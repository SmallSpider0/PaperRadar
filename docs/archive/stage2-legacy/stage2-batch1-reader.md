# Stage 2 / Batch 1 完成记录：HTML 阅读页基础版

## 本批目标

把已解析的全文结果接成可浏览的 HTML 阅读页，并从现有前端搜索入口进入。

## 本批实现

### 后端

- 新增 `app/backend/reader.py`
- 提供 `get_reader_payload(paper_id)`：
  - 读取 `data/parsed/{paper_id}.json`
  - 结合 metadata 记录返回论文基础信息
  - 对 `parsed_text_preview` 做基础清洗
  - 输出 paragraph 级预览和 chunk 列表
- 新增 API：`GET /api/reader/{paper_id}`

### 前端

- 新增页面：`app/frontend/pages/reader/[paperId].js`
- 阅读页展示：
  - 标题 / venue / year / 状态 / chunk_count
  - 原始论文页 / 全文来源链接
  - abstract
  - 阅读预览（paragraphs）
  - chunk preview
- 更新 `pages/search.js`
  - 搜索结果增加“抓取并解析”按钮
  - 搜索结果增加“进入阅读页”入口
- 更新 `pages/papers.js`
  - 增加 parse 按钮
  - 增加阅读页跳转入口
- 更新 `pages/index.js`
  - 首页加入 Stage 2 导航说明

## 如何验证

### 后端读取验证

```bash
cd /opt/paperradar/app
PYTHONPATH=. python3 - <<'PY'
from backend.reader import get_reader_payload
payload = get_reader_payload('paper_12f25bc580495784')
print(payload['paper_id'], payload['chunk_count'], len(payload['preview']['paragraphs']))
PY
```

预期：成功输出 paper_id / chunk_count / paragraph 数。

### 前端构建验证

```bash
cd /opt/paperradar/app/frontend
npm run build
```

预期：构建通过，生成 `/reader/[paperId]` 路由。

## 当前还没做什么

- 还没做复杂高亮
- 还没做章节级目录
- 还没做引用跳转
- 还没做图表提取
- 当前阅读页主要基于 preview + chunk，适合 Stage 2 Batch 1 基础浏览

## 下一批建议

进入 **Batch 2：单篇论文报告生成器**，产出 JSON / HTML 报告，并为后续报告查看页打基础。
