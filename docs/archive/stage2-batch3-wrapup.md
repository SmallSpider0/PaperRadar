# Stage 2 / Batch 3 收尾说明（多轮对话上下文）

## 本批目标

让 PaperRadar 的 RAG Chat 支持基础多轮对话：

- 会话持久化
- 消息持久化
- session continuation
- refine / expand / compare 基础上下文继承

---

## 已完成

### 1. 会话与消息持久化

后端已落地：

- `rag_sessions`
- `rag_messages`

并通过 `chat_session_store.py` 提供：

- 创建会话
- 追加消息
- 读取会话
- 读取最近消息
- 获取最近一次回答 payload

### 2. 统一消息入口

已提供：

- `POST /api/chat/message`

该接口会：

- 创建/续接 session
- 持久化 user / assistant message
- 返回当前 session、messages、answer

### 3. 前端 session continuation

`/chat` 页面已接入：

- `session_id`
- 多轮 message 展示
- 基于同一 session 的继续提问

### 4. follow-up 上下文继承（本次收尾补齐）

本次补齐了 Batch 3 最缺的一块：

- 识别 follow-up 类型：`refine / expand / compare`
- 从最近消息中恢复上一轮 structured query
- 将上一轮的 topic / filters / candidate papers 作为会话上下文提示传入回答链路
- 对 follow-up 请求做基础 override：
  - `expand`：继承上一轮 topic / filters
  - `refine`：继承上一轮 topic / filters，并优先约束到上一轮候选论文集合
  - `compare`：优先基于上一轮候选论文集合做比较

### 5. 验证中修复的问题

在联调过程中发现：

- 初版把上下文提示直接拼进 query，污染了 parser 的 topic 提取

已修复为：

- query 继续用于结构化解析
- context hint 单独传入 LLM prompt
- 避免 `StructuredQuery.topic` 被提示文本污染

---

## 已验证

通过本地脚本串行验证了以下多轮链路：

1. `2025 年有哪些关于 LLM 越狱的论文？`
2. `再扩大一点，补充更多相关工作`
3. `只看 NDSS 的`
4. `比较一下这些论文的差异`

验证结果：

- session 可以持续复用
- messages 可以持续写入与回读
- compare / refine / expand 的 follow-up 识别已生效
- structured query 可以继承上一轮 topic / filters
- compare 会优先沿用上一轮候选论文集合

---

## 当前仍未解决 / 不属于本批收尾的部分

### 1. 检索质量仍可能跑偏

虽然 Batch 3 的上下文继承已补齐，但底层 `search_metadata()` 在某些组合条件下仍可能召回不够相关的论文，例如：

- `LLM 越狱 + NDSS 2025`

这属于：

- 检索排序质量
- metadata recall 质量
- query rewrite / rerank 策略

更适合作为：

- Batch 2 稳定性补强
- 或后续 Batch 7 质量评估

### 2. 还不是完整的对话规划器

当前只做了基础 follow-up 规则，不包含：

- 复杂 query rewrite pipeline
- 显式的 conversation planner
- 真正的多步 agent orchestration

这符合 Batch 3 的“基础支持”范围。

---

## 本批涉及的主要文件

- `app/backend/chat_message.py`
- `app/backend/chat_session_store.py`
- `app/backend/chat_answer.py`
- `app/backend/chat_models.py`
- `app/backend/main.py`
- `app/frontend/pages/chat.js`

---

## 如何验证

### 1. 语法检查

```bash
python3 -m py_compile \
  app/backend/chat_message.py \
  app/backend/chat_session_store.py \
  app/backend/chat_answer.py \
  app/backend/chat_models.py \
  app/backend/chat_parser.py \
  app/backend/chat_search.py \
  app/backend/main.py
```

### 2. 多轮链路验证

可在项目根目录执行：

```bash
cd /opt/paperradar
PYTHONPATH=app python3 - <<'PY'
from backend.chat_message import run_chat_message

queries = [
    "2025 年有哪些关于 LLM 越狱的论文？",
    "再扩大一点，补充更多相关工作",
    "只看 NDSS 的",
    "比较一下这些论文的差异",
]

session_id = None
for query in queries:
    resp = run_chat_message(query=query, session_id=session_id, top_k=5)
    session_id = resp.session.get('id')
    print(query)
    print(resp.answer.structured_query.model_dump())
    print([paper.title for paper in resp.answer.papers[:3]])
    print('---')
PY
```

---

## 结论

Batch 3 现在已经达到“可交付的基线完成”状态：

- 会话持久化已通
- 多轮 continuation 已通
- follow-up 上下文继承已补齐
- compare / refine / expand 已具备基础可用性

但检索质量本身仍有提升空间，下一步更适合转向：

- 检索质量补强 / query rewrite / rerank
- 或直接进入 Batch 4（全文 chunk RAG）
