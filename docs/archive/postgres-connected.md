# PostgreSQL 接入记录

## 当前状态

PaperRadar 现在已经真正接入本机 PostgreSQL，而不再只是停留在 schema 设计阶段。

## 已完成

- PostgreSQL 已安装
- 服务已运行在 `127.0.0.1:5432`
- 已创建数据库用户：`paperradar`
- 已创建数据库：`paperradar`
- 已应用 `app/backend/schema.sql`

## 当前已存在表

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

## 备注

当前项目的订阅 / 匹配 / 通知轻量状态仍暂存在 JSON 文件中；后续可继续迁移到 PostgreSQL。
