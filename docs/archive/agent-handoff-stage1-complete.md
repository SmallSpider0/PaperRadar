# PaperRadar Agent Handoff（Stage 1 已完成）

## 1. 当前结论

PaperRadar 的 Stage 1 已经不是纸面方案，而是实际完成并部署的可运行版本。

当前可确认的状态：

- metadata crawler 已完成
- metadata search 已完成
- Google embedding 已接通并验证
- on-demand fulltext 已完成
- PDF 文本提取、chunk、embedding 已完成
- subscriptions / matching / notifications 已完成
- PostgreSQL 已接入
- minimal frontend 已完成
- HTTPS 已部署并可访问

## 2. 当前真实访问入口

- UI: `https://example.com/paperradar/`
- API health: `https://example.com/paperradar-api/health`

## 3. 当前运行中的关键服务

- `paperradar-api.service`
- `paperradar-web.service`
- `postgresql`
- `nginx`

## 4. Stage 1 实际已完成能力

### 数据获取
- USENIX Security 2025 metadata crawler
- NDSS 2025 metadata crawler
- metadata 标准化脚本

### 检索
- metadata search API
- Google embedding provider
- metadata embedding 构建脚本
- 关键词 fallback

### 全文链路
- 按需抓取全文
- 自动从详情页发现 PDF
- PDF 本地保存与 hash
- PDF 文本提取（pdfminer）
- chunk 切分
- chunk embedding

### 订阅
- 创建 / 列出 / 删除订阅
- 运行匹配
- 命中记录
- 通知记录
- PostgreSQL 同步

### 部署
- minimal frontend
- systemd 服务
- nginx HTTPS 路由

## 5. 当前 Stage 1 遗留项（不是阻塞，只是后续可优化）

- metadata / papers 主键体系仍可进一步统一
- subscriptions / matches / notifications 当前保留 JSON 备份层
- API / frontend 仍是最小版，未做更细的错误处理与体验优化
- PDF 解析当前是 Stage 1 可用实现，不是高保真的学术结构化解析

## 6. 后续 AI Agent 的边界

从现在开始，AI agent 不应该再回头重做 Stage 1 主链路，而应：

- 基于当前部署状态继续推进
- 优先进入 Stage 2
- 修补 Stage 1 时只能做增量优化，不能破坏现有运行链路

## 7. 推荐接手顺序

1. 先阅读当前文档与部署状态
2. 本地验证 UI / API / DB / HTTPS
3. 以独立 batch 方式推进 Stage 2
4. 每个 batch 做完都提交一次
