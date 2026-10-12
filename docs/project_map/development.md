# 开发流程

## 工作区

只在 task 简报给出的 workspace 里开发。origin 只能是 `https://github.com/kaulie/home-agent-gateway`。

- **永远不要**改 `/Users/gaolei/runtime/**`。
- 不要改已归档的 home-agent-os。
- 不要改 marketplace / brain，除非任务点名（声明在集市，规划在 Brain）。

## 分支

从最新 `origin/main` 开短命分支，PR 回 `main`。简报有 task id 则写进分支名。禁止直推 `main`、禁止 force push `main`。

任务已有 `prUrl` 时不要再开第二个 PR。合入 / 部署只听从 `goal` 与人的明确指令。

## 改代码时的边界

1. 先读 [`../../AGENT.md`](../../AGENT.md) 与本目录。
2. 能力执行改 `mac/src/mac_edge/plugins/<name>.py`；登记/心跳改 `services.py`。
3. 能力触发语 / schema 改集市，本仓只消费 export。
4. 不要把 `xiaodu.play` 做成「本机播放器出声」。
5. 改 `parents[N]` 相对路径时，同步改仓内同源文件布局。
6. 不要在本仓库加「发起部署」的接口。

## 测试

```bash
cd mac && python3 -m unittest discover -s tests -t .
```

个别用例可能缺可选依赖或本机设备；失败先分清是否本次引入。

## 提交与敏感物

不要提交 `mac/.env`、音箱账号、方舟 key、sqlite 库、录音、`backend/`。
