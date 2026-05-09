# Stage 1 数据库落地说明

## 当前目标

本批先完成数据库连接配置、Stage 1 schema、初始化脚本与 migration 落地骨架。

## 当前交付

- `app/backend/db.py`：数据库配置
- `app/backend/schema.sql`：Stage 1 基础表
- `app/backend/models.py`：Stage 1 表清单占位
- `app/scripts/init_db.py`：初始化说明脚本
- `app/scripts/apply_schema.py`：调用 `psql` 应用 schema

## Stage 1 基础表

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

## 说明

由于当前环境还未安装 SQLAlchemy / Alembic / psycopg 等依赖，本批先把 schema 与应用脚本落地，后续装依赖后再切到 ORM / migration 完整链路。

这仍然属于 Stage 1 的数据库批次，不涉及 crawler、全文抓取、搜索或订阅逻辑实现。
