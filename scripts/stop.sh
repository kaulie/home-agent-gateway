#!/usr/bin/env bash
#
# 停止 Mac Edge（网关）：先停健康小服务，再 TERM Edge（mac_voice 子进程由 voice supervisor 一并收掉），
# 最后兜底清掉可能残留的 mac_edge / mac_voice 进程与孤儿 mDNS 广告。
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF_RUNTIME_DIR="$(cd "${DIR}/.." && pwd)"

log() { echo "[stop] $*"; }

if [ -n "${RUNTIME_DIR:-}" ] && [ "${RUNTIME_DIR}" != "${SELF_RUNTIME_DIR}" ]; then
  log "忽略继承来的 RUNTIME_DIR=${RUNTIME_DIR}，按脚本位置用 ${SELF_RUNTIME_DIR}"
fi
RUNTIME_DIR="${SELF_RUNTIME_DIR}"
BACKEND_DIR="${RUNTIME_DIR}/backend"
PID_FILE="${BACKEND_DIR}/runtime.pid"
HEALTH_PID_FILE="${BACKEND_DIR}/health.pid"

stop_pid_file() {
  local pf="$1" label="$2"
  [ -f "${pf}" ] || return 0
  local pid
  pid="$(tr -d '[:space:]' < "${pf}" || true)"
  if [ -z "${pid}" ] || ! kill -0 "${pid}" 2>/dev/null; then
    log "${label} pid ${pid:-?} 已不存在，清理 pid 文件"
    rm -f "${pf}"
    return 0
  fi
  log "TERM → ${label} pid=${pid}"
  kill "${pid}" 2>/dev/null || true
  for _ in $(seq 1 30); do
    kill -0 "${pid}" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "${pid}" 2>/dev/null; then
    log "${label} 15s 内未退出，KILL → pid=${pid}"
    kill -9 "${pid}" 2>/dev/null || true
  fi
  rm -f "${pf}"
}

stop_pid_file "${HEALTH_PID_FILE}" "健康小服务"
stop_pid_file "${PID_FILE}" "Mac Edge"

# 兜底：pid 文件丢失时按命令行精确清理（只认 mac_edge / mac_voice，不误伤别的进程）
for pat in '[P]ython -m mac_edge' '[P]ython -m mac_voice'; do
  pids="$(pgrep -f "${pat}" 2>/dev/null || true)"
  if [ -n "${pids}" ]; then
    log "兜底清理（${pat}）：$(echo ${pids} | tr '\n' ' ')"
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 1
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
  fi
done

log "已停止"
