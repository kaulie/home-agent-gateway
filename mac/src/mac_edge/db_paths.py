"""Edge 的 **SQLite 库目录**（把「数据库」从代码/运行期数据里拆出来）。

Edge 只有一个 SQLite 库：`ncm_songs.sqlite3`（本地 ncm 歌库/播放/录音元数据，见
`ncm_songs/store.py`；契约 `docs/mac-ncm-songs-db.md`）。运行期数据（录音、缓存、JSON 状态）
仍归 `MAC_EDGE_DATA_DIR`，本模块只管库文件放哪。

优先级（与 brain 的 `server/data_paths.py` 同一套路）：

    <单库覆盖 MAC_EDGE_NCM_SONGS_DB>  >  MAC_EDGE_DB_DIR  >  MAC_EDGE_DATA_DIR  >  <mac>/data

本机生产：`MAC_EDGE_DB_DIR=/Users/gaolei/database/home-agent-gateway`（写在
`<runtime>/backend/.env`，平台部署保留 `backend/` → 库不会被 `--delete` 碰到）。
"""

from __future__ import annotations

import os
from pathlib import Path


def _project_data_dir() -> Path:
    # src/mac_edge/db_paths.py → parents[2] = mac/
    return Path(__file__).resolve().parents[2] / "data"


def data_dir() -> Path:
    """运行期数据目录（`MAC_EDGE_DATA_DIR` 优先，否则 `<mac>/data`）。"""
    raw = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return _project_data_dir()


def db_dir() -> Path:
    """SQLite 库目录：`MAC_EDGE_DB_DIR` 优先，否则跟数据目录走（历史行为）。"""
    raw = (os.environ.get("MAC_EDGE_DB_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return data_dir()


# 单库覆盖（优先级最高）：库名 → 环境变量
_SINGLE_DB_ENV: dict[str, str] = {
    "ncm_songs.sqlite3": "MAC_EDGE_NCM_SONGS_DB",
}


def db_file(name: str) -> Path:
    """库目录下的一个库文件路径（不建目录，由 open 方 mkdir）。"""
    key = str(name)
    env_key = _SINGLE_DB_ENV.get(key)
    if env_key:
        raw = (os.environ.get(env_key) or "").strip()
        if raw:
            return Path(raw).expanduser()
    return db_dir() / key
