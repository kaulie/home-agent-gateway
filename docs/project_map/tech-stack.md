# 技术栈

以 `mac/requirements.txt`、`scripts/start.sh`、`build.sh` 为准。不列计划中的栈。

| 项 | 事实 |
|---|---|
| 语言 | Python 3.10+ |
| 主进程 | `python -m mac_edge` |
| 语音子进程 | `python -m mac_voice` |
| HTTP 客户端 | httpx |
| TTS | edge-tts |
| STT | aiohttp + 火山 SAUC WebSocket（mac_voice） |
| 麦 | sounddevice + numpy |
| PDF | pypdf、pymupdf |
| HTML→PDF | weasyprint（缺 Pango 时退 Chrome/Edge headless） |
| 视觉默认 provider | volcengine-python-sdk[ark] |
| 健康口 | stdlib HTTP（`scripts/health_server.py`） |
| 单测 | `unittest`，`mac/tests/` |

## 构建

| 工具 | 用途 |
|---|---|
| `build.sh` | 发版包装 → `outputs/`（必须含 `scripts/restart.sh`）；顺带尽量打进 `games/coin-catcher/dist` |
| `scripts/start.sh` | 目标机把依赖装进 `<runtime>/backend/data/.venv` |

无 Docker 作为一等部署路径。无根 `package.json`（小游戏在 `games/coin-catcher` 内自有前端构建）。本检出无 `.github/workflows`。

## 本仓库没有的东西

- 无 Brain 规划器、无集市 UI
- 无 Paddle / WhisperX / MediaPipe 引擎（在 sidecar）
- 无 iOS/Android 工程
- 无应用内发版 API
