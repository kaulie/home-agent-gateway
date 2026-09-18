#!/usr/bin/env bash
#
# 打包脚本 —— 遵循「agent-control-plane-deployment」部署系统规范。
#
# 调用方（二选一，均从仓库根执行）：
#   - 控制面流水线：POST /api/deploy-notify {serviceId:"home-agent-gateway"}
#   - 独立发版：~/deployment/bin/release.sh home-agent-gateway [ref]
#
# 约定（与 home-agent-brain / service-registry 同一套）：
#   - cwd = 仓库根；环境变量 APP_VERSION = <8 位短 hash>
#   - 必须产出 outputs/，其中必须包含 scripts/restart.sh（平台硬性要求）
#   - VERSION / COMMIT / GIT_REPO_URL 由调用方写进发版包，本脚本不写
#   - 运行期可变内容一律不进 outputs/：平台部署是
#       rsync -a --delete --filter='P backend/{.env,data/,runtime.pid,server.log,.watchdog-paused}'
#     即 **runtime 目录里只有 backend/ 那几项和 .git/ 能活过部署**。
#     Edge 的数据目录（MAC_EDGE_DATA_DIR）与 .env / pid / log 都在 <runtime>/backend/ 下。
#
# 本服务是 Python：发版包 = 运行期目录布局，即
#   outputs/{mac/**(源码+sql+deploy), config/**(端点默认值), scripts/*.sh, build.sh?, README.md, .gitignore}
# 依赖（httpx / 声卡 / STT / PDF 等）由 scripts/start.sh 按 mac/requirements.txt 装进
#   <runtime>/backend/data/.venv（部署保留，不用每次重装）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT}"

VERSION="${APP_VERSION:-dev}"
OUT="${ROOT}/outputs"

echo "[build] home-agent-gateway version=${VERSION}"
[ -f "${ROOT}/scripts/restart.sh" ] || {
  echo "[build][错误] 缺少 scripts/restart.sh（平台硬性要求）" >&2
  exit 1
}
[ -d "${ROOT}/mac/src/mac_edge" ] || {
  echo "[build][错误] 缺少 mac/src/mac_edge（Edge 源码）" >&2
  exit 1
}
[ -d "${ROOT}/config" ] || {
  echo "[build][错误] 缺少 config/（mac_edge 读端点默认值）" >&2
  exit 1
}

# 语法体检：拦住拼写/缩进级问题；不跑单测（那是评审/CI 的事）
if command -v python3 >/dev/null 2>&1; then
  python3 -m compileall -q "${ROOT}/mac/src" "${ROOT}/config" >/dev/null || {
    echo "[build][错误] 源码语法检查未通过（python3 -m compileall）" >&2
    exit 1
  }
  echo "[build] 语法检查通过（compileall mac/src config）"
fi

rm -rf "${OUT}"
mkdir -p "${OUT}/scripts"

# mac/：源码 + sql + deploy + README（排除 .venv/data/logs/密钥/缓存）
# 注意排除模式相对「传输根」，所以写 data/ 而不是 mac/data/。
rsync -a \
  --exclude='.git/' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='.env' \
  --exclude='data/' \
  --exclude='logs/' \
  --exclude='*.egg-info/' \
  "${ROOT}/mac/" "${OUT}/mac/"

# config/：端点默认值（mac_edge 用 parents[3] 定位仓根后 import）
rsync -a --exclude='__pycache__/' --exclude='*.pyc' "${ROOT}/config/" "${OUT}/config/"

# games/coin-catcher：mac.game.host 在电视上跑的小游戏。
# 它的 dist/ 是 vite 构建产物、上游 .gitignore 忽略 → 平台部署 rsync --delete 会把它从 runtime
# 清掉（实测踩过）。这里：① 已有 dist 就带上；② 没有就用 npm 现建（需要 node）；③ 都不行则响亮告警。
GAME_SRC="${ROOT}/games/coin-catcher"
if [ -d "${GAME_SRC}" ]; then
  if [ ! -f "${GAME_SRC}/dist/index.html" ] && command -v npm >/dev/null 2>&1; then
    echo "[build] games/coin-catcher 缺 dist → npm ci && npm run build"
    (cd "${GAME_SRC}" && npm ci --silent && npm run build --silent) \
      || echo "[build][警告] 小游戏 dist 构建失败：mac.game.host 部署后会起不来（先本地 build 好再发版）" >&2
  fi
  rsync -a --exclude='node_modules/' --exclude='.DS_Store' \
    "${GAME_SRC}/" "${OUT}/games/coin-catcher/"
  if [ ! -f "${OUT}/games/coin-catcher/dist/index.html" ]; then
    echo "[build][警告] 发版包里没有 games/coin-catcher/dist/index.html：部署后 mac.game.host 不可用" >&2
  fi
fi

cp "${ROOT}/scripts/start.sh" "${ROOT}/scripts/stop.sh" "${ROOT}/scripts/restart.sh" \
  "${ROOT}/scripts/health_server.py" "${OUT}/scripts/"
[ -f "${ROOT}/README.md" ] && cp "${ROOT}/README.md" "${OUT}/README.md"
[ -f "${ROOT}/.gitignore" ] && cp "${ROOT}/.gitignore" "${OUT}/.gitignore"

find "${OUT}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

chmod +x "${OUT}/scripts/"*.sh

echo "[build] outputs 就绪："
ls -1 "${OUT}" | sed 's/^/  /'
echo "  scripts/: $(cd "${OUT}/scripts" && ls -1 | tr '\n' ' ')"
