# PaperRadar API 设计（首版）

## 1. 设计原则

PaperRadar API 默认围绕两条链路展开：

1. **元数据链路**：抓取、入库、检索、订阅
2. **按需全文链路**：抓取 PDF、解析、生成报告

所以 API 也应明确分为：

- metadata APIs
- on-demand fulltext APIs
- subscription APIs
- report APIs

---

## 2. Metadata APIs

### 2.1 触发抓取某个会议年份

`POST /api/tasks/ingest/venue/{venue}/{year}`

作用：

- 抓取某会议某年份的论文列表
- 入库元数据、摘要、来源链接
- 不默认下载 PDF

示例：

```http
POST /api/tasks/ingest/venue/USENIX_SECURITY/2025
```

返回建议：

```json
{
  "job": "ingest_venue",
  "venue": "USENIX_SECURITY",
  "year": 2025,
  "status": "queued"
}
```

### 2.2 触发单篇论文元数据刷新

`POST /api/tasks/ingest/paper/{paper_id}`

作用：

- 刷新单篇论文元数据
- 可重新同步摘要、作者、外部 id
- 不默认抓 PDF

### 2.3 搜索论文

`POST /api/search`

请求体建议：

```json
{
  "query": "LLM guided fuzzing for binaries",
  "filters": {
    "venues": ["USENIX_SECURITY", "NDSS"],
    "year_from": 2023,
    "year_to": 2026
  },
  "use_fulltext": true,
  "limit": 20
}
```

说明：

- 默认先搜 metadata
- 当 `use_fulltext=true` 时，可额外利用已按需解析过的 chunk
- 不会因为检索请求而自动下载 PDF

### 2.4 查询论文详情

`GET /api/papers/{paper_id}`

返回建议包含：

- 基础元数据
- `content_policy`
- `fulltext_status`
- `report_status`
- 已存在文件列表
- 已存在报告列表

---

## 3. On-demand Fulltext APIs

### 3.1 按需抓取 PDF

`POST /api/papers/{paper_id}/fetch-fulltext`

作用：

- 为单篇论文触发 PDF 抓取
- 先检查 `content_policy`
- 成功后更新 `fulltext_status`

请求体建议：

```json
{
  "reason": "report_request"
}
```

返回建议：

```json
{
  "paper_id": "paper_123",
  "job": "fetch_pdf",
  "status": "queued"
}
```

### 3.2 触发全文解析

`POST /api/papers/{paper_id}/parse-fulltext`

作用：

- 对已下载的 PDF 做解析
- 生成 chunk
- 按需生成 embedding

说明：

- 如果 PDF 尚未下载，可返回错误，或串联触发抓取流程
- 建议后端支持自动串联，但状态必须清晰可见

### 3.3 查询全文处理状态

`GET /api/papers/{paper_id}/fulltext-status`

返回建议：

```json
{
  "paper_id": "paper_123",
  "content_policy": "on_demand_allowed",
  "fulltext_status": "parsed",
  "latest_jobs": [
    {"job_type": "fetch_pdf", "status": "done"},
    {"job_type": "parse_pdf", "status": "done"},
    {"job_type": "embed_chunks", "status": "done"}
  ]
}
```

---

## 4. Report APIs

### 4.1 生成单篇论文报告

`POST /api/papers/{paper_id}/generate-report`

作用：

- 若全文未就绪，自动触发按需全文链路
- 最终生成 HTML 报告
- 后续阶段再补 PPT 生成

请求体建议：

```json
{
  "report_type": "paper_summary"
}
```

### 4.2 查询报告

`GET /api/papers/{paper_id}/reports`

作用：

- 查询该论文已有的报告产物

### 4.3 获取单个报告详情

`GET /api/reports/{report_id}`

返回建议包含：

- 报告状态
- HTML 地址
- PPT 地址（如存在）
- 引用的 chunk 信息

---

## 5. Subscription APIs

### 5.1 获取订阅列表

`GET /api/subscriptions`

### 5.2 创建订阅

`POST /api/subscriptions`

请求体建议：

```json
{
  "type": "topic",
  "name": "LLM fuzzing",
  "query_text": "LLM guided fuzzing for binaries and protocol analysis",
  "filters": {
    "venues": ["USENIX_SECURITY", "NDSS", "IEEE_SP", "ACM_CCS"]
  },
  "threshold": 0.75
}
```

### 5.3 修改订阅

`PATCH /api/subscriptions/{id}`

### 5.4 删除订阅

`DELETE /api/subscriptions/{id}`

### 5.5 查询订阅命中记录

`GET /api/subscriptions/{id}/matches`

---

## 6. Notification APIs

### 6.1 查询通知记录

`GET /api/notifications`

### 6.2 手动重发通知

`POST /api/notifications/{id}/retry`

---

## 7. 管理与运维 API

### 7.1 查询任务列表

`GET /api/tasks`

### 7.2 查询单个任务状态

`GET /api/tasks/{task_id}`

### 7.3 重建元数据 embedding

`POST /api/tasks/rebuild-metadata-embeddings`

### 7.4 重建单篇论文全文 embedding

`POST /api/tasks/rebuild-fulltext-embeddings/{paper_id}`

说明：

- 这个接口只对已完成按需全文解析的论文有效

---

## 8. 阶段一最小 API 集

如果先只做最小闭环，建议优先实现：

- `POST /api/tasks/ingest/venue/{venue}/{year}`
- `POST /api/search`
- `GET /api/papers/{paper_id}`
- `POST /api/papers/{paper_id}/fetch-fulltext`
- `POST /api/papers/{paper_id}/parse-fulltext`
- `GET /api/papers/{paper_id}/fulltext-status`
- `GET /api/subscriptions`
- `POST /api/subscriptions`
- `PATCH /api/subscriptions/{id}`
- `DELETE /api/subscriptions/{id}`

报告生成接口可以保留设计，但实现可以放到阶段二。

---

## 9. 一句话结论

**API 层要明确区分“普通元数据检索”和“按需全文处理”，避免任何一个搜索或抓取动作偷偷变成默认下载 PDF 全文。**
