---
title: NewAPI Tools
emoji: 🧰
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
---

# NewAPI Tools (HF Space)

This directory is for Hugging Face Spaces Docker deployment.
It reuses a prebuilt GHCR image to avoid rebuilding inside Spaces.

## Usage

1. Copy the contents of `_hf/` to the root of your Space repository.
2. Configure the required variables in Space Settings -> Variables.
3. Start the Space and visit `https://<space>.hf.space/`.

## Required Variables

- `ADMIN_PASSWORD`
- `API_KEY`
- `JWT_SECRET`
- `SQL_DSN`

If you do not use `SQL_DSN`, provide these split variables instead:

- `DB_ENGINE`
- `DB_DNS`
- `DB_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`

## Optional Variables

- `NEWAPI_BASEURL`
- `NEWAPI_API_KEY`
- `REDIS_PASSWORD`
- `REDIS_APPENDONLY`
- `REDIS_MAXMEMORY`
- `REDIS_MAXMEMORY_POLICY`

## Port Notes

- The public port is `7860`, and HF injects `PORT` automatically.
- Do not override `PORT` in Space Variables unless you also change `app_port`.
- The backend listens on `SERVER_PORT=8000`, and Nginx exposes `PORT`.

## Startup Self-Check

- The container renders the Nginx port config at startup before running readiness checks.
- If any hop in `PORT -> Nginx -> backend` fails, the container exits with clear diagnostics instead of waiting for HF to send `SIGTERM` later.
- Look for log prefixes `[startup]` and `[healthcheck]`.

## Troubleshooting

- Make sure the Space root `README.md` still contains `sdk: docker` and `app_port: 7860`.
- Make sure `_hf/Dockerfile` points to the GHCR image digest you actually published.
- If logs show `frontend probe failed` but `backend probe passed`, the issue is in the Nginx listen port or proxy layer.
- If both probes fail, inspect the backend startup on port `8000` and verify required environment variables.
