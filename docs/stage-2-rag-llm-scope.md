# Stage 2 范围说明（RAG + LLM 智能检索）

## 目标

Stage 2 调整为：基于 **RAG + Gemini API** 的智能检索与论文问答系统。

系统不再以“阅读页 / 报告页 / PPT”作为当前主线，而是优先建设：

- 自然语言检索论文
- 基于论文摘要 / 后续全文片段的问答
- 多论文比较与归纳
- 对话式 refine / narrow / expand
- **支持中文检索、中文提问与中文回答**

一句话：

**让用户像和研究助理对话一样检索、比较、追问论文。**

---

## 当前已具备的基础

Stage 1 已完成并可复用：

- PostgreSQL 论文主链路
- `papers` 表与 metadata 入库
- metadata embedding 已全量生成并回灌
- 当前稳定数据规模：1237 篇论文
- 已补摘要 1185 篇
- 基础搜索底座已具备

这些能力将直接作为 Stage 2 的 RAG 检索底座。

---

## Stage 2 包含

### 1. 智能检索

支持用户直接自然语言提问：

- 找某主题论文
- 找某会议 / 某年份论文
- 找某类 attack / defense / survey
- 找和某篇论文相似的论文
- **支持中文问题直接检索英文论文库**（如“2025 年关于 LLM 越狱的论文有哪些？”）

### 2. 基于摘要的问答

支持基于召回论文的摘要做回答：

- 单篇论文问答
- 多篇论文比较
- 某主题简要总结
- 哪些论文更值得先读
- **用户可用中文提问，系统优先用中文回答**（论文标题、会议名等专有名词可保留英文）

### 3. 对话式上下文

支持：

- refine（进一步缩小）
- expand（进一步扩展）
- compare（比较）
- summarize（归纳）

### 4. 语言支持要求

Stage 2 需要默认支持：

- 中文检索英文论文库
- 中文提问 / 中文追问
- 中文回答 / 中文总结
- 中英混合 query（如“帮我找 NDSS 2024 里 browser fingerprinting 的论文”）

初期允许通过规则解析 + Gemini 辅助完成中英混合理解，不要求一开始就做复杂多语种 NLP 管线。

### 5. 后续全文 chunk RAG

在摘要级问答稳定后，再接入：

- 全文 chunk 存储
- chunk embedding
- chunk-level evidence
- 更细粒度问答

---

## Stage 2 不包含

当前阶段不再作为主线推进：

- 不优先做 HTML 阅读页
- 不优先做单篇报告页
- 不优先做 PPT 生成
- 不优先做报告状态管理

这些旧 Stage 2 方案已转入归档，后续若需要可重新启用。

---

## 核心架构

### 数据层

复用现有：

- `papers`
- `paper_metadata_embeddings`

后续新增：

- `rag_sessions`
- `rag_messages`
- `paper_chunks`
- `paper_chunk_embeddings`
- `rag_citations`

### 检索层

分两级：

1. metadata 混合检索
   - keyword
   - metadata embedding
   - venue/year filters

2. chunk 检索（后续）
   - chunk embedding
   - chunk keyword / BM25
   - rerank

### 推理层

- query understanding
- retrieval orchestration
- answer generation（Gemini API）

### 交互层

- chat API
- citations
- paper cards
- 多轮上下文

---

## MVP 范围

第一版先实现：

1. 用户自然语言问题输入
2. query understanding
3. metadata 混合召回 top-k papers
4. 基于摘要构造上下文
5. Gemini 生成回答
6. 返回答案 + 引用论文列表

暂不做：

- chunk RAG
- 复杂 agent 自动规划
- 报告页 / PPT
- 复杂前端工作台

---

## 设计原则

1. **先做摘要级 RAG，再做全文级 RAG**
2. **必须输出 citations，降低幻觉**
3. **优先复用 Stage 1 数据底座，不重新起炉灶**
4. **中文体验优先可用，不强求首版就做到完美翻译与完美术语统一**
5. **每一批都要能独立验证，不做一口气大重构**

---

## 一句话结论

当前 Stage 2 的主线已经调整为：

**围绕现有论文数据库与 embedding，构建基于 Gemini API 的对话式论文检索、问答与比较系统。**
