---
title: NewAPI Tools
emoji: 🧰
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
---

# NewAPI Tools (HF Space)

此目录用于 Hugging Face Spaces 的 Docker 快速部署。
构建时直接复用 GHCR 预构建镜像，避免重复编译。

## 使用方式

1. 将 `_hf/` 目录内容同步到 Space 仓库根目录。
2. 在 Space 的 Variables 中配置环境变量。
3. 启动后访问 `https://<space>.hf.space/`。

## 必填环境变量

- `ADMIN_PASSWORD`
- `API_KEY`
- `JWT_SECRET`
- `SQL_DSN`（或使用分离配置 `DB_ENGINE` / `DB_DNS` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD`）

## 可选环境变量

- `NEWAPI_BASEURL`
- `NEWAPI_API_KEY`
- `REDIS_PASSWORD`
- `REDIS_APPENDONLY`
- `REDIS_MAXMEMORY`
- `REDIS_MAXMEMORY_POLICY`

## 端口说明

- 默认对外端口为 `7860`，HF 会自动注入 `PORT`。
