# Stage 1 实施批次（仅供 AI Agent 执行）

> 这份文档只拆 Stage 1，不包含 Stage 2 / Stage 3。

## 批次总原则

每个批次都必须满足：

- 范围小，可独立完成
- 完成后可以本地运行验证
- 不破坏 metadata-first / fulltext-on-demand
- 完成后同步更新文档

---

## 批次 1：项目骨架与基础运行

### 目标

把项目跑起来，先建立最小工程骨架。

### 本批只做

- 初始化 `app/backend`
- 初始化 `app/frontend`
- 初始化 `app/workers`
- 初始化 `app/deploy`
- 增加配置加载
- 增加 health check

### 本批交付物

- FastAPI 基础入口
- Next.js 基础入口
- 基础配置文件
- `/health` 接口
- 最小 README / 运行说明更新

### 验证标准

- backend 能启动
- frontend 能启动
- `/health` 返回正常

### 本批不要做

- 不做 crawler
- 不做数据库 schema
- 不做全文抓取
- 不做订阅逻辑

---

## 批次 2：数据库与数据模型落地

### 目标

把 Stage 1 需要的数据库结构建起来。

### 本批只做

- 连接 PostgreSQL
- 建 migration 机制
- 建 Stage 1 所需表
- 建基础 ORM / repository

### 本批交付物

- 数据库连接配置
- migration 文件
- Stage 1 基础表
- 初始化脚本

### 建表范围

优先只建：

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

### 验证标准

- migration 可执行
- 表可创建成功
- backend 能连通数据库

### 本批不要做

- 不做 crawler
- 不做 embedding 生成
- 不做前端页面开发

---

## 批次 3：元数据抓取与入库

### 目标

打通 metadata ingest 主链路。

### 本批只做

- 实现 USENIX crawler
- 实现 NDSS crawler
- 实现元数据标准化
- 实现去重入库
- 原始响应落盘

### 本批交付物

- `USENIX Security` metadata crawler
- `NDSS` metadata crawler
- metadata ingest pipeline
- 去重规则
- 原始抓取数据样例

### 验证标准

- 能抓到论文标题、摘要、作者、来源链接
- 能稳定写入数据库
- 重复抓取不会产生重复论文

### 本批不要做

- 不默认下载 PDF
- 不做全文解析
- 不做搜索 API

---

## 批次 4：metadata 检索

### 目标

先让系统不依赖全文也能搜。

### 本批只做

- 生成 metadata embeddings
- 建 metadata search API
- 支持标题 / 摘要检索
- 支持会议 / 年份过滤

### 本批交付物

- metadata embedding pipeline
- metadata search API
- 最小搜索结果格式

### 验证标准

- 输入研究方向描述，能返回相关论文
- 检索不触发 PDF 下载
- 过滤器可生效

### 本批不要做

- 不做全文 chunk 检索
- 不做报告生成

---

## 批次 5：按需全文抓取与解析

### 目标

把 fulltext-on-demand 链路补上，但只在显式触发时运行。

### 本批只做

- 实现 `fetch-fulltext`
- 实现 `parse-fulltext`
- 保存 PDF 文件与 hash
- 生成 chunk
- 生成 fulltext embedding
- 查询全文状态 API

### 本批交付物

- 按需全文抓取接口
- 按需全文解析接口
- 全文状态查询接口
- chunk / fulltext embedding 管线

### 验证标准

- 不触发接口时，不会自动下载 PDF
- 触发后能下载 PDF 并记录 hash
- 解析成功后能查到 chunk / 状态

### 本批不要做

- 不做 HTML 报告
- 不做 PPT
- 不做配图

---

## 批次 6：订阅与匹配

### 目标

把“新论文入库后可命中订阅”做起来。

### 本批只做

- 创建订阅 API
- 编辑 / 删除订阅 API
- 订阅匹配逻辑
- 命中记录
- 通知记录

### 本批交付物

- subscription API
- match pipeline
- notification record pipeline

### 验证标准

- 能创建订阅
- 新论文入库后能产生命中记录
- 同一论文不会重复刷通知

### 本批不要做

- 不做邮件 / webhook 正式推送
- 不做复杂通知中心

---

## 批次 7：最小前端与部署模板

### 目标

把 Stage 1 变成可实际使用、可部署的系统。

### 本批只做

- 搜索页
- 论文详情页
- 订阅页
- systemd 模板
- nginx 模板
- `.env.example`

### 本批交付物

- 最小前端页面
- 本机部署模板
- 运行与部署说明

### 验证标准

- 页面可访问
- 能搜索论文
- 能查看论文详情
- 能管理订阅
- 服务可通过 systemd + nginx 方式接入

### 本批不要做

- 不做高级 dashboard
- 不做统计大屏
- 不做复杂视觉设计

---

## 最终要求

AI agent 完成任一批次后，输出必须包含：

1. 本批改了哪些文件
2. 本批实现了什么
3. 本批如何验证
4. 还有哪些 Stage 1 内容没做
5. 下一批推荐做什么

---

## 一句话结论

**Stage 1 必须被拆成小批次逐步完成，绝不能让 AI agent 一上来把 Stage 2 / Stage 3 的东西也一起做进去。**
