# 阶段一任务清单（供 AI Agent 直接执行）

## 目标

阶段一只完成核心闭环：

- 元数据抓取
- 元数据入库
- 按需全文抓取
- 按需解析
- 关键词 / 语义检索
- 基础订阅
- 最小前端
- 本机部署模板

---

## A. 项目骨架

### A1. 创建目录结构

需要建立：

```text
app/
  backend/
  frontend/
  workers/
  scripts/
  deploy/
storage/
  papers/
  reports/
  figures/
data/
  raw/
  parsed/
  generated/
```

### A2. 初始化后端工程

交付：

- Python 项目结构
- FastAPI app 入口
- 配置文件加载
- 基础 health API

### A3. 初始化前端工程

交付：

- Next.js 项目结构
- 首页 / 搜索页占位
- API 调用封装

---

## B. 数据库与模型

### B1. 建 PostgreSQL schema

优先表：

- `venues`
- `venue_editions`
- `papers`
- `paper_external_ids`
- `paper_files`
- `paper_parse_jobs`
- `paper_metadata_embeddings`
- `subscriptions`
- `subscription_matches`
- `notifications`

### B2. 建 ORM / 数据访问层

交付：

- 数据模型定义
- migration 文件
- 初始化脚本

---

## C. 抓取与入库

### C1. 实现 venue crawler

优先顺序：

1. USENIX Security
2. NDSS

交付：

- 会议列表抓取
- 论文详情抓取
- 摘要 / 作者 / 链接解析
- 原始响应落盘到 `data/raw/`

### C2. 实现 metadata ingest pipeline

交付：

- 去重逻辑
- 元数据标准化
- 入库逻辑
- 外部 ID 记录

### C3. 增补元数据增强源

至少接一个：

- OpenAlex
- DBLP
- Crossref

---

## D. 按需全文链路

### D1. 实现 fetch-fulltext

交付：

- 根据 `content_policy` 检查是否允许抓取 PDF
- 下载 PDF 到本地存储
- 计算 hash
- 写入 `paper_files`
- 更新 `fulltext_status`

### D2. 实现 parse-fulltext

交付：

- 基础 PDF 文本抽取
- 或预留 GROBID 接口
- 解析结果写入 `data/parsed/`
- 生成 chunk

### D3. 实现 embedding pipeline

交付：

- 标题 + 摘要 metadata embedding
- 已解析 chunk 的 fulltext embedding
- 内容 hash 去重

---

## E. 搜索与订阅

### E1. 搜索 API

交付：

- metadata 检索
- 可选 fulltext 检索（仅针对已解析论文）
- 过滤器支持

### E2. 订阅 API

交付：

- 创建订阅
- 编辑订阅
- 删除订阅
- 订阅命中记录

### E3. 匹配逻辑

交付：

- 新论文入库后自动匹配订阅
- 记录 match score 和 reason
- 去重通知

---

## F. 前端

### F1. 搜索页

包含：

- 搜索框
- 会议 / 年份过滤
- 结果列表

### F2. 论文详情页

包含：

- 元数据
- 来源链接
- 全文状态
- 手动触发全文抓取 / 解析按钮（如后端已完成）

### F3. 订阅页

包含：

- 订阅列表
- 新建 / 编辑 / 删除订阅

---

## G. 部署

### G1. 本机部署模板

交付：

- `.env.example`
- `systemd` service 模板
- `nginx` 反向代理模板
- 初始化脚本

### G2. 运维接口

交付：

- `/health`
- `/api/tasks`
- 基础任务状态查询

---

## H. 阶段一完成标准

必须全部满足：

1. 能抓取 USENIX / NDSS 论文元数据
2. 能稳定入库并去重
3. 能按需抓取 PDF
4. 能按需解析并建立检索索引
5. 能完成 metadata 搜索
6. 能创建并命中订阅
7. 能在网页中查看结果
8. 能以 systemd + nginx 方式部署

---

## I. AI Agent 执行建议

如果把阶段一交给 AI agent，建议按以下顺序分批执行，不要一口气全做：

1. 先建工程骨架
2. 再建数据库与 migration
3. 再做 crawler 和 ingest
4. 再做 on-demand fulltext pipeline
5. 再做 search / subscription API
6. 最后补前端与部署模板

每完成一个批次，都应：

- 本地运行
- 做最小验证
- 更新文档
- 再进入下一批次
