# 2026-03-18 HF 启动自检与探活分层诊断

状态：已采纳

## 背景

Hugging Face Spaces 在服务启动后会通过外部端口探活。
此前日志显示：

- `backend`
- `nginx`
- `redis`

都已启动，但平台仍在约 1-2 分钟后发送 `SIGTERM` 回收容器。

根因特征是：

- 容器内部服务存活。
- 外部探活链路 `PORT -> Nginx -> backend` 不可观测。
- 失败时日志无法快速定位是 Nginx 监听问题还是后端未就绪。

## 决策

采用“启动自检 + 分层健康检查”的方案：

1. `frontend/nginx.conf` 改为模板化端口与 upstream。
2. `docker/entrypoint.sh` 在启动时渲染 Nginx 配置，并在超时前持续等待 `/api/health` ready。
3. `docker/healthcheck.sh` 先探 `PORT`，再探 `SERVER_PORT`，输出分层诊断信息。
4. `_hf/README.md` 明确记录 HF 端口约束与排查方法。

## 结果

- HF 启动失败时可以直接从日志判断故障层级。
- 平台回收前，本地日志已经给出可操作的诊断信息。
- 修复发布后，HF 部署恢复正常。

## 取舍

收益：

- 降低平台环境排障时间。
- 避免“服务存活但端口未 ready”这种隐性失败。

成本：

- 容器启动逻辑从单条 `CMD` 变为脚本维护。
- 需要额外维护模板配置和探活脚本。

## 证据

- `Dockerfile`
- `frontend/nginx.conf`
- `docker/entrypoint.sh`
- `docker/healthcheck.sh`
- `_hf/README.md`
