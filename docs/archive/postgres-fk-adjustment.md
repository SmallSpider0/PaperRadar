# Stage 1 外键调整说明

## 背景

当前 Stage 1 的 subscription_matches / notifications 使用的是 metadata 层的 `paper_url` 作为论文标识写入数据库。

而初版 schema 中：

- `subscription_matches.paper_id`
- `notifications.paper_id`

都外键指向 `papers.id`

这会导致 Stage 1 运行时把 metadata URL 写入时发生约束冲突。

## 当前处理

为保持 Stage 1 快速可用，已移除以下外键：

- `subscription_matches_paper_id_fkey`
- `notifications_paper_id_fkey`

## 原因

Stage 1 还没有把 metadata 层统一映射为真正的 `papers.id` 主键体系，因此先保留 `paper_id` 为自由文本字段更符合当前实现。

## 后续建议

等后续真正完成 metadata 入库主键统一后，再恢复更严格的外键约束。
