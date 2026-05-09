# Stage 2 Implementation Batches（RAG + LLM，供 AI Agent 直接执行）

## 总原则

- 只做新的 Stage 2：RAG + Gemini 智能检索 / 问答
- 基于当前已完成的 Stage 1 数据底座继续开发
- 每个 batch 完成后必须：
  - 本地验证
  - 更新文档
  - git commit

---

## Batch 1：智能检索底座

### 目标

让系统能接收自然语言查询，并返回相关论文列表。

### 本批只做

- query schema
- query parser（规则 + Gemini 辅助）
- metadata 混合召回
- 基础 chat search API
- 中文 / 英文 / 中英混合 query 基础支持

### 交付物

- `POST /api/chat/search`
- structured query 输出
- top-k paper results
- 中文 query 可直接触发检索，不要求用户先手动翻成英文

### 不做

- 不做回答生成
- 不做多轮上下文
- 不做全文 chunk

---

## Batch 2：摘要级问答

### 目标

基于召回论文摘要生成回答。

### 本批只做

- context builder
- Gemini answer pipeline
- citations schema
- answer API
- 中文回答与中文引用解释支持

### 交付物

- `POST /api/chat/answer`
- answer + citations 输出
- 论文引用列表
- 中文提问默认中文回答（保留必要英文论文名与术语）

### 不做

- 不做全文 chunk 证据
- 不做复杂 compare / summarize mode

---

## Batch 3：多轮对话上下文

### 目标

支持用户追问和缩小 / 扩大检索范围。

### 本批只做

- chat session state
- message persistence
- refine / expand / compare 基础支持
- 中文多轮追问上下文延续

### 交付物

- session model
- message model
- 会话上下文检索逻辑

---

## Batch 4：全文 chunk RAG

### 目标

让系统能基于全文片段回答更细问题。

### 本批只做

- `paper_chunks` 数据模型
- chunk embedding
- chunk retrieval
- chunk citations

### 交付物

- chunk ingestion/retrieval pipeline
- chunk-based answer context

---

## Batch 5：多论文比较与归纳

### 目标

支持 compare / summarize / trend 分析。

### 本批只做

- compare mode
- summarize mode
- grouped citations

### 交付物

- 多论文比较回答结构
- 主题归纳回答结构

---

## Batch 6：前端对话入口

### 目标

提供一个可直接对话的前端页面。

### 本批只做

- chat UI
- citations rendering
- paper result cards
- session continuation

### 交付物

- chat page
- answer/citation UI

---

## Batch 7：质量、日志与验收

### 目标

把系统打磨成可持续迭代的智能检索能力。

### 本批只做

- query / answer logging
- retrieval quality review
- evaluation cases
- Stage 2 acceptance doc

### 交付物

- logs / eval cases
- stage2 acceptance doc

---

## 每个 batch 的统一输出要求

1. 改了哪些文件
2. 实现了什么
3. 如何验证
4. 当前还没做什么
5. 下一批建议做什么
