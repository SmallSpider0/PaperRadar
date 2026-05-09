# Stage 1 数据库优先运行时说明

## 当前目标

把订阅链路从“已迁移到 PostgreSQL”进一步推进到“运行时数据库优先”。

## 当前已完成

- subscriptions：数据库优先读写
- subscription_matches：可同步写入 PostgreSQL（已验证）
- notifications：可同步写入 PostgreSQL（已验证）

## 当前策略

为了保持 Stage 1 稳定，当前仍保留 JSON 文件作为轻量备份层：

- 先写 JSON
- 再同步写 PostgreSQL
- 读取优先 PostgreSQL，失败时再 fallback 到 JSON

## 意义

这样做以后，即使后面 AI agent 继续推进，也不会再误以为订阅链路仍是纯 JSON 原型。
