# 本地密钥接入说明

PaperRadar 当前已安全接入服务器上现有的 Google / Gemini API key。

## 来源

优先来源：

- 当前 shell 环境中的 `GEMINI_API_KEY`
- 服务器上的 OpenViking / OpenClaw 既有配置

## 接入方式

项目根目录新增：

- `.env.local`

该文件：

- 已被 `.gitignore` 忽略
- 不进入 Git
- 仅用于本机项目运行

## 当前读取方式

`app/backend/config.py` 会优先读取项目根目录下的 `.env.local`，并把其中变量注入运行环境。

## 原则

- 不把密钥写入仓库文件
- 不把密钥提交到 Git
- 后续 AI agent 开发时，默认只使用 `.env.local` 中的密钥，不要把 key 硬编码进代码
- 当前项目 embedding 模型应优先使用服务器上已验证可用的 `gemini-embedding-001`
