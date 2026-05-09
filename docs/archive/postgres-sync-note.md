# PostgreSQL 同步说明

当前 Stage 1 已验证以下状态数据可以写入 PostgreSQL：

- subscriptions
- subscription_matches
- notifications

说明：

- subscriptions 已进入数据库优先读写
- matches / notifications 已验证可同步入库
- Stage 1 当前仍保留 JSON 作为备份层，便于调试与回滚
