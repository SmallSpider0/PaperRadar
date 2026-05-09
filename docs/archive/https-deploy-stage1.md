# Stage 1 HTTPS 部署说明

## 当前方案

复用服务器现有的 HTTPS nginx 默认站点与证书，将 PaperRadar 挂到现有公网入口下：

- UI: `https://example.com/paperradar/`
- API: `https://example.com/paperradar-api/`

## 这样做的原因

- 不需要新增域名
- 不需要重新申请证书
- 可以直接复用当前服务器已生效的 TLS 配置

## nginx 位置

- `/etc/nginx/sites-enabled/openclaw-https`
- `/etc/nginx/snippets/paperradar-location.conf`

## 服务

- API: 127.0.0.1:8100
- Web: 127.0.0.1:3100
