#!/bin/bash
# 快速核对本目录服务身份，不读取研究原件。
exec "$(dirname "$0")/modulea.command" status "$@"
