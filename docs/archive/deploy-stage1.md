# Stage 1 部署模板说明

## 当前提供

- `app/deploy/paperradar-api.service`
- `app/deploy/paperradar-web.service`
- `app/deploy/nginx-paperradar.conf`

## 说明

这批先提供最小 systemd / nginx 模板，满足 Stage 1 的可部署要求。

后续如果继续推进，可再补：

- worker service
- 更正式的环境文件
- 自动初始化脚本
- 日志与监控配置
