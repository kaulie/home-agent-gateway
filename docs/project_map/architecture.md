# 服务架构

## 进程边界

```
Brain :9527
        ▲  HTTP 客户端（登记 / 心跳 / 拉单 / 步状态 / Asset）
        │
  python -m mac_edge
        │
        ├─ marketplace_catalog.py → GET 集市 /api/v1/export
        ├─ capability_ads.py      广告 + 本机在线覆盖
        ├─ services.py            服务登记表（含 xiaodu.play 探测）
        ├─ executor.py            按 capability_id 派到 plugin
        ├─ plugins/*.py           设备 I/O
        ├─ mac_voice（子进程）    连续麦 + STT；voice ingest :8790
        └─ xiaodu TTS HTTP        默认 :8000（局域网拉流，不是健康口）

scripts/health_server.py :9528     ← 只给部署平台探活，不是 Edge API
```

不要把健康口做成「第二个 Edge HTTP 面」。Edge 本体没有 `/health`。

## 规划广告与心跳

1. `mac/src/mac_edge/marketplace_catalog.py` 拉 `HOME_AGENT_MARKETPLACE_URL`（默认 `http://127.0.0.1:4250`）的 `/api/v1/export`。
2. 心跳带本机在线覆盖；空字段用声明补齐。
3. **`decomposes_to` 是执行顺序**，不要按字母重排。

## 插件落点（摘录）

能力执行几乎都在 `mac/src/mac_edge/plugins/`。常见入口文件：

| 能力方向 | 文件 |
|---|---|
| 小度 TTS / 投 URL | `xiaodu_speaker.py`（`xiaodu.play` 另在 `services.py` 登记） |
| 网易云 | `netease_music.py` |
| 小米电视 / 锁 / 云 / 鱼缸 / 打印 | `xiaomi_*.py` |
| 指字客户端 | `point_to_character.py` → `:9189` |
| 发音客户端 | `pronunciation_assess.py` → `:9190` |
| 投屏 / Chromecast | `chromecast_display.py`、`xiaomi_tv_display.py` |
| PDF | `pdf_*.py` |
| 视觉 / 问答 | `vision_*.py`、`query_content.py` |
| 客厅灯 | `livingroom_light.py` |
| 相机 / 直播 | `gopro_camera.py`、`video_live_*.py` |

plugin **不知道** Asset 身份语义时，只传图片/音频字节给 sidecar。

## 同源但路径写死的仓内文件

`mac_edge` 若干路径用 `parents[N]` 相对仓库根：

| 路径 | 谁在用 |
|---|---|
| `server/mdns_service.py` | `agent.py` |
| `games/coin-catcher/**` | `game_host.py`（`dist/` 要能进发版包） |
| `plugins/voice-lamp-test/profiles/default.yaml` | `voice_test/profile.py` |
| `plugins/livingroom-ceiling-light/audio/**` | `livingroom_light.py` |

改这些目录层级必须同步改代码。

## 存储

| 用途 | 生产落点 |
|---|---|
| 非库数据（edge_id、录音、缓存） | `MAC_EDGE_DATA_DIR`（常 `/Users/gaolei/artifact-storage/home-agent-gateway`） |
| SQLite（`ncm_songs.sqlite3`） | `MAC_EDGE_DB_DIR`（常 `/Users/gaolei/database/home-agent-gateway`） |
| 运行期日志 | `MAC_EDGE_LOG_DIR` 或不设则跟数据目录；stdout 在 `<runtime>/backend/server.log` |

库路径优先级：`MAC_EDGE_NCM_SONGS_DB` > `MAC_EDGE_DB_DIR` > `MAC_EDGE_DATA_DIR` > `<mac>/data`。

## 外部依赖

| 依赖 | 默认 |
|---|---|
| Brain | `http://brain.local:9527` 一类（见 `config/endpoints.py`） |
| 集市 | `http://127.0.0.1:4250` |
| 指字 | `http://127.0.0.1:9189` |
| 发音 | `http://127.0.0.1:9190` |
| 部署平台 | `:4220` |
