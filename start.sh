#!/usr/bin/env bash
# 织叙-NexTale 启动脚本
cd "$(dirname "$0")"
exec .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --reload "$@"
