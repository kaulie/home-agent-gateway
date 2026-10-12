# project_map — home-agent-gateway 项目地图

本目录按**运行事实**说明本仓库，不是概念词典。

| 文档 | 维度 |
|---|---|
| [positioning.md](positioning.md) | 项目定位：解决什么、不解决什么、和周边怎么分工 |
| [architecture.md](architecture.md) | 服务架构：进程、心跳、插件、sidecar、存储 |
| [tech-stack.md](tech-stack.md) | 技术栈 |
| [deployment.md](deployment.md) | 部署：谁部署、健康口、运行目录、数据落点 |
| [release.md](release.md) | 发布：`build.sh` 产物、契约 |
| [development.md](development.md) | 开发：工作区、分支、测试、提交边界 |

根目录 [`AGENT.md`](../../AGENT.md) 是后续 agent 的入口：理解以本目录为准，滞后必须更新，与事实不符必须提出异议。

协议与插件说明仍在 [`README.md`](../../README.md)、[`mac/README.md`](../../mac/README.md)。那些文件回答「怎么启动 / 某能力怎么跑」；`docs/project_map/` 回答「这个仓库现在怎么改」。

## 怎么读

1. 先读 [positioning.md](positioning.md) 和 [architecture.md](architecture.md)，再按任务去对应维度。
2. 动手前对照代码：主循环与登记在 `mac/src/mac_edge/`；能力执行在 `mac/src/mac_edge/plugins/`；健康口在 `scripts/health_server.py`。
3. 发现本目录或 README 与代码不一致时，按 [`AGENT.md`](../../AGENT.md) 处理，不要默认文档赢。

## 本轮已核对的异议（2026-10-12）

1. **能力声明不在本仓。** 广告来自集市 `GET /api/v1/export`。不要在 gateway 再写一份 `typical_triggers` 目录。
2. **`xiaodu.play` 没有独立 `play.py`。** 投指定音频 URL（DLNA / AVTransport）写在 `mac/src/mac_edge/services.py` + `xiaodu_speaker.py` 的 play 路径，与 `xiaodu.speaker`（本机 TTS 出声）独立。不要做成「本机网易云出声」。
3. **健康口是 `:9528`，不是 Brain 的 9527。** Edge 本体没有 `/health`；平台探活靠 `scripts/health_server.py`。
4. **指字 / 发音源码不在本仓。** HTTP sidecar 分别是 [character-service](https://github.com/kaulie/character-service) `:9189`、[pronunciation-service](https://github.com/kaulie/pronunciation-service) `:9190`。
5. **[`kaulie/home-agent-os`](https://github.com/kaulie/home-agent-os) 已归档。** 不要往 os 回写 Mac Edge。
6. **本检出无 `.github/workflows`。** 合入前至少本地跑 `mac/tests`。

后续 agent 若发现上述条目被新代码推翻，删除或改写，不要累积过期异议。
