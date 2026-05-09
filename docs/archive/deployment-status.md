# 当前部署状态

## 运行中的服务

- `paperradar-api.service`
- `paperradar-web.service`
- `postgresql`
- `nginx`

## 当前访问地址

- UI: `https://example.com/paperradar/`
- API health: `https://example.com/paperradar-api/health`

## 本机端口

- API: `127.0.0.1:8100`
- Web: `127.0.0.1:3100`
- PostgreSQL: `127.0.0.1:5432`

## 备注

- HTTPS 复用了服务器现有 nginx 与证书
- 当前为 Stage 1 可运行部署状态
