# Stage 1 / IEEE S&P 摘要补全

## 目标

在 `IEEE S&P 2025` accepted papers 页面本身不提供 abstract 的情况下，为 Stage 1 的 `IEEE_SP` 元数据补回摘要。

## 方案

采用 **OpenAlex 元数据增强**：

- 按 `title + year` 检索 OpenAlex works
- 优先匹配 `IEEE S&P / Security and Privacy` 相关 venue
- 从 `abstract_inverted_index` 重建摘要文本
- 若本地没有 `authors_text`，则顺手回填作者列表
- 将 `content_policy` 显式设为 `metadata_only`

## 本批新增

- `app/workers/enrich_openalex.py`
  - OpenAlex 查询
  - 标题归一化匹配
  - abstract 重建
- `app/scripts/enrich_ieee_sp_abstracts.py`
  - 对 `ieee_sp_2025_metadata.json` 分批执行 enrich
  - 支持 `--start` / `--limit`
  - 记录进度到 `data/generated/ieee_sp_2025_enrich_state.json`

## 用法

### 单批跑 20 条

```bash
cd /opt/paperradar/app
PYTHONPATH=. python3 scripts/enrich_ieee_sp_abstracts.py --limit 20
```

### 从指定位置继续跑

```bash
cd /opt/paperradar/app
PYTHONPATH=. python3 scripts/enrich_ieee_sp_abstracts.py --start 40 --limit 20
```

## 抽样验证

已抽样验证以下标题可从 OpenAlex 命中并重建摘要：

- `PAC-Private Algorithms`
- `Verifiable Secret Sharing Simplified`
- `CMASan: Custom Memory Allocator-aware Address Sanitizer`

## 说明

- 这一步先解决“SP 摘要怎么补”的能力问题
- 全量 255 篇可以继续分批跑完，不需要一次性长时间阻塞
- 后续若要提高稳定性，可再加入本地缓存 / 批量并发控制 / Crossref 兜底
