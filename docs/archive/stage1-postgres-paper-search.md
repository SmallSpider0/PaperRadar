# Stage 1 / PostgreSQL 论文主链路接管

## 目标

把 PaperRadar 的论文主链路从“JSON 文件优先”切到：

- 论文元数据入 PostgreSQL
- metadata embedding 入 PostgreSQL
- 搜索优先读取 PostgreSQL
- 仅在数据库不可用或无数据时回退 JSON 文件

## 本批实现

### 新增脚本

- `app/scripts/ingest_papers_to_postgres.py`

作用：

- 读取 `data/generated/*_normalized.json`
- upsert `venues`
- upsert `venue_editions`
- upsert `papers`
- 若存在 embedding，则 upsert `paper_metadata_embeddings`

### 搜索改造

- 修改 `app/backend/search.py`

当前逻辑：

1. 优先从 PostgreSQL 读取 `papers + venue_editions + venues + paper_metadata_embeddings`
2. 若读库失败或为空，则回退读取 `data/generated/*_normalized.json`
3. 搜索评分仍保留：
   - keyword score
   - metadata embedding cosine similarity

## 本次实测

执行：

```bash
cd /opt/paperradar/app
PYTHONPATH=. python3 scripts/check_db.py
PYTHONPATH=. python3 scripts/apply_schema.py
PYTHONPATH=. python3 scripts/ingest_papers_to_postgres.py
```

结果：

- `ingested papers: 921`
- `postgres_records = 921`

搜索抽测：

```bash
PYTHONPATH=. python3 - <<'PY'
from backend.search import load_records_from_postgres, search_metadata
rows = load_records_from_postgres()
print('postgres_records=', len(rows))
res = search_metadata('browser security', limit=3)
print('search_count=', len(res))
for item in res:
    print(item['score'], item['record']['venue_code'], item['record']['title'])
PY
```

结果：可正常返回 PostgreSQL 中的论文搜索结果。

## 当前状态

这次之后，论文主搜索链路已经不再只是“读 JSON 文件的假入库”，而是：

- **PostgreSQL 优先**
- JSON 只作为 fallback

## 后续建议

1. embedding 跑完后再次执行 `ingest_papers_to_postgres.py`，把最新 embedding 同步入库
2. API / 前端重启后再次验证前端搜索
3. 后续继续把全文状态、报告状态等更多链路都统一收口到 PostgreSQL
