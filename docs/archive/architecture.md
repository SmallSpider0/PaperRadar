# PaperRadar 架构草图

## 单机部署组件

- Nginx：统一入口与静态文件服务
- Next.js：前端页面
- FastAPI：后端 API
- Worker：抓取、解析、向量化、报告生成
- PostgreSQL + pgvector：元数据、按需解析 chunk、向量检索
- Redis：缓存、任务队列
- GROBID：按需 PDF 结构化解析
- 本地存储目录：保存按需抓取的 PDF、HTML、PPT、图片

## 核心数据流

1. 抓取会议论文列表
2. 入库元数据与来源链接
3. 在需要时按需下载允许获取的 PDF
4. 按需调用 GROBID 解析结构化全文
5. 切 chunk 并生成 embedding
6. 提供混合检索 API
7. 在需要时生成 HTML / PPT 报告
8. 匹配订阅并推送通知

## 合规边界

- 默认只入库元数据与来源链接，不默认抓取全文 PDF
- USENIX / NDSS：作为优先的按需全文来源
- IEEE S&P / ACM CCS：首期 metadata-only，不做反爬或批量全文下载
- 全文处理必须依赖 `content_policy` 控制
