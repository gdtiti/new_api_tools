# NewAPI Middleware Tool - All-in-One Dockerfile (Go Backend)
# 前端 + Go 后端合并到单个镜像
#
# 构建缓存说明:
#   - npm 依赖缓存: /root/.npm
#   - Go 模块缓存: /go/pkg/mod
#   - Go 编译缓存: /root/.cache/go-build
#   使用 docker buildx build 或 DOCKER_BUILDKIT=1 启用缓存挂载

# syntax=docker/dockerfile:1

# Stage 1: 构建前端
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: 构建 Go 后端
FROM --platform=$BUILDPLATFORM golang:1.25-alpine AS backend-builder
ARG TARGETARCH
WORKDIR /build
RUN apk add --no-cache git ca-certificates tzdata

# 先复制依赖文件，利用层缓存
COPY backend/go.mod backend/go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

# 复制源码并编译，挂载 Go 编译缓存
COPY backend/ .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=$TARGETARCH go build \
    -ldflags="-s -w" \
    -o /build/server \
    ./cmd/server

# Stage 3: 最终镜像 (Nginx + Go binary)
FROM alpine:3.19
WORKDIR /app

# 安装 Nginx 和运行时依赖
RUN apk add --no-cache \
    nginx \
    supervisor \
    redis \
    curl \
    ca-certificates \
    tzdata

# 复制 Go 二进制
COPY --from=backend-builder /build/server /app/server

# 创建数据目录
RUN mkdir -p /app/data /app/data/redis && chmod 755 /app/data /app/data/redis

# 复制前端构建产物
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# 复制 Nginx 配置
COPY frontend/nginx.conf /etc/nginx/http.d/default.conf

# Copy container startup helpers
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
COPY docker/healthcheck.sh /app/docker/healthcheck.sh
RUN chmod +x /app/docker/entrypoint.sh /app/docker/healthcheck.sh

# Supervisor 配置 - 同时运行 Nginx / Go 后端 / Redis
RUN mkdir -p /etc/supervisor.d && \
    cat <<'EOF' > /etc/supervisord.conf
[supervisord]
nodaemon=true
user=root

[program:nginx]
command=/usr/sbin/nginx -g "daemon off;"
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:backend]
command=/app/server
directory=/app
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:redis]
command=/bin/sh -c 'REDIS_ARGS="--appendonly ${REDIS_APPENDONLY:-yes} --dir /app/data/redis --maxmemory ${REDIS_MAXMEMORY:-256mb} --maxmemory-policy ${REDIS_MAXMEMORY_POLICY:-allkeys-lru}"; if [ -n "$REDIS_PASSWORD" ]; then REDIS_ARGS="$REDIS_ARGS --requirepass $REDIS_PASSWORD"; fi; exec redis-server $REDIS_ARGS'
autostart=true
autorestart=true
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
EOF

ENV SERVER_PORT=8000
ENV REDIS_HOST=127.0.0.1
ENV REDIS_PORT=6379
ENV PORT=7860
ENV STARTUP_TIMEOUT_SECONDS=60
ENV HEALTHCHECK_CURL_TIMEOUT_SECONDS=5

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["/app/docker/healthcheck.sh"]

CMD ["/app/docker/entrypoint.sh"]
