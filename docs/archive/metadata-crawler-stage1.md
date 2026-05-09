# Stage 1 元数据抓取说明

## 本批目标

打通 metadata ingest 的第一步：

- USENIX metadata crawler
- NDSS metadata crawler
- 原始数据落盘
- 标准化脚本

## 当前实现

### crawler

- `app/workers/crawlers/usenix_security.py`
- `app/workers/crawlers/ndss.py`

### 通用抓取

- `app/workers/fetch_html.py`
- `app/workers/schemas.py`

### 脚本

- `app/scripts/crawl_metadata.py`
- `app/scripts/normalize_metadata.py`

## 当前结果

本地运行 `crawl_metadata.py` 已获取到样例数据：

- USENIX records: 455
- NDSS records: 211

说明当前公开页面抓取链路是可用的。

## 当前边界

本批只完成原始抓取与标准化准备：

- 不默认下载 PDF
- 不做全文解析
- 不做数据库入库
- 不做 embedding

数据库入库会在后续 ingest 批次继续补上。
