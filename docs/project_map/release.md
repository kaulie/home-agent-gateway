# 发布细节

一次发布 = 部署平台对某个 git ref 跑仓库根 `build.sh`，得到 `outputs/`，再 rsync 到 runtime。

调用方只有：

- `POST :4220/api/deploy-notify {serviceId:"home-agent-gateway", ref}`
- 平台 `release.sh home-agent-gateway [ref]`

本仓库没有「本地一键上线」脚本。`outputs/` gitignore。`VERSION` / `COMMIT` / `GIT_REPO_URL` 由调用方写入。

## `build.sh` 约定

- cwd = 仓库根；`APP_VERSION` = 8 位短 hash。
- 必须产出 `outputs/`，且含 `scripts/restart.sh`。
- 产物：`outputs/{mac/**, config/**, scripts/*.sh, README.md, .gitignore}`，以及路径写死的 `server/mdns_service.py`、`games/`、`plugins/` 资源。
- 不进包：venv、`.env`、库文件、日志、`__pycache__`。
- Python 依赖由目标机 `start.sh` 装进 `backend/data/.venv`。
- 打包环境 PATH 可能没有 Homebrew：脚本会补 `/usr/local/bin` 与 `/opt/homebrew/bin`，否则 `games/coin-catcher/dist` 进不了包，下次部署会把电视小游戏删掉。

合入 `main` ≠ 已上线。
