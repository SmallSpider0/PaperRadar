# Stage 1 按需全文链路说明

## 本批目标

实现 fulltext-on-demand 的最小主链路：

- 按需抓取全文源文件
- 保存本地文件与 hash
- 保存状态文件
- 提供解析入口
- 提供状态查询入口

## 当前实现

- `app/backend/fulltext.py`
- `app/scripts/fetch_fulltext.py`
- `app/scripts/parse_fulltext.py`
- `app/scripts/fulltext_status.py`

## 当前行为

### fetch
- 根据 `paper_url` 找到 metadata 记录
- 默认不主动触发，只有显式执行脚本 / 接口才抓
- 文件保存到 `storage/papers/<paper_id>/`
- 状态保存到 `status.json`

### parse
- 当前先做最小解析入口
- 对 HTML 文件先保留文本 preview
- 对 PDF 暂时只保留后续接口位置，下一步再补 PDF 解析

### status
- 可根据 `paper_id` 查询 `not_requested / downloaded / parsed`

## 边界

- 仍然不做默认全文抓取
- 仍然不做报告生成
- PDF 解析能力后续继续增强
