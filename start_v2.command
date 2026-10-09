#!/bin/bash
# 启动新版工作台（macOS / Linux）：双击或在终端运行。需要 Python 3.11 或更新版本。
cd "$(dirname "$0")" || exit 1
PY="${MODULEA_PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "需要 Python 3.11 或更新版本；可用 MODULEA_PYTHON 指定"; exit 1; }
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
exec "$PY" -m modulea serve --port "${MODULEA_PORT:-8780}" "$@"
