"""运行期目录解析：代码目录 / 数据目录 / 库目录 / 日志目录（都可指到代码之外）。

- `config.mac_root()` —— `mac/` 代码目录（`MAC_EDGE_MAC_ROOT` 可覆盖）
- `config.log_dir()` —— 运行期日志目录（`MAC_EDGE_LOG_DIR` > `<mac>/logs`）
- `db_paths.data_dir()/db_dir()/db_file()` —— 数据目录 / SQLite 库目录
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mac_edge import config, db_paths


class MacRootTests(unittest.TestCase):
    def test_default_is_mac_dir(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAC_EDGE_MAC_ROOT", None)
            self.assertEqual(config.mac_root().name, "mac")

    def test_override(self) -> None:
        with mock.patch.dict(os.environ, {"MAC_EDGE_MAC_ROOT": "/tmp/mac-root-x"}):
            self.assertEqual(config.mac_root(), Path("/tmp/mac-root-x"))


class LogDirTests(unittest.TestCase):
    def test_default_is_mac_logs(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MAC_EDGE_LOG_DIR", None)
            self.assertEqual(config.log_dir(), config.mac_root() / "logs")

    def test_env_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MAC_EDGE_LOG_DIR": tmp}):
                self.assertEqual(config.log_dir(), Path(tmp))

    def test_intranet_ping_log_follows_log_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MAC_EDGE_LOG_DIR": tmp}):
                os.environ.pop("MAC_EDGE_INTRANET_PING_LOG", None)
                settings = config._load_intranet_ping(config.mac_root())
                self.assertEqual(
                    settings.log_path, Path(tmp) / "intranet_ping.log"
                )


class DbDirTests(unittest.TestCase):
    def test_db_dir_follows_data_dir_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"MAC_EDGE_DATA_DIR": tmp}, clear=False):
                os.environ.pop("MAC_EDGE_DB_DIR", None)
                self.assertEqual(db_paths.db_dir(), Path(tmp))
                self.assertEqual(
                    db_paths.db_file("ncm_songs.sqlite3"),
                    Path(tmp) / "ncm_songs.sqlite3",
                )

    def test_db_dir_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_dir = Path(tmp) / "database"
            with mock.patch.dict(os.environ, {"MAC_EDGE_DB_DIR": str(db_dir)}):
                self.assertEqual(
                    db_paths.db_file("ncm_songs.sqlite3"),
                    db_dir / "ncm_songs.sqlite3",
                )


if __name__ == "__main__":
    unittest.main()
