#!/usr/bin/env bash
#
# 启动 Mac Edge（网关）—— 遵循 agent-control-plane-deployment 部署规范。
#
# 平台调用：cwd = runtimeDir、注入 PORT / SERVICE_PORT / RUNTIME_DIR / APP_VERSION；
# 契约：port=9528、health_url=http://127.0.0.1:9528/health。
#
# 端口说明：
#   * 8790 / 8000 等是 Edge 自己的能力端口（voice stream / 小度 TTS 拉流），由代码决定，不在这里改；
#   * 9528 是**健康检查口**，由 scripts/health_server.py 提供（Edge 本体没有 /health 路由）。
#
# 运行期文件全部放 <runtime>/backend/（平台部署唯一保留的位置）：
#   backend/.env          密钥 + 运行期配置（模板见 mac/.env.example）
#   backend/data/.venv    依赖 venv（平台保留位）
#   backend/runtime.pid   本脚本写；backend/server.log  stdout/err（平台保留清单里的那一个）
# 数据 / 库 / 日志都在代码与 runtime 目录之外（平台 --delete 碰不到），由 backend/.env 指定：
#   MAC_EDGE_DATA_DIR    运行期数据（edge_id / ledger / 录音 / 缓存）
#   MAC_EDGE_DB_DIR      SQLite 库（ncm_songs.sqlite3）→ 见 mac/src/mac_edge/db_paths.py
#   MAC_EDGE_LOG_DIR     运行期日志（mac_voice / intranet_ping / health），默认跟 DATA_DIR 走
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# runtime 目录以脚本自身位置为准（不认继承来的 RUNTIME_DIR，可能是别的服务）
SELF_RUNTIME_DIR="$(cd "${DIR}/.." && pwd)"
APP_VERSION="${APP_VERSION:-dev}"

log() { echo "[start] $*"; }
warn() { echo "[start][警告] $*" >&2; }
die() { echo "[start][错误] $*" >&2; exit 1; }

if [ -n "${RUNTIME_DIR:-}" ] && [ "${RUNTIME_DIR}" != "${SELF_RUNTIME_DIR}" ]; then
  warn "忽略继承来的 RUNTIME_DIR=${RUNTIME_DIR}，按脚本位置用 ${SELF_RUNTIME_DIR}"
fi
RUNTIME_DIR="${SELF_RUNTIME_DIR}"

MAC_DIR="${RUNTIME_DIR}/mac"
BACKEND_DIR="${RUNTIME_DIR}/backend"
ENV_FILE="${BACKEND_DIR}/.env"
# 老位置：mac/.env（本地开发就是这个位置；run_mac_edge.sh 也会 source 它）
ENV_FILE_LEGACY="${MAC_DIR}/.env"
RUN_DIR="${BACKEND_DIR}/data"          # 只放 venv（平台保留位；数据在 MAC_EDGE_DATA_DIR）
VENV="${RUN_DIR}/.venv"
PY="${VENV}/bin/python"
REQ="${MAC_DIR}/requirements.txt"
PID_FILE="${BACKEND_DIR}/runtime.pid"
LOG_FILE="${BACKEND_DIR}/server.log"
HEALTH_PID_FILE="${BACKEND_DIR}/health.pid"
HEALTH_LOG="${BACKEND_DIR}/health.log"

[ -d "${MAC_DIR}/src/mac_edge" ] || die "缺少 ${MAC_DIR}/src/mac_edge（runtime 布局应为 <runtime>/mac/src/mac_edge）"
command -v python3 >/dev/null 2>&1 || die "本机没有 python3"
python3 -c 'import sys; assert sys.version_info >= (3, 10), sys.version' || die "需要 Python 3.10+"

# .env：以 backend/.env 为准（平台保留）；老位置 <runtime>/.env 迁过来并留 symlink
if [ ! -f "${ENV_FILE}" ]; then
  if [ -f "${ENV_FILE_LEGACY}" ]; then
    mkdir -p "${BACKEND_DIR}"
    log "把 ${ENV_FILE_LEGACY} 迁到 ${ENV_FILE}（部署只保 backend/）"
    mv "${ENV_FILE_LEGACY}" "${ENV_FILE}"
  else
    warn "没有 ${ENV_FILE}：Edge 仍可启动，但视觉/小米/网易云等需要密钥的能力会不可用"
    warn "模板见 ${MAC_DIR}/.env.example"
    mkdir -p "${BACKEND_DIR}"
    : > "${ENV_FILE}"
  fi
fi
chmod 600 "${ENV_FILE}" 2>/dev/null || true
if [ ! -e "${ENV_FILE_LEGACY}" ]; then
  ln -sfn "${ENV_FILE}" "${ENV_FILE_LEGACY}"
fi

# 健康检查口（= 平台契约里的 port/healthUrl 端口）。解析顺序：
#   1) shell 里显式 MAC_EDGE_HEALTH_PORT
#   2) backend/.env 里的 MAC_EDGE_HEALTH_PORT（部署配置，跟数据/密钥放一起）
#   3) 平台注入的 SERVICE_PORT（正式字段名）
#   4) 默认 9528
# **刻意不看继承来的 PORT**：交互式 shell 里常残留别的服务的 PORT（实测 web-cursor 4211），
# 照它走会在 127.0.0.1:4211 上和 web-cursor 抢位置 —— 那是别的服务的健康口。
_ENV_PORT="$(awk -F= '/^[[:space:]]*MAC_EDGE_HEALTH_PORT[[:space:]]*=/{gsub(/[[:space:]"]/,"",$2); v=$2} END{print v}' "${ENV_FILE}" 2>/dev/null || true)"
HEALTH_PORT="${MAC_EDGE_HEALTH_PORT:-${_ENV_PORT:-${SERVICE_PORT:-9528}}}"
if [ -n "${PORT:-}" ] && [ "${PORT}" != "${HEALTH_PORT}" ]; then
  warn "忽略继承来的 PORT=${PORT}（那是别的服务的），健康口用 ${HEALTH_PORT}"
fi

# 运行期数据目录（edge_id / ledger / 录音 / 各能力缓存；SQLite 库另由 MAC_EDGE_DB_DIR 决定）。
# 解析顺序：shell 里显式 MAC_EDGE_DATA_DIR > backend/.env 的 MAC_EDGE_DATA_DIR > <runtime>/backend/data。
# 本机生产把它指到代码外（~/artifact-storage/home-agent-gateway），代码/部署都碰不到。
_ENV_DATA_DIR="$(awk -F= '/^[[:space:]]*MAC_EDGE_DATA_DIR[[:space:]]*=/{gsub(/[[:space:]"]/,"",$2); v=$2} END{print v}' "${ENV_FILE}" 2>/dev/null || true)"
DATA_DIR="${MAC_EDGE_DATA_DIR:-${_ENV_DATA_DIR:-${RUN_DIR}}}"
case "${DATA_DIR}" in /*) ;; *) DATA_DIR="${RUNTIME_DIR}/${DATA_DIR}";; esac
export MAC_EDGE_DATA_DIR="${DATA_DIR}"

# 日志目录（mac_voice.supervised.out.log / intranet_ping.log / health.log）**跟随运行时环境**：
# shell 的 MAC_EDGE_LOG_DIR > backend/.env 的 MAC_EDGE_LOG_DIR > <数据目录>/logs。
# 这样日志不落在代码目录里（平台部署 --delete 会清），而是跟运行期数据放一起。
_ENV_LOG_DIR="$(awk -F= '/^[[:space:]]*MAC_EDGE_LOG_DIR[[:space:]]*=/{gsub(/[[:space:]"]/,"",$2); v=$2} END{print v}' "${ENV_FILE}" 2>/dev/null || true)"
LOG_DIR="${MAC_EDGE_LOG_DIR:-${_ENV_LOG_DIR:-${DATA_DIR}/logs}}"
case "${LOG_DIR}" in /*) ;; *) LOG_DIR="${RUNTIME_DIR}/${LOG_DIR}";; esac
export MAC_EDGE_LOG_DIR="${LOG_DIR}"
HEALTH_LOG="${LOG_DIR}/health.log"

mkdir -p "${DATA_DIR}" "${LOG_DIR}" "${RUN_DIR}" "${BACKEND_DIR}"
# 依赖：mac/requirements.txt（httpx / 声卡 / STT / PDF 渲染等）。缺 venv 现建。
if [ ! -x "${PY}" ]; then
  log "创建 venv ${VENV}"
  python3 -m venv "${VENV}" || die "python3 -m venv 失败"
fi
if ! "${PY}" -c 'import mac_edge, httpx, sounddevice, numpy' >/dev/null 2>&1; then
  log "安装依赖（$(basename "${REQ}")）"
  PYTHONPATH="${MAC_DIR}/src" "${PY}" -m pip install -q --disable-pip-version-check -r "${REQ}" || {
    warn "pip 安装失败（离线 / 缺系统库？）→ 用 --system-site-packages 重建 venv 兜底"
    rm -rf "${VENV}"
    python3 -m venv --system-site-packages "${VENV}" || die "重建 venv 失败"
    PYTHONPATH="${MAC_DIR}/src" "${PY}" -m pip install -q --disable-pip-version-check -r "${REQ}" || true
  }
fi
PYTHONPATH="${MAC_DIR}/src" "${PY}" -c 'import mac_edge, httpx, sounddevice, numpy' >/dev/null 2>&1 \
  || die "venv 里缺少依赖，请联网后重跑本脚本"

# 已在运行就不重复拉起
if [ -f "${PID_FILE}" ]; then
  old="$(tr -d '[:space:]' < "${PID_FILE}" || true)"
  if [ -n "${old}" ] && kill -0 "${old}" 2>/dev/null; then
    log "已在运行 pid=${old}"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

log "启动 部署版本=${APP_VERSION} runtime=${RUNTIME_DIR} 数据目录=${DATA_DIR} 日志目录=${LOG_DIR} 健康口=127.0.0.1:${HEALTH_PORT}"
cd "${MAC_DIR}"
# Edge 本体（run_mac_edge.sh 里的默认值都可被这里的 env 覆盖）
PYTHONUNBUFFERED=1 \
MAC_EDGE_DATA_DIR="${DATA_DIR}" \
MAC_EDGE_HEALTH_PORT="${HEALTH_PORT}" \
MAC_EDGE_PYTHON="${PY}" \
nohup bash "${MAC_DIR}/run_mac_edge.sh" >> "${LOG_FILE}" 2>&1 < /dev/null &
echo $! > "${PID_FILE}"
pid="$(cat "${PID_FILE}")"

# 健康小服务（Edge 没有 /health 路由）：读 pid 文件 + 日志心跳判活，给平台探活用
nohup env MAC_EDGE_HEALTH_PORT="${HEALTH_PORT}" \
  RUNTIME_DIR="${RUNTIME_DIR}" "${PY}" "${DIR}/health_server.py" \
  >> "${HEALTH_LOG}" 2>&1 < /dev/null &
echo $! > "${HEALTH_PID_FILE}"

for _ in $(seq 1 60); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "[start][错误] Edge 进程已退出，最近日志：" >&2
    tail -30 "${LOG_FILE}" >&2 || true
    exit 1
  fi
  if curl -fsS -m 2 "http://127.0.0.1:${HEALTH_PORT}/health" >/dev/null 2>&1; then
    log "启动成功 pid=${pid} 健康=http://127.0.0.1:${HEALTH_PORT}/health log=${LOG_FILE}"
    exit 0
  fi
  sleep 0.5
done

echo "[start][错误] 30s 内 /health 未就绪，最近日志：" >&2
tail -30 "${LOG_FILE}" >&2 || true
kill "${pid}" 2>/dev/null || true
rm -f "${PID_FILE}"
exit 1
