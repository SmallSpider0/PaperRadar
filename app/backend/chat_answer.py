from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import requests

from backend.chat_models import ChatAnswerResponse, ChatSearchResponse, Citation, PaperToolResponse, RetrievalPaper, StructuredQuery
from backend.chat_search import run_chat_search
from backend.config import settings
from backend.llm_usage import log_llm_usage


CONCLUSION_MARKERS = ["结论", "总结", "简而言之", "总体来看", "根据当前检索到的论文"]
EVIDENCE_MARKERS = ["具体来说", "依据", "支持点", "原因", "以下论文"]
NON_RETRIEVAL_FOLLOWUPS = {
    "chat": ["帮我找 2025 年 NDSS 的 prompt injection 论文", "比较一下上面这些论文", "这个聊天页怎么用"],
    "meta": ["你能基于库里的论文回答什么问题", "怎么在这里比较论文", "帮我解释一下当前能力边界"],
    "help": ["帮我找近两年的 LLM safety 论文", "比较这些论文的差异", "只看更偏工程实现的论文"],
    "ask_clarification": ["帮我找 prompt injection 相关论文", "比较上一轮这些论文", "解释一下这个系统怎么用"],
}


def _emit_progress(progress_callback: Callable[[dict], None] | None, **payload) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(payload)
    except Exception:
        return


def _truncate(text: str | None, limit: int = 1200) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _select_papers(papers: list[RetrievalPaper], limit: int = 5) -> list[RetrievalPaper]:
    ranked = sorted(papers, key=lambda paper: (paper.score, bool(paper.abstract), paper.year or 0), reverse=True)
    return ranked[:limit]


def _paper_snippet(paper: RetrievalPaper, limit: int = 320) -> str:
    return _truncate(paper.abstract, limit) or "No abstract available."


def _programmatic_reason(paper: RetrievalPaper, query: str) -> str:
    pieces: list[str] = []
    if paper.venue_code and paper.year:
        pieces.append(f"该论文来自 {paper.venue_code} {paper.year}")
    elif paper.venue_code:
        pieces.append(f"该论文来自 {paper.venue_code}")
    if paper.match_reasons:
        pieces.append("命中原因：" + "；".join(paper.match_reasons[:2]))
    snippet = _paper_snippet(paper, 160)
    if snippet and snippet != "No abstract available.":
        pieces.append("摘要证据：" + snippet)
    else:
        pieces.append(f"与问题“{query}”在检索阶段高度相关")
    return "；".join(pieces)


def _derive_limitations(selected_papers: list[RetrievalPaper], raw_limitations: list[Any], query: str) -> list[str]:
    limitations: list[str] = [str(item).strip() for item in raw_limitations if str(item).strip()]

    missing_abstracts = [paper.title for paper in selected_papers if not (paper.abstract or "").strip()]
    if missing_abstracts:
        limitations.append("部分候选论文缺少摘要，当前回答对这些论文的判断会更弱。")

    if any(keyword in query.lower() for keyword in ["why", "how", "细节", "实验", "参数", "threat model", "证据"]):
        limitations.append("当前基于摘要级证据，涉及实验细节、参数或 threat model 的结论可能不足。")

    if not limitations:
        limitations.append("当前回答基于摘要级检索结果，尚未使用全文 chunk 证据。")

    deduped: list[str] = []
    seen = set()
    for item in limitations:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


def _build_context(papers: list[RetrievalPaper]) -> str:
    blocks: list[str] = []
    for idx, paper in enumerate(papers, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[Paper {idx}]",
                    f"Paper ID: {paper.paper_id or 'unknown'}",
                    f"Title: {paper.title}",
                    f"Venue: {paper.venue_code or 'unknown'}",
                    f"Year: {paper.year or 'unknown'}",
                    f"Abstract: {_truncate(paper.abstract, 420) or 'N/A'}",
                    f"Why relevant: {'; '.join((paper.match_reasons or [])[:2]) or 'retrieved by semantic search'}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _build_grounded_system_instruction() -> str:
    return """
你是 PaperRadar 的论文问答助手。请严格只根据给定论文上下文回答，不要编造未提供的事实。

硬性要求：
1. 用户用中文提问时，默认用中文回答。
2. 论文标题、会议名、作者名、必要术语可以保留英文。
3. 如果上下文不足以支持判断，要明确写出“根据当前检索到的论文，暂时无法确定”。
4. 不要声称读过全文；你当前只有摘要级证据。
5. 尽量引用具体论文标题，不要泛泛而谈。
6. 只输出严格 JSON 对象，不要输出 markdown，不要输出代码块，不要输出额外说明。
7. answer 保持简短：1段结论 + 最多3条依据。
8. citations 最多返回3条，limitations 最多返回2条。
""".strip()


def _build_tool_context(
    tool_calls: list[dict[str, Any]] | None = None,
    compare_result: dict[str, Any] | None = None,
    filter_result: dict[str, Any] | None = None,
) -> str:
    lines: list[str] = []
    if tool_calls:
        lines.append("[Tool Trace]")
        for index, call in enumerate(tool_calls, start=1):
            tool = call.get("tool") or "unknown_tool"
            summary = call.get("summary") or ""
            planner_reason = call.get("planner_reason") or ""
            args = call.get("args") or {}
            lines.append(f"{index}. tool={tool}")
            if summary:
                lines.append(f"   summary: {summary}")
            if planner_reason:
                lines.append(f"   planner_reason: {planner_reason}")
            if args:
                lines.append(f"   args: {json.dumps(args, ensure_ascii=False)}")
    if compare_result:
        lines.append("")
        lines.append("[Compare Result]")
        if compare_result.get("summary"):
            lines.append(f"summary: {compare_result['summary']}")
        for row in (compare_result.get("rows") or [])[:4]:
            row_bits = [row.get("title") or "unknown"]
            if row.get("problem"):
                row_bits.append(f"problem={row['problem']}")
            if row.get("approach"):
                row_bits.append(f"approach={row['approach']}")
            lines.append("- " + " | ".join(row_bits))
    if filter_result:
        lines.append("")
        lines.append("[Filter Result]")
        if filter_result.get("summary"):
            lines.append(f"summary: {filter_result['summary']}")
        for item in (filter_result.get("results") or [])[:6]:
            title = item.get("title") or "unknown"
            tags = ", ".join(item.get("topic_tags") or [])
            lines.append(f"- {title}" + (f" | tags={tags}" if tags else ""))
    return "\n".join(lines).strip()


def _build_grounded_user_prompt(
    query: str,
    context: str,
    context_hint: str | None = None,
    *,
    tool_context: str | None = None,
) -> str:
    schema = {
        "answer": "string",
        "citations": [{"paper_id": "string", "title": "string", "reason": "string"}],
        "limitations": ["string"],
    }
    schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    return f"""
只返回一个 JSON 对象，字段严格限制为 answer/citations/limitations。
不要输出 markdown，不要输出代码块，不要补充解释。

JSON schema:
{schema_text}

额外限制：
- answer 用中文，控制在 120-220 字。
- citations 最多 3 条。
- limitations 最多 2 条。
- 如果证据不足，answer 直接明确说暂时无法确定。

用户问题：
{query}

会话上下文提示：
{context_hint or 'N/A'}

论文上下文：
{context}

工具摘要：
{tool_context or 'N/A'}
""".strip()


def _build_direct_system_instruction(mode: str) -> str:
    base = """
你是 PaperRadar 的 AI 研究助手。
你既可以与用户正常聊天，也可以说明如何基于库里的论文完成检索、比较和归纳。
如果当前问题不需要查论文，就直接自然回答，不要强行编造检索过程。
只输出 JSON，不要输出 Markdown 代码块。
""".strip()
    if mode == "meta":
        return base + "\n重点说明你的角色是 PaperRadar 内的论文研究助手。"
    if mode == "help":
        return base + "\n重点说明这个页面如何使用，以及适合提什么类型的问题。"
    if mode == "ask_clarification":
        return base + "\n如果用户的话过于简短或缺少上下文，请先温和澄清，不要擅自发起论文检索。"
    return base


def _build_direct_user_prompt(
    query: str,
    *,
    mode: str,
    context_hint: str | None = None,
    context_papers: list[dict] | None = None,
) -> str:
    schema = {
        "answer": "string，中文为主，自然回复，不要伪造论文证据。",
        "followup_suggestions": ["string"],
    }
    schema_text = json.dumps(schema, ensure_ascii=False)
    context_titles = [paper.get("title") for paper in (context_papers or [])[:5] if paper.get("title")]
    return f"""
输出 JSON schema：
{schema_text}

当前模式：
{mode}

用户消息：
{query}

会话上下文提示：
{context_hint or 'N/A'}

最近候选论文标题（如有）：
{" | ".join(context_titles) if context_titles else 'N/A'}
""".strip()


def _resolve_gemini_model(model_name: str) -> str:
    normalized = (model_name or "").strip()
    aliases = {
        "gemini-3.1-flash": "gemini-2.5-flash",
        "gemini-3-flash": "gemini-2.5-flash",
        "gemini-flash": "gemini-2.5-flash",
    }
    return aliases.get(normalized, normalized or "gemini-2.5-flash")


def _extract_text_response(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")

    parts = candidates[0].get("content", {}).get("parts", [])
    texts = [part.get("text", "") for part in parts if part.get("text")]
    answer = "\n".join(texts).strip()
    if not answer:
        raise RuntimeError("Gemini returned empty answer")
    return answer


def _extract_usage(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usageMetadata") or {}
    prompt_tokens = int(usage.get("promptTokenCount") or 0)
    completion_tokens = int(usage.get("candidatesTokenCount") or 0)
    total_tokens = int(usage.get("totalTokenCount") or (prompt_tokens + completion_tokens))
    thoughts_tokens = int(usage.get("thoughtsTokenCount") or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "thoughts_tokens": thoughts_tokens,
    }


def _merge_usage(base: dict[str, int] | None, inc: dict[str, int] | None) -> dict[str, int]:
    base = base or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "thoughts_tokens": 0}
    inc = inc or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "thoughts_tokens": 0}
    return {
        "prompt_tokens": int(base.get("prompt_tokens", 0)) + int(inc.get("prompt_tokens", 0)),
        "completion_tokens": int(base.get("completion_tokens", 0)) + int(inc.get("completion_tokens", 0)),
        "total_tokens": int(base.get("total_tokens", 0)) + int(inc.get("total_tokens", 0)),
        "thoughts_tokens": int(base.get("thoughts_tokens", 0)) + int(inc.get("thoughts_tokens", 0)),
    }


def _call_gemini(
    prompt: str,
    *,
    system_instruction: str | None = None,
    max_output_tokens: int = 2500,
    response_mime_type: str | None = "application/json",
    temperature: float = 0.1,
    usage_source: str | None = None,
    timeout_seconds: float = 40.0,
    thinking_budget: int | None = None,
) -> tuple[str, str | None, dict[str, int]]:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    resolved_model = _resolve_gemini_model(settings.gemini_model)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{resolved_model}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "topP": 0.8,
            "maxOutputTokens": max_output_tokens,
        },
    }
    if response_mime_type:
        payload["generationConfig"]["responseMimeType"] = response_mime_type
    if thinking_budget is not None:
        payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": max(0, int(thinking_budget))}
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    response = requests.post(
        url,
        headers={"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=max(5.0, float(timeout_seconds or 40.0)),
    )
    response.raise_for_status()
    payload = response.json()
    finish_reason = ((payload.get("candidates") or [{}])[0] or {}).get("finishReason")
    usage = _extract_usage(payload)
    if usage_source:
        log_llm_usage(
            source=usage_source,
            model=resolved_model,
            finish_reason=finish_reason,
            token_usage=usage,
        )
    return _extract_text_response(payload), finish_reason, usage


def _parse_answer_payload(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()

    candidates = [text]
    if "```json" in text:
        start = text.find("```json") + len("```json")
        end = text.find("```", start)
        if end != -1:
            candidates.insert(0, text[start:end].strip())
    elif "```" in text:
        start = text.find("```") + len("```")
        end = text.find("```", start)
        if end != -1:
            candidates.insert(0, text[start:end].strip())

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.insert(0, text[first_brace:last_brace + 1].strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, str):
                try:
                    reparsed = json.loads(parsed)
                    if isinstance(reparsed, dict):
                        reparsed["_parse_ok"] = True
                        return reparsed
                except json.JSONDecodeError:
                    return {
                        "answer": parsed.strip(),
                        "citations": [],
                        "limitations": ["模型返回了字符串化结果，已回退为纯文本答案。"],
                        "_parse_ok": False,
                    }
            if isinstance(parsed, dict):
                parsed["_parse_ok"] = True
                return parsed
        except json.JSONDecodeError:
            continue

    return {
        "answer": text,
        "citations": [],
        "limitations": ["模型未返回结构化 JSON，已回退为纯文本答案。"],
        "_parse_ok": False,
    }


def _normalize_answer_text(answer_text: str, citations: list[Citation], limitations: list[str]) -> str:
    text = answer_text.strip()
    if text.startswith("{") and '"answer"' in text:
        first_quote = text.find('"answer"')
        if first_quote != -1:
            text = text[text.find(':', first_quote) + 1 :].strip().lstrip('"').rstrip('}').strip()
            text = text.replace('\\n', '\n').replace('\\"', '"')

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        lines = ["根据当前检索到的论文，暂时无法确定。"]

    conclusion = lines[0]
    evidence_lines = []
    for line in lines[1:]:
        if any(marker in line for marker in CONCLUSION_MARKERS) and not evidence_lines:
            continue
        evidence_lines.append(line)

    if not evidence_lines:
        evidence_lines = [f"可参考论文：{citation.title}" for citation in citations[:3]]

    normalized = ["结论：", conclusion, "", "依据："]
    normalized.extend(f"- {line}" for line in evidence_lines[:4])

    if limitations:
        normalized.extend(["", "局限："])
        normalized.extend(f"- {item}" for item in limitations)

    return "\n".join(normalized).strip()


def _build_citations(selected_papers: list[RetrievalPaper], model_citations: list[dict[str, Any]], query: str) -> list[Citation]:
    paper_map = {paper.paper_id: paper for paper in selected_papers if paper.paper_id}
    title_map = {paper.title: paper for paper in selected_papers}

    citations: list[Citation] = []
    used_keys: set[str] = set()
    for item in model_citations:
        paper = None
        paper_id = item.get("paper_id")
        title = item.get("title")
        if paper_id and paper_id in paper_map:
            paper = paper_map[paper_id]
        elif title and title in title_map:
            paper = title_map[title]
        if not paper:
            continue

        key = paper.paper_id or paper.title
        if key in used_keys:
            continue
        used_keys.add(key)
        citations.append(
            Citation(
                id=f"citation-{paper.paper_id or len(citations) + 1}",
                label=paper.citation.label if paper.citation else None,
                paper_id=paper.paper_id,
                title=paper.title,
                venue_code=paper.venue_code,
                year=paper.year,
                paper_url=paper.paper_url,
                pdf_url=paper.source_pdf_url,
                score=paper.score,
                snippet=item.get("reason") or _programmatic_reason(paper, query),
                role="evidence",
                relevance_note=item.get("reason") or _programmatic_reason(paper, query),
                evidence_type="paper",
            )
        )

    if citations:
        return citations

    return [
        Citation(
            id=f"citation-{paper.paper_id or index}",
            label=paper.citation.label if paper.citation else None,
            paper_id=paper.paper_id,
            title=paper.title,
            venue_code=paper.venue_code,
            year=paper.year,
            paper_url=paper.paper_url,
            pdf_url=paper.source_pdf_url,
            score=paper.score,
            snippet=_programmatic_reason(paper, query),
            role="evidence",
            relevance_note=_programmatic_reason(paper, query),
            evidence_type="paper",
        )
        for index, paper in enumerate(selected_papers, start=1)
    ]


def _apply_follow_up_overrides(search_response, follow_up_overrides: dict | None):
    if not follow_up_overrides:
        return search_response

    structured_query = search_response.structured_query.model_copy(deep=True)
    override_topic = (follow_up_overrides.get("topic") or "").strip()
    override_filters = follow_up_overrides.get("filters") or {}
    override_paper_ids = set(follow_up_overrides.get("paper_ids") or [])

    if override_topic:
        structured_query.topic = override_topic
    if override_filters:
        structured_query.filters = structured_query.filters.model_validate(override_filters)

    results = search_response.results
    if override_paper_ids:
        filtered = [paper for paper in results if paper.paper_id in override_paper_ids]
        if filtered:
            results = filtered

    return search_response.model_copy(update={"structured_query": structured_query, "results": results})


def _build_used_papers(selected_papers: list[RetrievalPaper]) -> list[dict[str, Any]]:
    return [
        {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "venue_code": paper.venue_code,
            "year": paper.year,
            "paper_url": paper.paper_url,
            "citation_label": paper.citation.label if paper.citation else None,
        }
        for paper in selected_papers
    ]


def _build_search_response_from_context(query: str, structured_query: StructuredQuery, context_papers: list[dict] | None):
    context_models = [RetrievalPaper(**paper) for paper in (context_papers or [])]
    return ChatSearchResponse(
        query=query,
        structured_query=structured_query,
        results=context_models,
        retrieval_summary={
            "intent_label": "会话候选复用",
            "applied_filters": {},
            "query_variants": [],
            "query_type": structured_query.query_type,
            "embedding_variant_limit": 0,
            "recall_limit": 0,
            "result_count": len(context_models),
            "needs_fulltext": structured_query.needs_fulltext,
            "retrieval_backend": "session_context",
        },
        paper_tool=PaperToolResponse(
            tool_name="reuse_session_papers",
            query_summary=structured_query.topic or query,
            applied_filters={},
            results=context_models,
        ),
    )


def _build_direct_fallback_answer(query: str, mode: str, context_papers: list[dict] | None = None) -> tuple[str, list[str]]:
    if mode == "meta":
        return (
            "我是 PaperRadar 里的 AI 研究助手，可以直接聊天，也可以在需要时基于库里的论文帮你检索、比较和总结。",
            NON_RETRIEVAL_FOLLOWUPS["meta"],
        )
    if mode == "help":
        return (
            "你可以直接问我论文问题，比如按主题找论文、限定年份/会议、比较上一轮候选论文，或者让我总结某个方向的趋势。",
            NON_RETRIEVAL_FOLLOWUPS["help"],
        )
    if mode == "ask_clarification":
        if context_papers:
            return (
                "如果你想继续刚才那批论文，可以直接说“比较这些论文”“只看更偏工程实现的”或“按方法路线总结一下”。",
                NON_RETRIEVAL_FOLLOWUPS["ask_clarification"],
            )
        return (
            "我可以直接聊天，也可以帮你查论文。你可以继续具体一点，比如给我一个研究主题、论文集合，或者直接说明你想比较什么。",
            NON_RETRIEVAL_FOLLOWUPS["ask_clarification"],
        )
    return (
        "你好，我在这儿。你可以直接和我聊天，也可以让我基于 PaperRadar 里的论文帮你检索、比较和归纳。",
        NON_RETRIEVAL_FOLLOWUPS["chat"],
    )


def run_direct_chat_answer(
    query: str,
    *,
    mode: str = "chat",
    context_papers: list[dict] | None = None,
    context_hint: str | None = None,
    structured_query: StructuredQuery | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> ChatAnswerResponse:
    structured_query = structured_query or StructuredQuery(intent=mode, topic=query)
    _emit_progress(progress_callback, progress=0.14, stage="direct_prompt", message="准备普通对话提示词", mode=mode)
    prompt = _build_direct_user_prompt(
        query,
        mode=mode,
        context_hint=context_hint,
        context_papers=context_papers,
    )
    try:
        _emit_progress(progress_callback, progress=0.55, stage="direct_llm", message="生成普通对话回答", mode=mode)
        raw_answer, finish_reason, usage = _call_gemini(
            prompt,
            system_instruction=_build_direct_system_instruction(mode),
            max_output_tokens=900,
            response_mime_type="application/json",
            temperature=0.3,
        )
        payload = _parse_answer_payload(raw_answer)
        if finish_reason == "MAX_TOKENS" or not payload.get("_parse_ok"):
            raw_answer, _, retry_usage = _call_gemini(
                prompt,
                system_instruction=_build_direct_system_instruction(mode),
                max_output_tokens=1200,
                response_mime_type="application/json",
                temperature=0.3,
            )
            usage = _merge_usage(usage, retry_usage)
            payload = _parse_answer_payload(raw_answer)
        answer_text = (payload.get("answer") or "").strip()
        suggestions = [str(item).strip() for item in (payload.get("followup_suggestions") or []) if str(item).strip()]
        if not answer_text:
            raise RuntimeError("empty direct chat answer")
        model_status = "ok"
    except Exception as exc:
        answer_text, suggestions = _build_direct_fallback_answer(query, mode, context_papers=context_papers)
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        model_status = f"fallback:{type(exc).__name__}"
        _emit_progress(progress_callback, progress=0.9, stage="direct_fallback", message="普通对话模型异常，已回退", mode=mode)

    _emit_progress(progress_callback, progress=0.97, stage="direct_finalize", message="普通对话回答已生成", mode=mode)
    return ChatAnswerResponse(
        query=query,
        answer=answer_text,
        answer_markdown=answer_text,
        citations=[],
        papers=[],
        structured_query=structured_query,
        answer_summary={
            "model": _resolve_gemini_model(settings.gemini_model),
            "requested_model": settings.gemini_model,
            "model_status": model_status,
            "citation_count": 0,
            "paper_count": 0,
            "language": "zh-CN",
            "token_usage": usage,
            "limitations": [],
        },
        used_papers=[],
        followup_suggestions=suggestions or NON_RETRIEVAL_FOLLOWUPS.get(mode, NON_RETRIEVAL_FOLLOWUPS["chat"]),
    )


def run_grounded_chat_answer(
    query: str,
    *,
    paper_ids: list[str] | None = None,
    top_k: int = 8,
    context_papers: list[dict] | None = None,
    context_hint: str | None = None,
    follow_up_overrides: dict | None = None,
    search_response=None,
    tool_calls: list[dict[str, Any]] | None = None,
    compare_result: dict[str, Any] | None = None,
    filter_result: dict[str, Any] | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> ChatAnswerResponse:
    def _search_progress(payload: dict) -> None:
        local_progress = float(payload.get("progress") or 0.0)
        overall_progress = 0.06 + 0.66 * max(0.0, min(local_progress, 1.0))
        _emit_progress(progress_callback, progress=overall_progress, status="running", **payload)

    if search_response is None:
        _emit_progress(progress_callback, progress=0.04, stage="answer_prepare", message="准备问答检索")
        search_response = run_chat_search(query=query, top_k=top_k, progress_callback=_search_progress)
    elif isinstance(search_response, dict):
        search_response = ChatSearchResponse.model_validate(search_response)

    if context_papers and getattr(search_response, "results", None) is None:
        search_response = _build_search_response_from_context(query, StructuredQuery(intent="qa", topic=query), context_papers)

    search_response = _apply_follow_up_overrides(search_response, follow_up_overrides)
    papers = search_response.results

    if paper_ids:
        paper_id_set = set(paper_ids)
        filtered = [paper for paper in papers if paper.paper_id in paper_id_set]
        if filtered:
            papers = filtered
    elif context_papers:
        context_models = [RetrievalPaper(**paper) for paper in context_papers]
        lowered = query.lower()
        if any(keyword in lowered for keyword in ["哪几篇", "哪些", "更值得先读", "compare", "比较", "这些论文", "上面这些", "它们"]):
            papers = context_models

    selected_papers = _select_papers(papers, limit=min(top_k, 3))
    context = _build_context(selected_papers)
    tool_context = _build_tool_context(tool_calls=tool_calls, compare_result=compare_result, filter_result=filter_result)
    compare_only_prompt = bool(compare_result and (compare_result.get("rows") or []))
    if compare_only_prompt:
        compact_compare_context = json.dumps(
            {
                "summary": compare_result.get("summary"),
                "rows": (compare_result.get("rows") or [])[:4],
            },
            ensure_ascii=False,
        )
        prompt_context = "[Compare Context]\n" + compact_compare_context
        prompt_tool_context = "N/A"
    else:
        prompt_context = context
        prompt_tool_context = tool_context
    try:
        _emit_progress(progress_callback, progress=0.78, stage="answer_prompt", message="准备答案提示词")
        prompt = _build_grounded_user_prompt(query, prompt_context, context_hint=context_hint, tool_context=prompt_tool_context)
        _emit_progress(progress_callback, progress=0.84, stage="answer_llm", message="生成答案")
        raw_answer, finish_reason, usage = _call_gemini(
            prompt,
            system_instruction=_build_grounded_system_instruction(),
            max_output_tokens=1100,
        )
        payload = _parse_answer_payload(raw_answer)
        # Avoid truncated JSON: if we hit MAX_TOKENS or JSON parsing failed, retry once with more output tokens.
        if finish_reason == "MAX_TOKENS" or not payload.get("_parse_ok"):
            _emit_progress(progress_callback, progress=0.9, stage="answer_retry", message="答案格式不完整，正在重试")
            raw_answer, _, retry_usage = _call_gemini(
                prompt,
                system_instruction=_build_grounded_system_instruction(),
                max_output_tokens=1500,
            )
            usage = _merge_usage(usage, retry_usage)
            payload = _parse_answer_payload(raw_answer)
        limitations = _derive_limitations(selected_papers, payload.get("limitations") or [], query)
        citations = _build_citations(selected_papers, payload.get("citations") or [], query)
        answer_text = _normalize_answer_text(
            (payload.get("answer") or "").strip() or "根据当前检索到的论文，暂时无法确定。",
            citations,
            limitations,
        )
        model_status = "ok"
        _emit_progress(progress_callback, progress=0.97, stage="answer_finalize", message="整理引用与局限")
    except Exception as exc:
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        limitations = _derive_limitations(
            selected_papers,
            ["模型调用超时或异常，已降级为检索证据直出回答。"],
            query,
        )
        citations = _build_citations(selected_papers, [], query)
        if citations:
            evidence_lines = [f"- {item.title}（{item.venue_code or 'unknown'} {item.year or 'unknown'}）" for item in citations[:4]]
            answer_text = "\n".join(
                [
                    "结论：",
                    "基于当前检索结果，以下论文与问题最相关；模型生成暂不可用，先给出证据清单。",
                    "",
                    "依据：",
                    *evidence_lines,
                    "",
                    "局限：",
                    "- 当前为降级回答，未生成深度归纳结论。",
                ]
            )
        else:
            answer_text = "根据当前检索到的论文，暂时无法确定。"
        model_status = f"fallback:{type(exc).__name__}"
        _emit_progress(progress_callback, progress=0.95, stage="answer_fallback", message="模型异常，已降级为证据直出")

    return ChatAnswerResponse(
        query=query,
        answer=answer_text,
        answer_markdown=answer_text,
        citations=citations,
        papers=selected_papers,
        structured_query=search_response.structured_query,
        answer_summary={
            "model": _resolve_gemini_model(settings.gemini_model),
            "requested_model": settings.gemini_model,
            "model_status": model_status,
            "citation_count": len(citations),
            "paper_count": len(selected_papers),
            "language": "zh-CN",
            "token_usage": usage,
            "limitations": limitations,
        },
        used_papers=_build_used_papers(selected_papers),
        followup_suggestions=[
            "比较这些论文的差异",
            "只看其中更偏工程实现的",
            "按方法路线归纳这些论文",
        ],
        compare_result=compare_result,
        filter_result=filter_result,
    )


def run_chat_answer(
    query: str,
    paper_ids: list[str] | None = None,
    top_k: int = 8,
    context_papers: list[dict] | None = None,
    context_hint: str | None = None,
    follow_up_overrides: dict | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> ChatAnswerResponse:
    return run_grounded_chat_answer(
        query=query,
        paper_ids=paper_ids,
        top_k=top_k,
        context_papers=context_papers,
        context_hint=context_hint,
        follow_up_overrides=follow_up_overrides,
        progress_callback=progress_callback,
    )
