# PaperRadar

PaperRadar 是一个部署在本服务器上的内部科研工具，用于跟踪特定计算机研究方向的最新论文进展。

当前项目**只允许推进 Stage 1（核心闭环）**。

## 当前范围（只做 Stage 1）

Stage 1 只做以下内容：

- 论文元数据抓取
- 元数据入库与去重
- 按需全文抓取
- 按需全文解析
- metadata / fulltext 检索
- 基础订阅
- 最小前端
- 本机部署模板

## 当前明确不做

以下内容全部不是 Stage 1：

- HTML 报告系统
- PPT 生成
- Nano Banana 配图
- 高级可视化
- 多租户权限系统
- 分布式复杂架构

## 最重要的产品约束

### 1. metadata-first

默认只抓：

- 论文元数据
- 摘要
- 来源链接

### 2. fulltext-on-demand

默认不抓 PDF 全文。

只有这些场景才允许抓全文：

- 人工显式触发
- 报告生成任务触发（设计先保留）
- 后台明确任务触发

### 3. 搜索不能偷偷触发全文抓取

- 普通搜索不能自动下载 PDF
- 普通列表页不能自动下载 PDF
- 普通 ingest 不能自动下载 PDF

## 文档导航（优先阅读顺序）

如果后续由 AI agent 开发，请按这个顺序读：

1. `docs/agent-handoff-stage1-complete.md`
2. `docs/stage-1-core.md`
3. `docs/ingestion-policy.md`
4. `docs/data-model.md`
5. `docs/api.md`
6. `docs/tasks-stage-1.md`
7. `docs/implementation-batches.md`
8. `docs/stage-2-batches.md`
9. `docs/stage-2-implementation-batches.md`
10. `docs/deployment-status.md`

## Stage 1 成功标准

必须全部满足：

1. 能抓取 USENIX / NDSS 论文元数据
2. 能稳定入库并去重
3. 能按需抓取 PDF
4. 能按需解析并建立检索索引
5. 能完成 metadata 搜索
6. 能创建并命中订阅
7. 能在网页中查看结果
8. 能以 systemd + nginx 方式部署
9. 能通过 HTTPS 访问已部署实例

## 当前部署状态

- UI: `https://example.com/paperradar/`
- API health: `https://example.com/paperradar-api/health`

## 一句话结论

**PaperRadar 当前不是“论文全文仓库”，而是“元数据优先、全文按需”的 Stage 1 核心系统。后续所有开发都必须围绕这个边界执行。**
