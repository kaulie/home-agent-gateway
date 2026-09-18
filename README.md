# home-agent-gateway

家庭 Agent 的**代理网关**：客厅 Mac 上的 Edge Runtime（Brain 侧客户端）。
对接 Brain 做 **注册 / 心跳 / 轮询 intent / 执行能力步**；`display.*`、`music.*`、`xiaomi.*`、
`reading.*`、`vision.*` 等能力都在这里落地（详见 [`mac/README.md`](mac/README.md)）。

## 来源

代码自 [`kaulie/home-agent-os`](https://github.com/kaulie/home-agent-os) 拆分而来
（源 commit `37d9537c` 的 `mac/` 与 `config/`，**纯搬迁、未改逻辑**，另加部署脚本，
见下「相对上游的改动」）。Brain 控制面在独立仓库
[`kaulie/home-agent-brain`](https://github.com/kaulie/home-agent-brain)，两者通过 HTTP
（Brain `:9527`）通信。

```
mac/                     Mac Edge 源码（本仓主内容）
├── src/mac_edge/         Edge 主进程：注册 / 心跳 / intent 轮询 / 能力插件
├── src/mac_voice/        连续麦克风 + STT（由 mac_edge 的 voice supervisor 拉起）
├── tests/                单测
├── sql/                  本地 ncm 歌库迁移
├── deploy/               home-server 角色的部署脚本
├── run_mac_edge.sh       本地/开发前台启动（env 可覆盖）
└── stop_mac_edge.sh      本地/开发停止
config/                  仓内端点默认值（endpoints.py / endpoints.json）
build.sh                 打包（部署系统要求）→ outputs/
scripts/                 部署系统要求的启停脚本 + 健康检查小服务
```

## 运行

### 本地 / 开发（前台）

```bash
cd mac
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
bash run_mac_edge.sh          # 前台；env 可用 MAC_EDGE_* 覆盖
bash stop_mac_edge.sh
```

### runtime（部署系统托管，`/Users/gaolei/runtime/home-agent-gateway`）

```bash
bash scripts/start.sh     # 或 scripts/restart.sh / scripts/stop.sh
curl 127.0.0.1:9528/health
```

## 部署（agent-control-plane-deployment 规范）

与 `home-agent-brain` 同一套约定：仓库根 `build.sh` 产出 `outputs/`（必须含 `scripts/restart.sh`）；
平台部署是 `rsync -a --delete --filter='P backend/{.env,data/,runtime.pid,server.log,.watchdog-paused}'
--exclude='.git/'`，**runtime 目录里只有 `backend/` 那几项与 `.git/` 能活过部署**。

| 项 | 值 |
|----|-----|
| 进程 | `python -m mac_edge`（`PYTHONPATH=<runtime>/mac/src`），子进程 `python -m mac_voice` |
| 监听 | 8790（voice stream）· 8000（小度 TTS 拉流）· **9528（健康检查，由 `scripts/health_server.py` 提供）** |
| 契约 | `startCmd/stopCmd/restartCmd = bash scripts/{start,stop,restart}.sh`；`port=9528`；`healthUrl=http://127.0.0.1:9528/health` |
| 运行期文件 | `<runtime>/backend/{.env, data/, runtime.pid, server.log}` —— `data/` 同时是 Edge 的数据目录（`MAC_EDGE_DATA_DIR`） |
| venv | `<runtime>/backend/data/.venv`（部署保留，不用每次重装依赖） |

```ini
# <runtime>/backend/.env（含密钥，不入 git；模板见 mac/.env.example）
MAC_EDGE_DATA_DIR=/Users/gaolei/runtime/home-agent-gateway/backend/data
MAC_EDGE_HEALTH_PORT=9528
```

## 相对上游的改动（拆分时）

- 新增 `build.sh`、`scripts/{start,stop,restart}.sh`、`scripts/health_server.py`（部署系统要求 + 健康口）
- `mac/run_mac_edge.sh`：`MAC_EDGE_*` 默认值改成「已设置的 env 优先」（`${X:-默认}`），
  以便 runtime 目录用 `backend/` 布局启动；本地默认行为不变
- `mac/src/mac_edge/config.py`：`.env` 额外从 `<repo>/backend/.env` 加载（平台保留位，优先于 `mac/.env`）
- `.gitignore`：补 `outputs/`、`backend/`、平台写入的版本文件

## 边界

- 本仓只承载 **Mac Edge（网关）**。Brain 在 `home-agent-brain`；iPhone / Android / Kindle / iPad 客户端在各自仓库。
- 仓内 `mac/` 这一层目录保留原名：`mac_edge/config.py` 用 `parents[3]` 定位仓根（读 `config/endpoints.py`），
  改目录层级需要同步改代码。

