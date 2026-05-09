# Stage 1 metadata 检索说明

## 本批目标

先完成不依赖全文的 metadata 检索。

## 当前实现

- `app/backend/embedding.py`
  - embedding provider 抽象
  - 当前默认支持 Google embedding API
- `app/backend/search.py`
  - metadata 加载
  - 关键词检索
  - embedding 相似度融合
- `app/backend/main.py`
  - 新增 `POST /api/search`
- `app/scripts/build_metadata_embeddings.py`
  - 为 normalized metadata 生成 embedding

## 当前策略

- 默认检索 metadata
- 如果 metadata 已带 embedding，则做语义融合
- 如果当前环境没有可用 Google API key，则自动退回关键词检索

## 边界

- 不触发 PDF 下载
- 不做全文 chunk 检索
- 不做报告生成
