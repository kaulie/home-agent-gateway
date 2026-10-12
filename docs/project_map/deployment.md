# 部署细节

## 谁负责部署

部署**只**由部署平台完成：[`agent-control-plane-deployment`](https://github.com/kaulie/agent-control-plane-deployment)，本机 `:4220`。

平台从 GitHub ref 调本仓 `build.sh`，得到 `outputs/`，rsync 到 runtime，执行 `scripts/restart.sh`。

- **禁止**在 agent 进程里同步跑 deploy / restart（会杀掉正在跑命令的 gateway 自身）。
- **禁止**手改 `/Users/gaolei/runtime/**`。

```bash
curl -sS -X POST http://127.0.0.1:4220/api/deploy-notify \
  -H 'content-type: application/json' \
  -d '{"serviceId":"home-agent-gateway","ref":"main"}'
```

## 端口与探活

| 口 | 谁听 | 用途 |
|---|---|---|
| **9528** | `scripts/health_server.py` | 平台契约 `port` / `healthUrl`；仅 `127.0.0.1` |
| 8790 | mac_voice | voice stream ingest |
| 8000 | xiaodu TTS 拉流 | 局域网设备来拉 MP3，不是探活 |

契约：`healthUrl=http://127.0.0.1:9528/health`。心跳超时**不**让平台把 Edge 判死。

**本机开发不要占用 9528 / 8790**，除非确认线上实例已停。

## 运行目录

```
<runtime>/                          平台 runtimeDir（本仓 clone）
  scripts/{start,stop,restart}.sh
  mac/                              源码
  config/                           端点默认值
  backend/.env                      平台 rsync --delete 时保留
  backend/runtime.pid
  backend/server.log
  backend/data/.venv                依赖（部署保留，尽量不每次重装）
```

数据与库**不在** runtime 代码树：见 [architecture.md](architecture.md) 存储节。`start.sh` 会解析 `MAC_EDGE_*` 并 mkdir。

平台 rsync `--delete` 时，runtime 里只有 `backend/` 那几项与 `.git/` 能活过部署。
