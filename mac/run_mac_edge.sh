#!/bin/bash
# 本地 / 开发前台启动；runtime（部署系统托管）走 ../scripts/start.sh。
# 所有 MAC_EDGE_* 默认值都是「已设置的 env 优先」（${X:-默认}），
# 这样部署脚本能覆盖数据目录 / 健康口 / Brain 地址，而本地默认行为不变。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
# 本地默认 .venv 就在 mac/ 下；部署时由 scripts/start.sh 指定 MAC_EDGE_PYTHON。
PY_BIN="${MAC_EDGE_PYTHON:-$ROOT/.venv/bin/python}"
export MAC_EDGE_BRAIN_URL="${MAC_EDGE_BRAIN_URL:-http://127.0.0.1:9527}"
export MAC_EDGE_INTERVAL_SEC="${MAC_EDGE_INTERVAL_SEC:-3}"
export MAC_EDGE_CLIENT_HINT="${MAC_EDGE_CLIENT_HINT:-living-room-mac}"
export MAC_EDGE_DISPLAY_NAME="${MAC_EDGE_DISPLAY_NAME:-客厅 · Mac Edge}"
export MAC_EDGE_DEVICE_TYPE="${MAC_EDGE_DEVICE_TYPE:-mac}"
export MAC_EDGE_ROOM="${MAC_EDGE_ROOM:-living-room}"
export MAC_EDGE_APP_VERSION="${MAC_EDGE_APP_VERSION:-0.3.0}"
export MAC_EDGE_DATA_DIR="${MAC_EDGE_DATA_DIR:-$ROOT/data}"
export MAC_EDGE_CAST_DISPLAY_URL="${MAC_EDGE_CAST_DISPLAY_URL:-http://127.0.0.1:9095/endpoint/display}"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
# Optional local secrets (ARK_API_KEY / MAC_EDGE_VISION_*); also loaded by Python from .env
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
# This machine registers all Mac capabilities except GoPro / img-server.
export MAC_EDGE_ROLE="${MAC_EDGE_ROLE:-laptop}"
cd "$ROOT"
exec "$PY_BIN" -m mac_edge

