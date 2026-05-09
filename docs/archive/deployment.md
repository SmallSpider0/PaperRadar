# PaperRadar 部署说明（首版）

## 推荐部署方式

首期采用本机单机部署：

- `paperradar-web.service`
- `paperradar-api.service`
- `paperradar-worker.service`
- PostgreSQL
- Redis
- Nginx
- GROBID（可选 Docker）

## 目录约定

- 项目代码：`projects/PaperRadar/app/`
- 存储目录：`projects/PaperRadar/storage/`
- 文档目录：`projects/PaperRadar/docs/`

## 反向代理建议

- `/` → web
- `/api/` → api
- `/files/` → 静态产物

## 运行建议

- API / Worker / Web 都使用 systemd 托管
- PostgreSQL / Redis 仅监听本地
- 定时抓取通过 worker 定时任务或 cron 触发
- 生成任务（embedding / 报告 / 图片）使用队列限流

## 备份

- PostgreSQL：每日备份
- storage/：定期归档
- 重要产物：HTML / PPT / 按需抓取的 PDF 原件保留 hash
