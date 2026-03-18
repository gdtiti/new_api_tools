# 项目概览

最后更新：2026-03-18

## 系统结构

- 前端：静态资源由 Nginx 提供。
- 后端：Go 服务提供 `/api/*` 接口，默认监听 `SERVER_PORT=8000`。
- 缓存：容器内嵌 Redis，默认监听 `6379`。
- 部署：单容器运行 `nginx + backend + redis`，由 `supervisord` 管理进程。

## HF 部署链路

1. HF Spaces 通过 `README.md` 中的 `app_port: 7860` 暴露外部端口。
2. 容器启动时读取 `PORT`，渲染 Nginx 监听端口。
3. Nginx 对外提供 `PORT`，并将 `/api/` 代理到 `127.0.0.1:SERVER_PORT`。
4. Go 后端在 `SERVER_PORT` 提供 `/api/health`。

## 2026-03-18 修复摘要

- 新增 `docker/entrypoint.sh`，在启动阶段渲染 Nginx 配置并执行就绪等待。
- 新增 `docker/healthcheck.sh`，分层探测前端端口和后端端口。
- 将 `frontend/nginx.conf` 改为模板化配置，避免写死监听端口和 upstream。
- 在 `_hf/README.md` 中补充了 HF 端口说明与排查步骤。

## 风险与关注点

- Space Variables 不应手动覆盖 `PORT`，除非同步修改 `app_port`。
- 如果 `frontend probe failed` 但 `backend probe passed`，优先检查 Nginx。
- 如果前后探测都失败，优先检查后端启动日志和必填环境变量。
