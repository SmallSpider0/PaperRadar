# 项目：PaperRadar

## 摘要
安全顶会论文跟踪、语义检索、报告生成与订阅推送系统（本机开发部署）。

## 当前目标
在本服务器上开发并部署一个内部使用的“扫会”系统，按三阶段推进。首期只完成核心闭环：论文元数据抓取、按需全文抓取、按需解析、语义检索与基础订阅；HTML/PPT 报告、配图和复杂可视化后置到后续阶段。

## 项目约束
- 每次代码修改完成后，必须按改动范围执行对应刷新与验证：
  - 仅前端改动：执行前端构建与发布（`npm run build` + 同步静态目录）并 `reload nginx`
  - 仅后端改动：`restart paperradar-api` 并进行 health 检查
  - 前后端同时改动：先前端发布，再后端重启，最后 `reload nginx`，并做联合可用性验证
- 构建前验证是强约束：
  - 前端构建前必须先执行 `scripts/validate_prebuild.py`（已接入 `app/frontend/package.json` 的 `prebuild`）
  - 验证脚本只允许做本地静态/语法/规则检查，禁止任何 LLM 调用、外部 API 请求或联网依赖
  - 验证失败时必须中止构建与发布流程
- 鉴权与权限是强约束，新增功能必须遵守：
  - 新增后端业务接口默认必须鉴权（未登录返回 `401`），仅明确白名单（如 `/health`、登录接口）可匿名访问
  - 仅靠前端隐藏菜单不算安全，敏感能力必须在后端做角色校验（无权限返回 `403`）
  - 涉及管理能力（系统状态、全文处理、用户管理等）默认仅 `admin` 可访问；普通用户仅开放约定功能面
  - 新增页面必须接入登录态守卫与角色可见性控制，防止通过直接 URL 绕过
  - 涉及用户数据的读写必须按 `current_user.id` 做隔离，禁止跨用户读取/覆盖
  - 鉴权相关改动必须附带三类验证：未登录（401）、普通用户（允许/拒绝）、管理员（全量）
- 安全基线约束：
  - 会话凭证使用 `HttpOnly Cookie`，服务端仅存 token hash，不在前端持久化明文 token
  - 默认开启登录失败限速与会话失效机制（登出即失效、过期自动失效）
  - 禁止在代码中硬编码长期有效密码；管理员初始凭证必须通过环境变量注入并在部署后立即更换

## 目录说明
- `uploads/`：用户上传原始资料
- `docs/`：项目文档
- `ai/`：AI 辅助文件
- `memory/`：项目记录
- `output/`：交付结果

## 服务重启方法

### 1) 重启后端 API（FastAPI）

```bash
cd /opt/paperradar/app
systemctl restart paperradar-api
systemctl is-active paperradar-api
curl -sS http://127.0.0.1:8100/health
```

预期：
- `systemctl is-active` 返回 `active`
- 健康检查返回 `{"status":"ok",...}`

### 2) 仅刷新 Nginx（改路由或前端静态托管后）

```bash
systemctl reload nginx
```

### 3) 只改前端页面时（推荐流程）

```bash
cd /opt/paperradar/app/frontend
npm run build
rsync -a --delete out/ /var/www/paperradar/
systemctl reload nginx
```

### 4) 统一发布命令（推荐）

```bash
cd /opt/paperradar
bash app/scripts/deploy.sh all
```

可选模式：
- `bash app/scripts/deploy.sh frontend`：验证 + 前端构建发布 + reload nginx
- `bash app/scripts/deploy.sh backend`：重启后端 + health 检查
- `bash app/scripts/deploy.sh all`：验证 + 前端发布 + 后端重启 + reload nginx
