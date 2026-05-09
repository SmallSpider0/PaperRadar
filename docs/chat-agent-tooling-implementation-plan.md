# PaperRadar Chat：LLM 主导 + 论文工具化检索 + 引用体验升级实施方案

更新日期：2026-03-27

## 1. 背景与目标

当前 Stage 2 的 chat search 已具备：

- 自然语言检索
- 摘要级问答
- 多轮会话继承
- Recent Sessions 前端恢复
- topic profile / broad-topic / rerank 等检索增强

但现阶段暴露出的核心问题也越来越明确：

1. 用户真实问题往往不是“标准检索语句”，而是开放式研究问题
2. 规则 parser 很难长期覆盖 refine / expand / compare / summarize 等复杂问法
3. 当前系统的主要矛盾正在从“能不能解析 query”转向“LLM 如何更自然地驱动检索与证据组织”
4. 当前引用体验仍偏工程调试风格，不够适合真实研究助手场景

因此，下一阶段建议将 PaperRadar Chat 的主线从：

- 用户问句 → parser → 固定检索 → answer

升级为：

- 用户问句 → LLM 决策是否调用论文工具 → 多步检索/过滤/比较 → 基于结构化证据回答 + 更美观的引用块

一句话目标：

**把 PaperRadar Chat 从“规则主导的检索接口”升级成“LLM 主导的论文研究助手”，底层论文检索退到 tool 层，专注做高质量证据供应。**

---

## 2. 设计原则

### 2.1 总体原则

1. **LLM 提高自由度，但不直接碰底层数据库与 SQL**
2. **底层检索继续保留强约束，作为可控工具层**
3. **回答必须基于工具返回的证据，不允许凭空补全论文事实**
4. **引用块与证据块要产品化，不再只做调试型平铺列表**
5. **优先做轻量 agentic orchestration，不引入过重的通用 agent 框架**
6. **保留现有 parser / search / rerank 资产，先降级为 fallback 与 bootstrap，而不是直接推翻重写**

### 2.2 与当前系统的关系

本方案不是否定现有 Stage 2，而是对其职责重分配：

- `chat_parser.py`：从“主驱动入口”降级为“fallback / retrieval bootstrap”
- `chat_search.py` / `search.py`：从“面向用户的搜索结果层”升级为“面向 LLM 的 paper tool 层”
- `chat_answer.py`：从“固定上下文回答器”升级为“由 orchestration 驱动的 evidence-aware answer 生成器”
- 前端 `/chat`：从“搜索 + 回答展示页”升级为“研究助手对话界面 + 证据引用界面”

---

## 3. 目标架构

建议将新一轮 Chat 架构拆成四层：

### 3.1 Conversation Orchestrator（LLM 主控层）

职责：

- 理解用户消息意图
- 判断本轮是否需要调用工具
- 决定调用哪个工具、调用几次
- 基于工具结果组织回答
- 生成 citations / used_papers / follow-up suggestions

建议支持的高层意图包括：

- `search`
- `refine`
- `expand`
- `compare`
- `summarize`
- `ask_clarification`
- `answer_from_context`
- `request_more_evidence`

### 3.2 Paper Tools（论文工具层）

职责：

- 向 LLM 提供高质量候选论文
- 提供可解释的 match reasons / topic signals / metadata
- 支持 session candidate 上的二次过滤与 rerank
- 后续支持 chunk 级证据

### 3.3 Evidence / Citation Layer（证据层）

职责：

- 给 LLM 稳定可引用的 citation labels
- 给前端可渲染的 reference cards / evidence cards
- 给后续 chunk RAG 预留扩展结构

### 3.4 Frontend Rendering Layer（展示层）

职责：

- 渲染回答正文中的引用锚点
- 渲染 reference cards
- 提供点击跳转 / hover card / 详情抽屉
- 提供快捷追问入口

---

## 4. 为什么要从 parser 主导转向 LLM 主导

### 4.1 当前 parser 主导模式的局限

当前模式适合：

- 单轮检索
- 明确 topic + venue + year 的问法
- 较规则的 refine / expand

但在以下问题上会越来越脆：

- “帮我比较一下这些论文里哪篇更偏工程实现？”
- “这几篇工作有什么共同趋势？”
- “如果我只关心真实部署场景，应该先读哪几篇？”
- “把刚才的范围扩大到邻近方向，但不要太偏”
- “我不想看 survey，只要近两年的方法型论文”

这类问题本质上更接近“研究助手任务规划”，而不是“结构化 query 抽取”。

### 4.2 转向 LLM 主导后的好处

转向后：

- LLM 可以根据上下文灵活决定是否重搜、缩小、扩展或比较
- follow-up 逻辑不需要全部编码在规则里
- compare / summarize / trend 分析会自然很多
- parser 不再承担全部复杂度，只保留在简单 query 上的高效价值

### 4.3 需要避免的误区

本方案并不是让 LLM“完全自由发挥”，而是：

- **LLM 自由决定工具调用策略**
- **工具输出保持结构化与可控**
- **回答严格以工具证据为边界**

---

## 5. 统一 API 方向：收口到 `/api/chat/message`

当前 search / answer / message 的心智模型较分裂。建议后续逐步收口到统一入口：

```http
POST /api/chat/message
```

输入示意：

```json
{
  "session_id": "...",
  "message": "帮我比较一下这些论文的差异"
}
```

输出示意：

```json
{
  "session_id": "...",
  "message_id": "...",
  "assistant": {
    "answer_markdown": "这些工作大致可以分为三类...[P1][P2][P4]",
    "citations": [...],
    "used_papers": [...],
    "followup_suggestions": [...]
  },
  "trace": {
    "tool_calls": [
      {
        "tool": "search_papers",
        "summary": "retrieved 12 papers for llm jailbreak defense in 2025"
      }
    ]
  }
}
```

### 5.1 为什么统一入口更合理

因为在新架构里：

- search 只是 LLM 的中间动作
- answer 只是工具编排后的最终输出
- 对用户而言，入口始终是“发一条消息”

因此不建议长期并行维护“用户显式 search / answer”两套产品心智。

### 5.2 过渡期策略

短期内可保留：

- `/api/chat/search`
- `/api/chat/answer`
- `/api/chat/message`

但内部新逻辑优先建设在 `/api/chat/message`，其他接口逐步转为兼容层或调试入口。

---

## 6. 论文工具层设计

这里的重点是：**工具输出要从“面向用户的搜索结果”改成“面向 LLM 的结构化证据”。**

### 6.1 工具一：`search_papers`

用途：

- 给 LLM 一批候选论文
- 支持 broad / focused / follow-up / similarity 等检索策略

输入建议：

```json
{
  "query": "LLM jailbreak defenses in 2025",
  "session_id": "...",
  "filters": {
    "venues": ["NDSS", "USENIX_SECURITY"],
    "years": [2025]
  },
  "strategy": "broad",
  "top_k": 20
}
```

输出建议：

```json
{
  "query_summary": "papers about llm jailbreak defenses in 2025",
  "applied_filters": {
    "venues": ["NDSS", "USENIX_SECURITY"],
    "years": [2025]
  },
  "results": [
    {
      "paper_id": "...",
      "title": "...",
      "venue": "NDSS",
      "year": 2025,
      "authors": ["...", "..."],
      "abstract": "...",
      "source_url": "...",
      "topic_tags": ["llm safety", "prompt injection"],
      "relevance": {
        "score": 0.83,
        "why_matched": [
          "title mentions jailbreak defense",
          "topic tags include llm safety",
          "year filter matched 2025"
        ]
      },
      "citation": {
        "label": "P1",
        "display_text": "Title (NDSS 2025)"
      }
    }
  ]
}
```

#### 设计要求

- 输出必须可供 LLM 直接拿来引用
- `why_matched` 需要可解释，便于 answer prompt 使用
- `citation.label` 要稳定，支持后续正文中嵌入 `[P1]`
- 默认 top_k 应大于当前用户可见列表的数量，因为它是给 LLM 用的候选池

---

### 6.2 工具二：`get_paper_details`

用途：

- 用户追问某篇论文时补信息
- compare 前补齐关键元数据
- 展示 citation card / details drawer

输出建议包含：

- `paper_id`
- `title`
- `authors`
- `venue`
- `year`
- `abstract`
- `source_url`
- `pdf_url`（如果有）
- `topic_tags`
- `topic_summary`
- `citation_preview`

此工具的目标是“单篇深入查看”，避免把所有大字段都塞到 search 结果里。

---

### 6.3 工具三：`filter_or_rerank_candidates`

用途：

- 对 session 当前候选集做二次过滤或重排
- 避免每次 follow-up 都从全库重搜

输入示意：

```json
{
  "candidate_ids": ["p1", "p2", "p3"],
  "instruction": "prefer practical deployment papers over theoretical analysis"
}
```

输出建议：

- reranked candidate list
- each candidate 的 lightweight reasons
- optional removed candidates summary

#### 典型场景

- “只保留更偏工程实现的”
- “不要 survey”
- “只看真正做 defense 的，不要 attack paper”
- “把刚才结果里更像系统安全的优先”

---

### 6.4 工具四：`compare_papers`

用途：

- 对多篇论文生成结构化比较骨架
- 降低主回答 LLM 在 compare 任务中的组织负担

输入：

- `paper_ids`
- `compare_dimensions`（可选）

输出建议包含：

- `problem`
- `approach`
- `setting`
- `strengths`
- `limitations`
- `notable_difference`

该工具输出不一定直接给前端，而是优先供主回答 LLM 做语言组织。

---

### 6.5 后续工具预留：`search_chunks`

当摘要级问答稳定后，再引入：

- `search_chunks`
- `get_chunk_context`

用于支持全文片段级证据与更细粒度问答。

当前不作为优先实施项。

---

## 7. Orchestration 设计

### 7.1 每轮对话的推荐流程

建议采用轻量 orchestration：

1. 读取当前用户消息
2. 读取最近 session state / candidate papers / 上一轮 citations
3. 由 LLM 判断：
   - 是否已有足够上下文可直接回答
   - 是否需要 search
   - 是否需要 rerank/filter
   - 是否需要 compare
   - 是否需要澄清
4. 最多调用 1~3 次工具
5. 生成：
   - `answer_markdown`
   - `citations`
   - `used_papers`
   - `followup_suggestions`

### 7.2 为什么要限制工具调用次数

不建议放开成无限循环 agent，原因：

- token 与延迟不可控
- 工具调用路径更难回归测试
- 用户感知收益未必和复杂度成正比

首版建议约束：

- 每轮最多 2~3 次工具调用
- 如果证据不足，可以明确说不足，而不是继续无限重试

### 7.3 parser 的新定位

保留现有 parser，但用途改为：

- 简单 query 的快捷 bootstrap
- filters / venue / year 的快速抽取
- LLM tool planning 失败时的 fallback
- benchmark / 回归的可解释 baseline

即：**从主引擎降级为稳态兜底层。**

---

## 8. Citation / 引用块升级方案

这是本轮非常值得投入的产品升级点。

### 8.1 目标

引用系统需要同时满足：

- 让 LLM 易于使用
- 让用户易于点击与验证
- 为前端提供更好的 hover / drawer / link 能力
- 为后续 chunk/page/snippet 引用预留扩展

### 8.2 回答正文中的引用锚点

建议正文中使用：

- `[P1]`
- `[P2]`
- `[P1][P3]`

由前端将其渲染为可交互引用锚点。

### 8.3 建议的 citation schema

```json
{
  "answer_markdown": "2025 年相关工作主要分为三类...[P1][P3][P5]",
  "citations": [
    {
      "id": "c1",
      "label": "P1",
      "paper_id": "...",
      "title": "...",
      "venue": "NDSS",
      "year": 2025,
      "authors_short": "Alice et al.",
      "source_url": "...",
      "pdf_url": "...",
      "role": "representative",
      "relevance_note": "代表 inference-time guardrail 路线",
      "evidence_type": "paper"
    }
  ]
}
```

### 8.4 前端表现形式建议

#### 正文锚点

- hover：显示 mini card
- click：打开论文详情抽屉或跳外链

#### Reference Cards（回答下方）

每条 citation card 建议展示：

- 标题（可点击）
- venue + year
- authors 简写
- `relevance_note`
- 操作入口：
  - 查看摘要
  - 打开原文
  - 查看类似论文（后续）

#### Used Papers 面板

建议额外展示：

- 本轮回答基于哪些论文
- 当前 session 候选集有多少篇
- 本轮实际引用了哪几篇

这比单纯堆链接更适合研究助手场景。

### 8.5 预留的扩展字段

后续可扩展：

- `evidence_type = paper | abstract | chunk | quote`
- `anchor_text`
- `snippet`
- `page_range`
- `section`

因此首版 citation schema 不应只做“title + url”。

---

## 9. 前端改造建议

### 9.1 必做项

1. 支持正文中的 citation labels 渲染为可点击锚点
2. 增加回答下方的 reference cards 区域
3. 点击 citation 后可打开 detail drawer 或跳转外链
4. 渲染 `followup_suggestions`

### 9.2 强烈建议项

1. citation hover card
2. used papers / candidate set 可视化
3. “基于这些论文继续问”快捷入口，例如：
   - 比较这些论文
   - 只看 NDSS
   - 按方法分类
   - 哪篇最值得先读

### 9.3 UI 设计目标

目标不是把聊天页做成复杂工作台，而是：

- 回答可读
- 引用可点
- 证据可查
- 追问顺手

---

## 10. Prompt / 控制策略建议

### 10.1 系统层规则

给主回答 LLM 的规则建议明确写入：

1. 你是论文研究助手，不是通用闲聊机器人
2. 回答应优先基于工具返回的论文证据
3. 不要虚构论文、venue、年份、实验结果
4. 如果证据不足，要明确说不足
5. compare / summarize 时应区分明确证据与概括性判断
6. 引用论文时优先使用工具提供的 citation labels

### 10.2 工具使用约束

建议写明：

- 优先复用当前 session candidates
- 需要更宽召回时再重搜
- 默认每轮最多 2~3 次工具调用
- 无法支持结论时，不要无限尝试检索

---

## 11. 实施批次建议

建议按最小可交付路径推进，而不是一次性重写整个聊天系统。

### Batch A：工具输出重构（优先级最高）

目标：

- 保留现有 retrieval 内核
- 把 `chat search` 改造成面向 LLM 的 `search_papers` 工具输出
- 建立 citation schema

本批实现：

- 新建 / 重构 search tool response schema
- 给 search results 分配稳定 citation labels
- 补 `why_matched` / `relevance_note` / `used_papers` 等字段
- 保持旧接口兼容，先不动前端主流程

本批验证：

- 工具输出是否更适合 answer LLM 消费
- 同一批结果的 citation labels 是否稳定
- 当前 benchmark case 是否无明显回退

---

### Batch B：统一 message orchestration

目标：

- 让 `/api/chat/message` 成为主入口
- LLM 负责决定是否调用 search / rerank / compare 工具

本批实现：

- 增加 lightweight orchestration layer
- 支持一轮中 1~3 次 tool call
- parser 从主逻辑退为 fallback
- 输出统一的 assistant payload

本批验证：

- 单轮 search 问题
- follow-up refine / expand
- compare 问题
- 明显证据不足场景

---

### Batch C：Citation UX 升级

目标：

- 把回答引用体验做成真正可用的研究界面

本批实现：

- 正文 citation 锚点
- reference cards
- detail drawer / 外链跳转
- used papers 面板

本批验证：

- 点击引用是否稳定
- hover / drawer 是否正确展示对应论文
- 多篇 citation 场景是否可读

---

### Batch D：Candidate filtering / compare 深化

目标：

- 提高 follow-up / compare 的自然度与效率

本批实现：

- `filter_or_rerank_candidates`
- `compare_papers`
- richer follow-up suggestions

本批验证：

- “只看更偏工程实现的”
- “不要 survey”
- “比较这些论文的差异”
- “按方法分组总结”

---

### Batch E：Chunk RAG 工具化（后续阶段）

目标：

- 支持更细粒度证据与深入问答

本批实现：

- `search_chunks`
- chunk citation schema
- page / snippet 级 evidence payload

前提：

- 摘要级工具编排已稳定
- citation schema 已能平滑扩展

---

## 12. 建议的文件改动方向

以下为建议性映射，不要求一次改完。

### 后端

可能涉及：

- `app/backend/chat_models.py`
  - 增加 tool result / citation / assistant payload schema
- `app/backend/chat_search.py`
  - 从用户搜索结果层重构为 paper tool 输出层
- `app/backend/search.py`
  - 保持 retrieval 内核，补可解释信号输出
- `app/backend/chat_answer.py`
  - 改为基于 paper tool 结果组织回答
- `app/backend/chat_session_store.py`
  - 存储 used_papers / citations / tool traces
- `app/backend/main.py`
  - 推进 `/api/chat/message` 主入口能力

可新增：

- `app/backend/chat_orchestrator.py`
- `app/backend/chat_tools.py`
- `app/backend/citation_utils.py`

### 前端

可能涉及：

- `app/frontend/app/chat/...`
- citation renderer
- reference card components
- paper detail drawer
- used papers panel

---

## 13. 风险与控制点

### 13.1 风险：LLM 自由度提高后，工具调用不稳定

控制策略：

- 限制每轮 tool call 次数
- 做 tool trace logging
- 保留 parser fallback

### 13.2 风险：answer token 成本上升

控制策略：

- search tool 默认只返回关键字段
- abstract 长度截断
- 只给主 LLM 最相关的 top-N 证据

### 13.3 风险：citation schema 首版过于简陋，后续难扩展

控制策略：

- 首版就预留 `evidence_type / snippet / page_range / section`
- 不要只返回 title + url

### 13.4 风险：前端一次改太大

控制策略：

- 先做 citation 锚点 + reference cards
- hover card / detail drawer / candidate panel 分批推进

---

## 14. 推荐的实施顺序（结论版）

如果只选一条最稳的路径，建议按以下顺序做：

1. **先重构工具输出层**，把 retrieval 结果改成 LLM 可消费的 paper tools
2. **再建设统一 `/api/chat/message` orchestration**
3. **然后升级 citation / reference cards 前端体验**
4. **再做 candidate filtering / compare 深化**
5. **最后再接 chunk RAG**

不建议的顺序：

- 先上全文 chunk RAG
- 先大改 parser 规则
- 先做复杂通用 agent 框架

因为这些都不能直接解决当前“chat 应该更像研究助手而不是检索器”的主问题。

---

## 15. 一句话总结

本方案的核心不是“让 LLM 取代检索”，而是：

**让 LLM 成为主导交互与推理的研究助手，让底层检索成为高质量、可控、可引用的论文工具层。**

当这条线落地后，PaperRadar Chat 的体验会从：

- “检索接口 + 回答文本”

升级成：

- **“能对话、能追问、能比较、能点开证据、能顺着论文继续研究”的论文助手。**
