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
| 数据库 | **代码 / 运行期数据之外**：`MAC_EDGE_DB_DIR=/Users/gaolei/database/home-agent-gateway`（Edge 只有一个库 `ncm_songs.sqlite3`，见 `mac/src/mac_edge/db_paths.py`） |
| venv | `<runtime>/backend/data/.venv`（部署保留，不用每次重装依赖） |

```ini
# <runtime>/backend/.env（含密钥，不入 git；模板见 mac/.env.example）
MAC_EDGE_DATA_DIR=/Users/gaolei/runtime/home-agent-gateway/backend/data
MAC_EDGE_DB_DIR=/Users/gaolei/database/home-agent-gateway
MAC_EDGE_HEALTH_PORT=9528
```

**库目录优先级**（`mac/src/mac_edge/db_paths.py`）：
`MAC_EDGE_NCM_SONGS_DB`（单库）> `MAC_EDGE_DB_DIR` > `MAC_EDGE_DATA_DIR` > `<mac>/data`。
不设 `MAC_EDGE_DB_DIR` 时行为与上游一致（库就在数据目录里）；录音 / 各能力缓存 / JSON 状态
仍按 `MAC_EDGE_DATA_DIR` 走，只有 **SQLite 库**被拆出去。

## 相对上游的改动（拆分时）

- 新增 `build.sh`、`scripts/{start,stop,restart}.sh`、`scripts/health_server.py`（部署系统要求 + 健康口）
- `mac/run_mac_edge.sh`：`MAC_EDGE_*` 默认值改成「已设置的 env 优先」（`${X:-默认}`），
  以便 runtime 目录用 `backend/` 布局启动；本地默认行为不变
- `mac/src/mac_edge/config.py`：`.env` 额外从 `<repo>/backend/.env` 加载（平台保留位，优先于 `mac/.env`）
- `.gitignore`：补 `outputs/`、`backend/`、平台写入的版本文件、`mac/{.venv,data,logs}`、`mac/src/data/`
- 清理上游误提交的本地库：`mac/src/data/{ncm_songs.sqlite3,ncm_songs.sqlite3-shm,ncm_songs.sqlite3-wal}`
  从 git 移除（SQLite 的 WAL/SHM 不该进仓，且每次跑测试都会脏工作树）；运行期按
  `MAC_EDGE_DATA_DIR`（默认 `mac/data`）生成，不依赖仓里的那份

## 随拆分一并搬入的上游同源文件（路径被代码写死）

`mac_edge` 有几处路径是**相对仓库根**写死的（`parents[N]`）。为保持「纯搬迁、零行为变化」，
这些上游文件也搬进了本仓：

| 路径 | 谁在用 | 说明 |
|------|--------|------|
| `server/mdns_service.py` | `mac_edge/agent.py`（`parents[3]/"server"`，按文件路径加载） | brain / edge 共用的 mDNS 发布器（纯标准库 + 可选 zeroconf）。brain 仓里也是同一份，两边同源 |
| `games/coin-catcher/**` | `mac_edge/plugins/game_host.py`（`parents[4]/"games"`） | `mac.game.host` 在电视上跑的小游戏。**`dist/` 是 vite 构建产物**（上游 .gitignore 忽略），部署时要 `npm ci && npm run build` 或从旧 checkout 拷一份 `dist/` |
| `plugins/voice-lamp-test/profiles/default.yaml` | `mac_edge/plugins/voice_test/profile.py`（`parents[5]/"plugins"`） | 语音台灯测试档位 |
| `plugins/livingroom-ceiling-light/audio/**` | `mac_edge/plugins/livingroom_light.py`（`parents[4]/"plugins"`） | 客厅顶灯开 / 关 / 唤醒提示音 |

`<repo>/data`、`<repo>/mac/data` 这类**数据**路径不在上面：运行期一律由 `MAC_EDGE_DATA_DIR`
指定（runtime 里 = `<runtime>/backend/data`），代码里的相对路径只是兜底默认值。

## 边界

- 本仓只承载 **Mac Edge（网关）**。Brain 在 `home-agent-brain`；iPhone / Android / Kindle / iPad 客户端在各自仓库。
- 仓内 `mac/` 这一层目录保留原名：`mac_edge/config.py` 用 `parents[3]` 定位仓根（读 `config/endpoints.py`），
  改目录层级需要同步改代码。

