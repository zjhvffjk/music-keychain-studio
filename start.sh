#!/usr/bin/env bash
# Minuet Workbench 启动脚本（macOS / Linux）
#
# 首次使用建议：
#   python3 -m venv .venv
#   .venv/bin/pip install -r requirements.txt
set -e

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
elif command -v python >/dev/null 2>&1; then
  PY="python"
else
  echo "[!] 找不到 Python，请先安装 Python 3.9+。" >&2
  exit 1
fi

exec "$PY" "workbench/server.py" "$@"
