# 阶段一：核心闭环

## 目标

先做出最小可用版本，让 PaperRadar 具备：

- 自动抓论文元数据
- 合规入库
- 按需全文抓取
- 按需解析
- 关键词 + 语义检索
- 基础订阅

## 功能范围

### 数据源
- USENIX Security：默认元数据抓取 + 来源链接
- NDSS：默认元数据抓取 + 来源链接
- IEEE S&P：元数据 only
- ACM CCS：元数据 only

### 数据能力
- 论文元数据入库
- 按需 PDF 原件保存
- 按需 chunk 切分
- 按需 embedding 入库
- hash 与来源追踪

### 检索能力
- 标题 / 摘要 / chunk 关键词检索
- 研究方向描述的语义检索
- 按会议 / 年份过滤

### 订阅能力
- 研究方向订阅
- 会议订阅
- 命中后生成通知记录

### 页面范围
- 搜索页
- 论文列表页
- 论文详情页
- 订阅页

## 不做

- HTML 报告
- PPT
- Nano Banana 配图
- 高级图谱可视化
- 多租户权限系统

## 核心交付物

- crawler
- metadata ingest pipeline
- on-demand fulltext pipeline
- database schema
- vector search
- search api
- subscription api
- minimal frontend
- deployment templates
