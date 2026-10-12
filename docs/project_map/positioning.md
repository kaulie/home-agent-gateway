# 项目定位

## 一句话

home-agent-gateway 是客厅 Mac 上的 **Edge Runtime**：向 Brain 登记 / 心跳 / 拉 intent，并在本机执行设备 I/O 能力步。它不是 Brain，不是发出窗，也不是能力声明权威。

仓库：[`https://github.com/kaulie/home-agent-gateway`](https://github.com/kaulie/home-agent-gateway)  
平台健康口：`9528`  
平台 serviceId：`home-agent-gateway`（`build.sh` 注释）

## 它要解决什么

```
Brain :9527
   ↑  登记 / 心跳 / 拉已规划单 / 回报步状态 / 上传 Asset
   │
python -m mac_edge     ← 本仓主进程
   ├─ plugins/*        电视 / 灯 / 小度 / PDF / 相机 / 识曲 …
   ├─ mac_voice        连续麦 + STT（子进程）
   └─ HTTP sidecar     指字 :9189、发音 :9190（独立仓，本仓只当客户端）
```

- **执行在 Edge**：`display.*`、`music.*`、`xiaomi.*`、`reading.*`、`vision.*` 等落地在 `mac/src/mac_edge/plugins/`。
- **声明在集市**：触发语 / schema / decomposes_to 以 marketplace export 为准。
- **规划在 Brain**：本进程不写 execution_plan。

## 它不是什么

| 不是 | 谁才是 |
|---|---|
| Brain 控制面 / 规划器 | [`home-agent-brain`](https://github.com/kaulie/home-agent-brain) `:9527` |
| 能力声明目录 | [`home-agent-capabilty-marketplace`](https://github.com/kaulie/home-agent-capabilty-marketplace) `:4250` |
| 指字引擎 | [`character-service`](https://github.com/kaulie/character-service) `:9189` |
| 发音打分引擎 | [`pronunciation-service`](https://github.com/kaulie/pronunciation-service) `:9190` |
| 发出窗 | [`home-agent-ios`](https://github.com/kaulie/home-agent-ios) / [`home-agent-android`](https://github.com/kaulie/home-agent-android) |
| 部署平台 | [`agent-control-plane-deployment`](https://github.com/kaulie/agent-control-plane-deployment) `:4220` |
| 已冻结的单体 os | [`home-agent-os`](https://github.com/kaulie/home-agent-os)（归档只读） |

本仓库**没有**「对本机 runtime 发起部署」的 HTTP 入口。上线走 `:4220`。

## 当前形态

- 主进程 `python -m mac_edge`（`PYTHONPATH=<runtime>/mac/src`）
- 子进程 `python -m mac_voice`
- 健康检查独立小服务 `scripts/health_server.py` `:9528`
- 发版包装 `build.sh` + `scripts/{start,stop,restart}.sh`
- 仓内保留若干相对仓库根写死的上游文件（`server/mdns_service.py`、`games/coin-catcher/`、部分 `plugins/` 资源），改目录层级要同步改 `parents[N]`
