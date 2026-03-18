# 技术栈与部署要点

最后更新：2026-03-18

## 核心技术

- Go：后端 API 服务。
- Nginx：静态资源服务与反向代理。
- Redis：本地缓存与数据加速。
- Docker：单镜像部署。
- Hugging Face Spaces：Docker 运行环境。

## 关键环境变量

- `PORT`：HF 注入的外部访问端口，默认目标为 `7860`。
- `SERVER_PORT`：Go 后端监听端口，默认 `8000`。
- `STARTUP_TIMEOUT_SECONDS`：启动自检超时时间，默认 `60` 秒。
- `HEALTHCHECK_CURL_TIMEOUT_SECONDS`：探活请求超时，默认 `5` 秒。

## 关键文件

- `Dockerfile`
- `frontend/nginx.conf`
- `docker/entrypoint.sh`
- `docker/healthcheck.sh`
- `_hf/README.md`
