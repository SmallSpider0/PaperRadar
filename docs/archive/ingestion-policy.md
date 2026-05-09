# PaperRadar 数据获取与全文策略

## 1. 总原则

PaperRadar 默认采用：

- **metadata-first**
- **fulltext-on-demand**

即：

- 默认抓元数据、摘要、来源链接
- 默认不抓全文 PDF
- 只有在明确需要时才抓全文 PDF

明确需要的典型场景：

- 生成单篇论文报告
- 生成人工指定的主题报告
- 用户主动点击“抓取全文 / 解析全文”
- 后台明确触发某篇论文的深度处理任务

---

## 2. 来源策略

### 2.1 USENIX Security

默认策略：

- 抓元数据
- 抓摘要 / 详情页信息
- 保存来源页与 PDF 链接
- 不默认下载 PDF

全文策略：

- 当进入报告或全文解析流程时，可按需抓取 PDF

### 2.2 NDSS

默认策略：

- 抓元数据
- 抓详情页信息
- 保存来源页与 PDF 链接
- 不默认下载 PDF

全文策略：

- 当进入报告或全文解析流程时，可按需抓取 PDF

### 2.3 IEEE S&P

默认策略：

- 只抓元数据
- 优先使用开放元数据源补全
- 保存官方链接

全文策略：

- 首期默认不自动抓取全文
- 如需支持，必须单独审查来源与许可

### 2.4 ACM CCS

默认策略：

- 只抓元数据
- 优先使用开放元数据源补全
- 保存官方链接

全文策略：

- 首期默认不自动抓取全文
- 如需支持，必须单独审查来源与许可

---

## 3. content_policy 规则

每篇论文必须带 `content_policy`：

- `metadata_only`
  - 只允许元数据入库
  - 不允许抓取全文
- `on_demand_allowed`
  - 平时不抓全文
  - 在需要时允许抓取全文
- `manual_review`
  - 先不抓全文
  - 需要人工确认后才能继续

默认建议：

- USENIX / NDSS：`on_demand_allowed`
- IEEE S&P / ACM CCS：`metadata_only` 或 `manual_review`

---

## 4. 触发全文抓取的规则

只有以下接口或动作可以触发全文抓取：

- `POST /api/papers/{paper_id}/fetch-fulltext`
- `POST /api/papers/{paper_id}/generate-report`
- 管理员显式触发的后台任务

以下动作**不能**触发全文抓取：

- 普通搜索
- 普通元数据抓取
- 订阅命中
- 前端列表加载

---

## 5. Agent 实施要求

后续若交由 AI agent 开发，必须遵守：

1. 不要把 metadata ingest 和 fulltext ingest 混成一个默认流程
2. 不要在 crawler 阶段自动下载所有 PDF
3. 不要因为用户搜索某篇论文就自动抓全文
4. 所有全文抓取都必须有明确触发源
5. 所有全文抓取都必须记录 job、时间、来源 URL 和 hash

---

## 6. 一句话结论

**PaperRadar 的全文策略不是“先抓下来再说”，而是“先知道有什么，再只在真正需要时抓全文”。**
