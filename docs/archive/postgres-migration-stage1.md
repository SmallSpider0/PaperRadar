# Stage 1 状态迁移到 PostgreSQL

## 目标

将当前轻量 JSON 状态迁移到 PostgreSQL：

- subscriptions
- subscription_matches
- notifications

## 当前实现

- `app/backend/pg_json_store.py`
- `app/scripts/migrate_state_to_postgres.py`

## 迁移说明

当前迁移脚本会读取：

- `data/generated/subscriptions.json`
- `data/generated/subscription_matches.json`
- `data/generated/notifications.json`

并写入 PostgreSQL 中对应表。

## 当前边界

这是 Stage 1 的迁移版实现，目的是先完成落库。
后续还需要继续把运行时读写逻辑直接改为数据库优先。
