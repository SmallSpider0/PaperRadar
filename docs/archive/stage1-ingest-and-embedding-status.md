# Stage 1 / 已接入会议的入库与嵌入状态

## 当前真实状态

### 搜索链路

当前 `PaperRadar` 的搜索 API (`/api/search`) **直接读取 `data/generated/*_normalized.json`**，不是从 PostgreSQL 读取论文主索引。

因此：

- 前端“搜不到任何东西”并不一定说明数据库为空
- 更可能是：
  - 前端未部署到最新版本
  - 前端命中旧缓存
  - 前端 API base 配置未对上当前后端

### 本地 API 验证

已验证：

```bash
curl -s http://127.0.0.1:8100/health
curl -s -X POST http://127.0.0.1:8100/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"browser security","limit":3}'
```

本地 API 可正常返回搜索结果。

## 当前已接入会议

- USENIX Security 2025
- NDSS 2025
- IEEE S&P 2025

## 嵌入状态

开始重新执行：

```bash
cd /opt/paperradar/app
PYTHONPATH=. python3 scripts/build_metadata_embeddings.py
```

目的：

- 为所有 `*_normalized.json` 补齐 metadata embedding
- 让搜索从纯关键词结果升级为关键词 + embedding 混合排序

## 数据库状态说明

当前 PostgreSQL 已用于：

- subscriptions
- matches
- notifications

但论文主搜索索引当前仍是 **JSON 文件优先**，不是 PostgreSQL 优先。

## 下一步建议

1. 等 embedding 跑完
2. 重启 API / 前端服务（如有需要）
3. 强刷前端缓存后验证搜索
4. 后续再把 paper ingest 真正落进 PostgreSQL 主链路
