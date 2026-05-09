# Stage 2 Runtime / Deploy Notes

更新时间：2026-03-26

本文档记录 PaperRadar 当前 Stage 2 的运行方式、发布步骤、以及前端 / 后端 / worker / Redis / Nginx 各自什么时候需要重启或 reload。

## 1. 当前线上结构

- **前端 UI**：静态导出产物，由 Nginx 直接托管
  - 源目录：`app/frontend/`
  - 导出目录：`app/frontend/out/`
  - 线上静态目录：`/var/www/paperradar/`
  - 外部入口：`https://example.com/paperradar`
- **后端 API**：FastAPI + systemd
  - 服务名：`paperradar-api`
  - 监听：`127.0.0.1:8100`
  - 外部入口：`https://example.com/paperradar-api/`
- **检索队列 worker**：Redis + 独立 systemd worker
  - 服务名：`paperradar-retrieval-worker`
  - 作用：消费重型 retrieval job，限制并发，避免多用户请求同时压垮内存
- **Redis**：检索队列后端
  - 建议监听：`127.0.0.1:6379`
  - 作用：持久化 pending/running/completed job 状态
- **反向代理**：Nginx
  - 配置片段：`/etc/nginx/snippets/paperradar-location.conf`
  - 项目模板：`app/deploy/nginx-paperradar.conf`

## 2. 为什么前端不再用 next start

这次排查确认：

- `next start` + `basePath=/paperradar` 下，页面 HTML 能返回，但 `/_next/static/*` 在当前部署形态里会出现异常 404
- 问题不在构建产物缺失，而在运行时静态资源服务不稳定

因此当前改为：

- `next build` + `output: 'export'`
- Nginx 直接托管导出后的静态文件

这样更简单，也更适合当前 PaperRadar 的对外访问方式。

## 3. 日常发布命令

### 3.1 只改前端（页面 / 样式 / 交互）

```bash
cd /opt/paperradar/app/frontend
npm run build
rsync -a --delete out/ /var/www/paperradar/
systemctl reload nginx
```

### 3.2 改后端 Python（FastAPI / 接口 / 检索逻辑）

```bash
cd /opt/paperradar/app
systemctl restart paperradar-api
systemctl restart paperradar-retrieval-worker
```

### 3.3 首次部署 / 变更新增依赖（Redis queue）

```bash
cd /opt/paperradar/app/backend
python3 -m pip install -r requirements.txt

systemctl enable --now redis
cp /opt/paperradar/app/deploy/paperradar-retrieval-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now paperradar-retrieval-worker
```

### 3.4 改 Nginx 路由 / 静态托管规则

```bash
cp /opt/paperradar/app/deploy/nginx-paperradar.conf /etc/nginx/snippets/paperradar-location.conf
nginx -t
systemctl reload nginx
```

## 4. 验证方式

### 4.1 验证前端页面

```bash
curl -k -I https://example.com/paperradar
curl -k -I https://example.com/paperradar/chat
```

预期：`200`

### 4.2 验证静态资源

可从页面里抓取实际 chunk 名后验证，也可先测核心资源：

```bash
curl -k https://example.com/paperradar | grep -o '/paperradar/_next/static[^" ]*'
```

然后对输出路径逐个验证：

```bash
curl -k -I 'https://example.com/paperradar/_next/static/...'
```

预期：CSS / JS / `_buildManifest.js` / `_ssgManifest.js` 都返回 `200`

### 4.3 验证后端

```bash
curl http://127.0.0.1:8100/health
curl -k https://example.com/paperradar-api/health
```

预期：健康检查正常

### 4.4 验证检索队列

```bash
systemctl status redis --no-pager
systemctl status paperradar-retrieval-worker --no-pager
curl http://127.0.0.1:8100/health
```

预期：

- `redis` 与 `paperradar-retrieval-worker` 都是 `active (running)`
- `/health` 返回 `retrieval_queue.online=true`
- System 页面能看到 `pending / active / max concurrency`

## 5. 判断该重启什么

### 情况 A：只改前端页面

- 需要：`npm run build` + `rsync` + `systemctl reload nginx`
- 不需要：`systemctl restart paperradar-api`

### 情况 B：改了后端接口或 Python 逻辑

- 需要：`systemctl restart paperradar-api`
- `deploy.sh backend` 现默认也会重启 `paperradar-retrieval-worker`，避免检索逻辑变更后 worker 仍跑旧代码
- 前端没变时，不需要重新发布前端

### 情况 C：改了 Nginx 路由

- 需要：`nginx -t` + `systemctl reload nginx`

### 情况 D：同时改前后端

推荐顺序：

1. 发布前端静态产物
2. 重启后端 API
3. 重启 retrieval worker
4. reload Nginx
5. 做页面 + API 联合验证

## 6. 常见误区

### 误区 1：看到前端 404 就先重启 paperradar-api

不对。若是 `/paperradar/_next/static/*` 404，优先看：

- 前端是否重新 build
- `out/` 是否同步到 `/var/www/paperradar/`
- Nginx 是否已 reload
- 浏览器是否还缓存旧 HTML

### 误区 2：每次都先 pkill uvicorn

不建议。

如果 `paperradar-api` 是 systemd 管理，通常直接：

```bash
systemctl restart paperradar-api
```

就够了。

### 误区 3：前端仍用 next start 提供线上页面

当前不推荐。已确认这条路在本项目当前配置下更容易引出静态资源 404。

## 7. 当前推荐流程（最小版）

### 前端发布

```bash
cd /opt/paperradar/app/frontend
npm run build
rsync -a --delete out/ /var/www/paperradar/
systemctl reload nginx
```

### 后端发布

```bash
cd /opt/paperradar/app
systemctl restart paperradar-api
systemctl restart paperradar-retrieval-worker
```

或直接：

```bash
cd /opt/paperradar
bash app/scripts/deploy.sh backend
```

### 联合检查

```bash
curl -k -I https://example.com/paperradar
curl -k -I https://example.com/paperradar/chat
curl -k https://example.com/paperradar | grep -o '/paperradar/_next/static[^" ]*'
curl -k https://example.com/paperradar-api/health
systemctl status paperradar-retrieval-worker --no-pager
```

## 8. 备注

- 若页面仍显示旧资源路径，先做浏览器强刷：
  - macOS：`Cmd + Shift + R`
  - Windows/Linux：`Ctrl + Shift + R`
- `app/deploy/nginx-paperradar.conf` 是项目内模板；线上真实生效的是 `/etc/nginx/snippets/paperradar-location.conf`
- 前端静态托管目录以 `/var/www/paperradar/` 为准
- 如果搜索页或聊天页长时间停在 `queued`，优先检查 `redis` 和 `paperradar-retrieval-worker` 是否还活着
