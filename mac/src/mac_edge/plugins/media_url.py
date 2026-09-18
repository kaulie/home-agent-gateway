"""投屏/播放前的**媒体 URL 预检**：设备拉不到字节时，别让 DLNA「假装成功」。

背景：DLNA 是**盲发** —— ``SetAVTransportURI + Play`` 返回 200 只代表控制命令被接受，
真正拉字节的是电视/音箱自己。如果 img-server 没跑、文件被删、或 asset 授权失效，
现象就是「命令成功、设备毫无声音」，家里完全看不出为什么。

本模块在把 URL 交给设备**之前**由 Edge 自己取一次（``Range: bytes=0-0``，只要 1 字节；
img-server 不支持 HEAD —— 实测 501 —— 所以只能用 GET+Range）：

- 200 / 206 → 通过（顺便把 Content-Type / Content-Length 记进日志）
- 其它（404 / 403 / 5xx / 连不上 / 超时）→ 抛 ``MediaUrlError``：用户看到一句人话，
  具体 URL / 状态码 / 「检查 img-server 是否在跑」这类运维信息只进日志
- ``MAC_EDGE_MEDIA_PROBE=0`` 关掉（排障用）

注意范围：探针从 **Mac** 发起，能拦「提供文件的机器挂了 / 文件没了 / 授权失效」；
不能保证设备侧一定拉得到（网段隔离等），所以文案不承诺「必然出声」。
"""

from __future__ import annotations

import logging
import os
from typing import Callable

log = logging.getLogger("mac_edge.media_url")

ENV_DISABLE = "MAC_EDGE_MEDIA_PROBE"
DEFAULT_TIMEOUT_SEC = 5.0


class MediaUrlError(Exception):
    """媒体 URL 取不到（用户可读的失败）。"""


def probe_enabled() -> bool:
    raw = (os.environ.get(ENV_DISABLE) or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _default_fetcher(url: str, timeout_sec: float) -> tuple[int, str, str]:
    """默认探针：httpx GET + Range: bytes=0-0 → (status, content_type, content_length)。"""
    import httpx

    with httpx.Client(timeout=timeout_sec, follow_redirects=True) as client:
        resp = client.get(url, headers={"Range": "bytes=0-0"})
        return (
            int(resp.status_code),
            str(resp.headers.get("content-type") or ""),
            str(resp.headers.get("content-length") or ""),
        )


def verify_media_url(
    url: str,
    *,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    fetcher: Callable[[str], tuple[int, str, str]] | None = None,
    what: str = "媒体文件",
) -> None:
    """确认这个 URL 真能取到字节；失败抛 MediaUrlError（人话，细节进日志）。

    ``fetcher`` 只接收 url（便于单测注入）；``what`` 用于文案（如「音频」「图片」）。
    """
    target = (url or "").strip()
    if not target:
        raise MediaUrlError(f"{what}地址为空，没法交给电视播放。")
    if not probe_enabled():
        log.info("media probe disabled (%s=0) url=%s", ENV_DISABLE, target)
        return

    fetch = fetcher or (lambda u: _default_fetcher(u, timeout_sec))
    try:
        status, content_type, content_length = fetch(target)
    except Exception as e:  # noqa: BLE001 - 任何取数失败都算探针失败
        log.warning(
            "media probe failed url=%s error=%s: %s", target, type(e).__name__, e
        )
        raise MediaUrlError(
            f"{what}取不到（连接失败），电视会没声音 —— 确认提供文件的机器在线。"
        ) from e

    if status in (200, 206):
        log.info(
            "media probe ok url=%s status=%s type=%s length=%s",
            target,
            status,
            content_type or "-",
            content_length or "-",
        )
        return

    hint = ""
    if status in (401, 403):
        hint = "（授权/权限问题）"
    elif status == 404:
        hint = "（文件不在）"
    elif status >= 500:
        hint = "（提供文件的服务报错）"
    log.warning("media probe failed url=%s status=%s hint=%s", target, status, hint)
    raise MediaUrlError(f"{what}取不到（HTTP {status}）{hint}，电视会没声音。")
