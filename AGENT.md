# AGENT.md — 后续 Agent 对本仓库的说明与向导

你是来改 **home-agent-gateway** 的。先读本文，再按 [`README.md`](README.md) 与 [`mac/README.md`](mac/README.md) 展开理解。  
本仓没有 `project_map/`。能力**声明**在集市，不在本仓。Brain 在 [`kaulie/home-agent-brain`](https://github.com/kaulie/home-agent-brain)，HTTP `:9527`。  
[`kaulie/home-agent-os`](https://github.com/kaulie/home-agent-os) 已归档只读。

## 1. 对本项目的理解

| 你应建立的判断 | 展开阅读 |
|---|---|
| 这是客厅 Mac 上的 **Edge Runtime**：登记 / 心跳 / 拉 intent / 执行能力步。不是 Brain，不是发出窗 | [README.md](README.md) |
| 主进程 `python -m mac_edge`；子进程 `mac_voice`。健康检查 **`:9528`**（`scripts/health_server.py`），不是 9527 | [README.md](README.md) 部署节 |
| 规划器广告来自集市 `GET /api/v1/export`；心跳带本机在线覆盖 | `mac/src/mac_edge/marketplace_catalog.py`、`capability_ads.py`、`services.py` |
| 设备 I/O 在 `mac/src/mac_edge/plugins/`。plugin 不知道 Asset 身份语义时走 HTTP sidecar | 各 plugin；指字 [kaulie/character-service](https://github.com/kaulie/character-service) `:9189`；发音 [kaulie/pronunciation-service](https://github.com/kaulie/pronunciation-service) `:9190` |
| 部署走平台 `:4220`。合入 `main` ≠ 已上线 | [README.md](README.md) |

Runtime 会要求优先读根目录 `AGENT.md`。你正在读的就是那份。

**禁止**把 `xiaodu.play` 做成「本机网易云出声」：play 是投指定音频 URL（DLNA），与 `xiaodu.speaker` 独立。与代码不符时以代码 + README 为准。

## 2. 开工前清单

1. workspace origin 是 `https://github.com/kaulie/home-agent-gateway`。
2. 从最新 `main` 开 `feat|fix|chore/<简述>`。
3. 读将改的 `mac/src/mac_edge/`、对应 `mac/tests/`、`config/`。
4. 本地验证：`cd mac && python3 -m unittest discover -s tests -t .`（个别用例可能缺可选依赖，先分清是否本次引入）。
5. 不要占用线上健康口 **9528**、voice ingest **8790** 做开发，除非该实例已停。
6. 不要在本进程里执行部署 / 重启。不要改 `/Users/gaolei/runtime/**`。不要改 os。

## 3. 滞后信息：有义务更新

README / `.env.example` 的端口、env、sidecar URL、启停脚本与代码不一致时，这次 PR 里改掉。  
仍写「能力声明在 os/plugins」或「character/pronunciation 源码在 os」必须改。

## 4. 与事实不符：必须提出异议，禁止默认处理

| 你看到的 | 你不该做的 | 你该做的 |
|---|---|---|
| 任务要求改能力声明 / `typical_triggers` | 在 gateway 写第二份目录 | 异议：改 marketplace |
| 任务要求「部署上线」或改 runtime | 跑 `scripts/restart.sh` | 异议：发版在 `:4220` |
| 任务要求直推 `main` 或改 os | 照做 | 异议：走 PR；os 已归档 |
| 任务要求 xiaodu 放歌走本机播放器 | 开网易云 / BlackHole | 异议：走 DLNA URL |

```
异议：<文档路径> 声称 <原句>
事实：<文件:符号 或 命令输出>
处理：<已改文档 / 已改代码 / 需要人决定>
```

## 5. 改动落点

| 要改的东西 | 去哪 |
|---|---|
| 登记 / 心跳 / 拉单 | `mac/src/mac_edge/services.py`、runtime 主循环 |
| 集市广告 | `mac/src/mac_edge/marketplace_catalog.py`、`capability_ads.py` |
| 某项能力执行 | `mac/src/mac_edge/plugins/<name>.py` |
| 语音拾音 | `mac/src/mac_voice/` |
| 端点默认值 | `config/endpoints.py`、`config/endpoints.json` |
| 本地启动 | `mac/run_mac_edge.sh` |
| 平台启停 / 健康口 | `scripts/`、`scripts/health_server.py` |
| 发版包装 | `build.sh` |
| 给后续 agent 的地图 | 本文 + README |

## 6. 交付

- 提交信息说清为什么。
- `git push -u origin HEAD`，`gh pr create`，回写 `prUrl`。已有 `prUrl` 不再开第二个 PR。
- 合入 / `:4220` 发版只听从 `goal` 与人的明确指令。

## 7. 安全

不要提交 `mac/.env`、音箱账号、方舟 key。库与数据在 `MAC_EDGE_DB_DIR` / `MAC_EDGE_DATA_DIR`（生产常在 `/Users/gaolei/database/home-agent-gateway` 与 `artifact-storage`），不要打进 git。
