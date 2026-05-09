# Stage 1 / IEEE S&P metadata-only 接入记录

## 目标

把 `IEEE S&P 2025` 补进 Stage 1 的 metadata crawler 范围，遵循 metadata-only 边界，不默认抓取全文。

## 本批实现

- 新增 crawler：`app/workers/crawlers/ieee_sp.py`
- 接入 `app/scripts/crawl_metadata.py`
- 输出：
  - `data/raw/ieee_sp_2025_metadata.json`
  - `data/generated/ieee_sp_2025_normalized.json`

## 当前抓取策略

- 来源页面：`https://www.ieee-security.org/TC/SP2025/accepted-papers.html`
- 当前使用 accepted papers 页面中的折叠锚点作为每篇论文的来源定位 URL
- 当前为 metadata-only：
  - title：有
  - paper_url：有（accepted-papers 页面锚点）
  - abstract：暂无
  - authors_text：当前页面结构未稳定提取，先留空
  - source_pdf_url：无
  - content_policy：normalize 后默认为 `on_demand_allowed`，后续建议按 IEEE 策略改成 `metadata_only`

## 验证

```bash
cd /opt/paperradar/app
PYTHONPATH=. python3 scripts/crawl_metadata.py
PYTHONPATH=. python3 scripts/normalize_metadata.py
```

本次实测：`IEEE S&P records: 255`

## 说明

这一步先完成“会议覆盖补齐”的最小抓取接入，后续可继续补：

- authors 精确提取
- abstract 补全源
- `content_policy` 改为 `metadata_only`
- PostgreSQL ingest / 前端过滤联动
