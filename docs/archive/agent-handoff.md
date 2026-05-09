# PaperRadar Agent Handoff

## 1. 目标

这份文档用于把 PaperRadar 后续开发交给 AI agent 时，降低跑偏风险。

项目当前约束非常明确：

- 按三阶段推进
- 当前只做阶段一
- 默认 metadata-first
- fulltext-on-demand
- 不默认抓取论文 PDF 全文

---

## 2. 当前阶段范围

AI agent 当前只允许实现：

- 项目骨架
- 数据库 schema
- metadata crawler
- metadata ingest pipeline
- on-demand fulltext pipeline
- metadata / fulltext search API
- subscription API
- minimal frontend
- deployment templates

AI agent 当前不要实现：

- 完整 HTML 报告系统
- PPT 生成
- Nano Banana 配图
- 高级图谱可视化
- 复杂多租户权限系统
- 分布式大规模架构

---

## 3. 关键产品约束

### 3.1 不要默认抓 PDF

这是最重要的一条。

正确方式：

- crawler 只抓元数据、摘要、来源链接
- 全文抓取必须通过显式任务触发

错误方式：

- 在爬会议列表时顺手下载所有 PDF
- 在 ingest 时默认拉全文
- 在搜索时自动抓全文补索引

### 3.2 先做 metadata 检索

阶段一默认检索主链路应优先依赖：

- 标题
- 摘要
- metadata embedding

fulltext chunk 只对已按需处理的论文生效。

### 3.3 先可运行，再可扩展

优先单机稳定实现：

- FastAPI
- PostgreSQL
- pgvector
- Redis
- Next.js
- systemd
- nginx

不要在阶段一引入不必要的复杂基础设施。

---

## 4. 推荐执行顺序

1. 建目录和工程骨架
2. 建 schema 和 migration
3. 实现 USENIX / NDSS metadata crawler
4. 实现 ingest pipeline
5. 实现 metadata embedding
6. 实现 on-demand fetch / parse
7. 实现 search API
8. 实现 subscription API
9. 实现 minimal frontend
10. 实现 deployment templates

---

## 5. 每一步的最低要求

每完成一个子任务，AI agent 都应该：

- 能本地运行
- 有最小验证结果
- 不破坏 metadata-first / fulltext-on-demand 原则
- 同步更新对应文档

---

## 6. 建议交付格式

让 AI agent 每次只完成一个明确批次，并输出：

1. 改了哪些文件
2. 实现了什么
3. 怎么验证
4. 目前还没做什么
5. 下一批建议做什么

---

## 7. 推荐拆批方式

### 批次 1
- 初始化 backend / frontend / workers / deploy
- 初始化配置与 health API

### 批次 2
- 建 schema / migration
- 建基础 model / repository

### 批次 3
- 做 USENIX / NDSS crawler
- 做 metadata ingest

### 批次 4
- 做 metadata search API
- 做 metadata embeddings

### 批次 5
- 做 on-demand fulltext fetch / parse
- 做 fulltext status API

### 批次 6
- 做 subscription API
- 做 match / notification 记录

### 批次 7
- 做 minimal frontend
- 做部署模板

---

## 8. 一句话结论

**后续交给 AI agent 开发时，最重要的不是“写得多快”，而是始终守住范围边界：只做阶段一、默认不抓全文、每一步都能运行验证。**
