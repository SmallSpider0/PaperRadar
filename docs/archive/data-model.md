# PaperRadar 数据模型设计

## 1. 设计原则

PaperRadar 默认采用 **metadata-first / fulltext-on-demand** 模式：

- 默认只入库论文元数据、摘要、来源链接
- 不默认抓取 PDF 全文
- 只有在需要生成报告、人工触发解析、或其他明确要求全文处理的场景下，才按需抓取 PDF 并进入全文处理链路

因此，数据模型需要天然区分：

1. **元数据层**：默认存在
2. **全文层**：按需存在
3. **产物层**：按需存在

---

## 2. 核心实体

### 2.1 `venues`

会议主表。

字段建议：

- `id`
- `code`：如 `USENIX_SECURITY`
- `name`
- `publisher_type`：`usenix | ndss | ieee | acm | other`
- `homepage`
- `created_at`
- `updated_at`

### 2.2 `venue_editions`

会议年份或届次信息。

字段建议：

- `id`
- `venue_id`
- `year`
- `label`：如 `USENIX Security 2025`
- `program_url`
- `metadata_source`
- `created_at`
- `updated_at`

### 2.3 `papers`

论文主表，首期最核心。

字段建议：

- `id`
- `venue_edition_id`
- `title`
- `abstract`
- `authors_text`
- `doi`
- `paper_url`
- `source_pdf_url`
- `source`
- `content_policy`
- `fulltext_status`
- `report_status`
- `published_at`
- `raw_meta_json`
- `created_at`
- `updated_at`

字段说明：

- `content_policy`
  - `metadata_only`
  - `on_demand_allowed`
  - `manual_review`
- `fulltext_status`
  - `not_requested`
  - `queued`
  - `downloaded`
  - `parsed`
  - `failed`
- `report_status`
  - `not_requested`
  - `queued`
  - `generated`
  - `failed`

### 2.4 `paper_external_ids`

记录论文在不同外部源中的标识，便于去重和补全。

字段建议：

- `id`
- `paper_id`
- `source_name`：`dblp | crossref | openalex | semantic_scholar | venue_site`
- `external_id`
- `external_url`
- `created_at`

### 2.5 `paper_authors`

论文作者拆分表。

字段建议：

- `id`
- `paper_id`
- `author_order`
- `name`
- `orcid`
- `affiliation`
- `raw_json`

---

## 3. 全文层（按需）

### 3.1 `paper_files`

保存按需抓取下来的文件和生成产物。

字段建议：

- `id`
- `paper_id`
- `file_type`
- `storage_path`
- `source_url`
- `sha256`
- `size_bytes`
- `mime_type`
- `created_at`

`file_type` 建议值：

- `source_pdf`
- `parsed_json`
- `html_report`
- `ppt_report`
- `figure`

### 3.2 `paper_parse_jobs`

记录按需全文抓取和解析任务。

字段建议：

- `id`
- `paper_id`
- `job_type`
- `trigger_source`
- `status`
- `error_message`
- `started_at`
- `finished_at`
- `created_at`

`job_type` 建议值：

- `fetch_pdf`
- `parse_pdf`
- `build_chunks`
- `embed_chunks`
- `generate_report`

`trigger_source` 建议值：

- `manual`
- `report_request`
- `system`

### 3.3 `paper_chunks`

按需解析后生成的全文块。

字段建议：

- `id`
- `paper_id`
- `section_title`
- `chunk_index`
- `content`
- `content_tsv`
- `token_count`
- `page_from`
- `page_to`
- `content_hash`
- `created_at`

说明：

- 未触发全文处理的论文不会有这张表的数据
- 这张表只对按需抓取并解析成功的论文存在

### 3.4 `paper_embeddings`

按需生成的向量。

字段建议：

- `id`
- `paper_id`
- `chunk_id`
- `model_name`
- `embedding`
- `content_hash`
- `created_at`

说明：

- 只对被按需处理的 chunk 建立向量
- 如果只是 metadata 检索，可只建立 paper-level 向量

### 3.5 `paper_metadata_embeddings`

元数据层 embedding，用于默认检索。

字段建议：

- `id`
- `paper_id`
- `model_name`
- `embedding`
- `content_hash`
- `created_at`

说明：

- 基于标题 + 摘要生成
- 所有允许进入检索的论文默认都可以有这层 embedding
- 首期建议优先做这层，因为它不依赖全文抓取

---

## 4. 订阅与通知层

### 4.1 `subscriptions`

字段建议：

- `id`
- `user_id`
- `type`
- `name`
- `query_text`
- `filters_json`
- `threshold`
- `enabled`
- `created_at`
- `updated_at`

`type` 建议值：

- `topic`
- `venue`
- `query`

### 4.2 `subscription_matches`

记录某篇论文为何命中某个订阅。

字段建议：

- `id`
- `subscription_id`
- `paper_id`
- `match_score`
- `match_reason`
- `evidence_json`
- `created_at`

### 4.3 `notifications`

记录通知发送。

字段建议：

- `id`
- `subscription_id`
- `paper_id`
- `channel`
- `status`
- `payload_json`
- `sent_at`
- `created_at`

---

## 5. 报告层（按需）

### 5.1 `reports`

字段建议：

- `id`
- `paper_id`
- `report_type`
- `status`
- `summary_json`
- `html_file_id`
- `ppt_file_id`
- `created_at`
- `updated_at`

`report_type` 建议值：

- `paper_summary`
- `topic_summary`

### 5.2 `report_figures`

字段建议：

- `id`
- `report_id`
- `paper_file_id`
- `figure_type`
- `prompt_text`
- `created_at`

说明：

- 阶段一可以先不建表，文档先保留设计
- 阶段二再真正落库

---

## 6. 状态流转建议

### 6.1 默认论文状态

新论文入库后：

- `content_policy = on_demand_allowed` 或 `metadata_only`
- `fulltext_status = not_requested`
- `report_status = not_requested`

### 6.2 当用户请求生成报告时

触发顺序建议：

1. 检查 `content_policy`
2. 若允许全文抓取，则创建 `fetch_pdf` job
3. 下载成功后创建 `parse_pdf` job
4. 解析成功后创建 `build_chunks` job
5. chunk 成功后创建 `embed_chunks` job
6. 最后创建 `generate_report` job

### 6.3 当只是普通检索时

默认只依赖：

- `papers`
- `paper_metadata_embeddings`

如果论文曾被按需解析，再额外使用：

- `paper_chunks`
- `paper_embeddings`

---

## 7. 首期最小表集

如果阶段一想收缩到最小实现，建议先只建这些表：

- `venues`
- `venue_editions`
- `papers`
- `paper_external_ids`
- `paper_files`
- `paper_parse_jobs`
- `paper_metadata_embeddings`
- `subscriptions`
- `subscription_matches`
- `notifications`

等“按需全文”链路稳定后，再补：

- `paper_chunks`
- `paper_embeddings`
- `reports`
- `report_figures`

---

## 8. 一句话结论

**PaperRadar 的数据模型必须把“默认 metadata”与“按需 fulltext”作为一等概念分开设计，否则后面很容易又滑回默认抓全文的老路。**
