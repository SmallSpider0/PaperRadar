# Stage 1 / 批次 5 补强

## 本次补强目标

在最小 on-demand 链路基础上，继续把批次 5 做完整一些：

- 优先从详情页发现 PDF 链接
- 下载 PDF 而不是只保存 HTML
- 增加基础 chunk 切分
- 为已解析全文生成基础 embedding

## 当前实现

- `app/backend/chunking.py`
- `app/backend/fulltext.py` 已补：
  - HTML 中自动发现 PDF 链接
  - PDF 优先保存
  - 基于 `pdfminer` 的 PDF 文本抽取
  - 基础 chunk 切分
  - 最多前 10 个 chunk 的 embedding

## 当前边界

- 当前 PDF 解析属于 Stage 1 的可用版本，不是高保真学术结构化解析
- 后续若要更稳定的章节、标题、作者、引用结构，仍建议接 GROBID
