#!/usr/bin/env python3
"""Mac Edge 健康检查小服务（部署平台探活用）。

Edge 本体没有 `/health` 路由（它是心跳客户端，向外连 Brain 的 :9527），而部署系统要求
契约里的 `healthUrl` 返回 2xx。所以这里起一个**只读**的 stdlib HTTP 服务：

    GET /health → 200 {"ok": true, "service": "mac-edge", ...}   进程活着
                  503 {"ok": false, ...}                          进程没了

判活依据（不碰 Edge 代码）：
  1. `<runtime>/backend/runtime.pid` 里的 pid 还活着（`os.kill(pid, 0)`）；
  2. 顺带从数据目录读 `edge_id.json`、从日志尾部抓最后一条心跳行，回报“心跳多久之前”，
     便于人看（心跳超时**不**判死：麦克风/网络抖动不该让平台重启 Edge）。

环境变量：`MAC_EDGE_HEALTH_PORT`（默认 9528）、`RUNTIME_DIR`（默认脚本的上级目录）。
仅监听 127.0.0.1。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_RUNTIME = Path(os.environ.get("RUNTIME_DIR") or _HERE.parent).expanduser()
_PORT = int(os.environ.get("MAC_EDGE_HEALTH_PORT") or 9528)
_BACKEND = _RUNTIME / "backend"
_PID_FILE = _BACKEND / "runtime.pid"
_LOG_FILE = _BACKEND / "server.log"
_DATA_DIR = _BACKEND / "data"

_HEARTBEAT_RE = re.compile(r"heartbeat OK(?P<rest>.*)$")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _edge_pid() -> int:
    try:
        return int((_PID_FILE.read_text(encoding="utf-8") or "").strip() or 0)
    except (OSError, ValueError):
        return 0


def _edge_id() -> str:
    try:
        raw = json.loads((_DATA_DIR / "edge_id.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if isinstance(raw, dict):
        return str(raw.get("edge_id") or raw.get("id") or "")
    return ""


def _last_heartbeat_age_sec() -> float | None:
    """日志尾部最后一条 `heartbeat OK` 距今秒数；读不到就 None。"""
    try:
        size = _LOG_FILE.stat().st_size
        with _LOG_FILE.open("rb") as fh:
            fh.seek(max(0, size - 65536))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    stamp: float | None = None
    for line in tail.splitlines():
        if "heartbeat OK" not in line:
            continue
        m = re.match(r"^(?P<ts>\d{2}:\d{2}:\d{2})\b", line.strip())
        if not m:
            continue
        try:
            hh, mm, ss = (int(x) for x in m.group("ts").split(":"))
        except ValueError:
            continue
        now = time.localtime()
        same_day = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, hh, mm, ss, 0, 0, -1))
        stamp = max(stamp or 0.0, same_day)
    if stamp is None:
        return None
    return max(0.0, time.time() - stamp)


class _Handler(BaseHTTPRequestHandler):
    server_version = "mac-edge-health/1"

    def log_message(self, fmt: str, *args: object) -> None:  # 静音
        return

    def _payload(self) -> tuple[int, dict]:
        pid = _edge_pid()
        alive = _pid_alive(pid)
        age = _last_heartbeat_age_sec()
        body = {
            "ok": alive,
            "service": "mac-edge",
            "runtime_dir": str(_RUNTIME),
            "pid": pid or None,
            "edge_id": _edge_id() or None,
            "last_heartbeat_age_sec": None if age is None else round(age, 1),
            "data_dir": str(_DATA_DIR),
            "checked_at": round(time.time(), 3),
        }
        return (200 if alive else 503), body

    def _respond(self, with_body: bool) -> None:
        code, body = self._payload()
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if with_body:
            self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "/").split("?", 1)[0].rstrip("/") or "/"
        if path in ("/health", "/healthz", "/"):
            self._respond(with_body=True)
            return
        self.send_error(404)

    def do_HEAD(self) -> None:  # noqa: N802
        path = (self.path or "/").split("?", 1)[0].rstrip("/") or "/"
        if path in ("/health", "/healthz", "/"):
            self._respond(with_body=False)
            return
        self.send_error(404)


def main() -> int:
    host = "127.0.0.1"
    try:
        httpd = ThreadingHTTPServer((host, _PORT), _Handler)
    except OSError as exc:
        print(f"[health] bind {host}:{_PORT} failed: {exc}", file=sys.stderr, flush=True)
        return 1
    print(
        f"[health] mac-edge health on http://{host}:{_PORT}/health "
        f"(runtime={_RUNTIME} pid_file={_PID_FILE})",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
