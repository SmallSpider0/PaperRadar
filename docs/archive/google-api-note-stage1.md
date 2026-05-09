# Stage 1 语义能力说明（Google API）

PaperRadar 在 Stage 1 可以使用用户现有的 Google API 能力来完成：

- metadata embedding
- fulltext embedding（仅针对按需解析后的内容）
- 语义检索相关实验

当前原则：

- 先把 metadata-first / fulltext-on-demand 主链路搭好
- Google API 作为 embedding / semantic retrieval 的实现选项
- 不因为接入 Google API 就改变“默认不抓全文”的策略

建议后续在 Stage 1 的检索批次中：

- 优先做 metadata embedding
- 把 embedding provider 抽象成可替换层
- 首个 provider 可直接支持 Google embedding API
- 当前服务器上的 key 已验证可用 embedding 模型包括：`gemini-embedding-001`、`gemini-embedding-2-preview`
- 项目默认模型改为当前已验证可用的 `gemini-embedding-001`
