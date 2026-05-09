# Stage 1 订阅与通知说明

## 本批目标

完成最小可用的 subscription / match / notification 链路：

- 创建订阅
- 列出订阅
- 删除订阅
- 跑匹配
- 保存命中记录
- 保存通知记录

## 当前实现

- `app/backend/subscriptions.py`
- `app/scripts/subscription_create.py`
- `app/scripts/subscription_list.py`
- `app/scripts/subscription_delete.py`
- `app/scripts/subscription_match.py`
- `app/scripts/subscription_matches.py`
- `app/scripts/notification_list.py`

## 当前存储方式

Stage 1 当前先把订阅状态保存在：

- `data/generated/subscriptions.json`
- `data/generated/subscription_matches.json`
- `data/generated/notifications.json`

这是 Stage 1 的轻量实现，后续可迁移到 PostgreSQL。

## 去重原则

- 同一订阅 + 同一论文 URL 只生成一次通知记录
