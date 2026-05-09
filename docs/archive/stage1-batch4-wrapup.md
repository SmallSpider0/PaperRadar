# Stage 1 / 批次 4 收尾说明

## 本次收尾目标

让 Stage 1 的 metadata semantic search 真正可跑，而不是只停留在接口骨架。

## 本次补强

- 抽出统一的 `.env.local` 加载模块 `app/backend/env.py`
- 让 embedding 相关脚本和运行时都能稳定读取本地 Google API key
- 修正 metadata search 的本地数据路径
- 让 embedding 结果以更可读的 JSON 形式写回 normalized 文件

## 结果

完成后，`build_metadata_embeddings.py` 与 `search_metadata.py` 都应能直接基于本机 `.env.local` 运行，不需要手工额外 export key。
