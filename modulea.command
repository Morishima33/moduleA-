#!/bin/bash
# Windows与macOS共用Python运行管理；默认启动并打开浏览器。
set -e
modulea_root="$(cd "$(dirname "$0")" && pwd)"
exec "${MODULEA_PYTHON:-python3}" -B "$modulea_root/tools/manage_service.py" "$@"
