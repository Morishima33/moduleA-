#!/bin/bash
# 正常停止只调用认证接口；confirmed由用户主动提供。
exec "$(dirname "$0")/modulea.command" stop "$@"
