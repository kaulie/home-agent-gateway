#!/usr/bin/env bash
#
# 重启 Mac Edge（网关）= stop.sh + start.sh（部署平台的 restartCmd）。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[restart] stop"
bash "${DIR}/stop.sh"
echo "[restart] start"
bash "${DIR}/start.sh"
