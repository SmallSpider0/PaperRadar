# Stage 2 实施方案（RAG + LLM 智能检索）

## 目标

把 PaperRadar 从“能搜论文”升级成“能和用户对话、检索、问答、比较论文”的系统。

核心能力：

- 智能检索
- 基于论文的问答
- 多论文比较
- 对话式追问

---

## 方案概览

### 输入

用户自然语言问题，例如：

- 2025 年有哪些关于 LLM jailbreak 的论文？
- 帮我比较几篇 watermarking 工作
- 哪篇更偏工程实现？
- 这些论文的共同趋势是什么？
- 帮我找 NDSS 2024 里 browser fingerprinting 的论文

要求：

- 支持中文 query
- 支持英文 query
- 支持中英混合 query

### 输出

系统返回：

- 自然语言回答
- 引用论文列表
- 每篇论文的基础信息
- 后续追问入口

语言要求：

- 若用户用中文提问，默认用中文回答
- 论文标题、作者名、会议名、术语可保留英文原文
- 必要时可在中文中补充英文关键词，方便继续检索

---

## 系统分层

### 1. Query Understanding

将用户问题转成结构化检索意图：

```json
{
  "intent": "search|qa|compare|summarize",
  "topic": "llm jailbreak",
  "filters": {
    "venues": ["IEEE_SP", "USENIX_SECURITY"],
    "years": [2025]
  },
  "top_k": 8,
  "needs_fulltext": false
}
```

第一版可以采用：

- 规则解析 + Gemini 辅助
- 中英混合词识别（如年份、会议简称、英文主题词、中文问题词）
- 不要求一开始就做复杂 function calling

### 2. Retrieval

第一版用 metadata 混合召回：

- keyword score
- metadata embedding cosine similarity
- title boost
- venue/year filter
- 中文 query 到英文 metadata 的检索兼容（可通过 query rewrite / query expansion 逐步增强）

输出 top-k papers。

### 3. Context Builder

将召回结果整理成 LLM 可消费上下文：

```text
[Paper 1]
Title:
Venue:
Year:
Authors:
Abstract:
Why relevant:
```

### 4. Answer Generation

用 Gemini API 基于上下文回答。

要求：

- 只根据提供上下文回答
- 不确定时明确说明
- 尽量引用论文标题
- 回答和 citations 结构化返回
- 中文提问默认输出中文答案，保留必要英文术语

### 5. Dialogue State

后续支持：

- refine
- expand
- compare
- summarize

通过 session state 记录上一轮召回结果与用户筛选上下文。

---

## 建议的数据模型扩展

### 现有可复用

- `papers`
- `paper_metadata_embeddings`

### 新增建议

- `rag_sessions`
  - id
  - user/session id
  - created_at
  - updated_at

- `rag_messages`
  - id
  - session_id
  - role
  - content
  - structured_query_json
  - answer_json

- `rag_citations`
  - id
  - message_id
  - paper_id
  - score
  - snippet

后续全文时新增：

- `paper_chunks`
- `paper_chunk_embeddings`

---

## API 建议

### 1. 智能检索

`POST /api/chat/search`

输入：

```json
{
  "query": "2025年关于secure aggregation的论文有哪些？"
}
```

输出：

```json
{
  "structured_query": {...},
  "results": [...]
}
```

### 2. 问答

`POST /api/chat/answer`

输入：

```json
{
  "query": "这些论文哪篇更偏工程实现？",
  "session_id": "...",
  "paper_ids": ["..."]
}
```

输出：

```json
{
  "answer": "...",
  "citations": [...],
  "papers": [...]
}
```

### 3. 多轮对话

`POST /api/chat/message`

用于统一承载：

- search
- qa
- compare
- summarize

第一版可先分 API，后续再收口统一。

---

## 质量要求

### 1. 回答必须带引用

最少返回：

- paper_id
- title
- venue
- year
- source_url

### 2. 不得凭空补全

若上下文不足，明确输出：

- 当前检索到的论文不足以支持该判断
- 需要全文级证据

### 3. 优先可解释性

让用户能看出来：

- 为什么这些论文被召回
- 回答主要基于哪几篇论文
- 中文回答中的关键英文术语对应什么检索意图

---

## 风险与约束

### 1. 仍有 52 篇缺摘要

影响：这部分论文在摘要级 RAG 中可用性较弱。

策略：

- 降低回答权重
- 需要时再接全文 / 外部补全

### 2. 只靠摘要无法回答深问题

例如：

- 详细 threat model
- 实验参数
- 关键定量结果

策略：

- 作为下一阶段接 chunk RAG

### 3. 幻觉风险

策略：

- answer 必须基于 context
- 强制输出 citations
- 不足则明确说不足
- 中文回答不要把英文术语强行翻成不准确的中文概念

---

## 一句话结论

这份方案的核心是：

**先做摘要级对话式 RAG，尽快让用户能“直接问论文”；等交互跑通后，再升级到全文 chunk 级问答。**
