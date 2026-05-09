# Stage 1 PDF 解析验证

## 验证对象

- USENIX Security 2025 论文详情页
- URL: `https://www.usenix.org/conference/usenixsecurity25/presentation/agarwal-shubham`

## 验证内容

1. 从详情页自动发现 PDF 链接
2. 下载 PDF 到本地
3. 用 `pdfminer` 提取正文文本
4. 做 chunk 切分
5. 为前若干 chunk 生成 embedding

## 目标

这份验证用于说明：

- Stage 1 的按需全文链路已经不只是保存 PDF 文件
- 而是已经具备“抓取 PDF → 提取文本 → chunk → embedding”的可用能力
