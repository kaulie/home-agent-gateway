"""Read capability declarations from the marketplace API.

Marketplace is the declaration authority. Gateway only GETs
`/api/v1/export`; it never writes the catalog back.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

log = logging.getLogger("mac_edge.marketplace_catalog")

DEFAULT_URL = "http://127.0.0.1:4250"
ENV_URL = "HOME_AGENT_MARKETPLACE_URL"
ENV_CATALOG = "HOME_AGENT_MARKETPLACE_CATALOG"
ENV_CACHE = "HOME_AGENT_MARKETPLACE_CACHE"
ENV_TTL = "HOME_AGENT_MARKETPLACE_TTL_SEC"
DEFAULT_TTL_SEC = 60.0
FETCH_TIMEOUT_SEC = 3.0

VALID_KINDS = frozenset({"input", "action", "output", "system"})
VALID_COMPOSITIONS = frozenset({"atomic", "composite"})

_lock = threading.Lock()
_ads: dict[str, dict[str, Any]] | None = None
_ads_at = 0.0
_pinned = False


def marketplace_base_url() -> str:
    return (
        os.environ.get(ENV_URL) or os.environ.get("MARKETPLACE_URL") or DEFAULT_URL
    ).strip().rstrip("/") or DEFAULT_URL


def ttl_sec() -> float:
    raw = (os.environ.get(ENV_TTL) or "").strip()
    if not raw:
        return DEFAULT_TTL_SEC
    try:
        return max(1.0, float(raw))
    except ValueError:
        return DEFAULT_TTL_SEC


def _str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _pick(row: dict[str, Any], name: str) -> Any:
    definition = row.get("definition") if isinstance(row.get("definition"), dict) else {}
    if name in row and row[name] not in (None, ""):
        return row[name]
    return definition.get(name)


def ad_from_capability(row: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    cid = str(row.get("capability_id") or row.get("capabilityId") or row.get("id") or "").strip()
    if not cid:
        return None
    kind = str(_pick(row, "kind") or "").strip().lower()
    composition = str(_pick(row, "composition") or "atomic").strip().lower() or "atomic"
    if composition not in VALID_COMPOSITIONS:
        composition = "atomic"
    ad: dict[str, Any] = {
        "kind": kind if kind in VALID_KINDS else "",
        "composition": composition,
        "role": str(_pick(row, "role") or "").strip(),
        "planner_recognize": str(_pick(row, "planner_recognize") or "").strip(),
        "typical_triggers": _str_list(_pick(row, "typical_triggers")),
        "do_not_dispatch": _str_list(_pick(row, "do_not_dispatch")),
    }
    decomposes = _str_list(_pick(row, "decomposes_to"))
    prefer = str(_pick(row, "prefer_when") or "").strip()
    if decomposes:
        ad["decomposes_to"] = decomposes
    if prefer:
        ad["prefer_when"] = prefer
    return ad


def ads_from_payload(payload: Any) -> dict[str, dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("ads"), dict):
        out: dict[str, dict[str, Any]] = {}
        for key, value in payload["ads"].items():
            cid = str(key or "").strip()
            if cid and isinstance(value, dict):
                out[cid] = dict(value)
        return out
    rows: list[Any]
    if isinstance(payload, dict):
        rows = payload.get("capabilities") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ad = ad_from_capability(row)
        cid = str(row.get("capability_id") or "").strip()
        if ad and cid:
            out[cid] = ad
    return out


def _cache_path() -> Path | None:
    raw = (os.environ.get(ENV_CACHE) or "").strip()
    if raw:
        return Path(raw).expanduser()
    data = (os.environ.get("MAC_EDGE_DATA_DIR") or "").strip()
    if data:
        return Path(data).expanduser() / "marketplace-ads.json"
    return None


def _read_cache() -> dict[str, dict[str, Any]]:
    path = _cache_path()
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return ads_from_payload(payload)


def _write_cache(ads: dict[str, dict[str, Any]]) -> None:
    path = _cache_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"ads": ads, "fetched_at": int(time.time())}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        log.warning("marketplace ads cache write failed path=%s", path, exc_info=True)


def _load_file_catalog() -> dict[str, dict[str, Any]]:
    raw = (os.environ.get(ENV_CATALOG) or "").strip()
    if not raw:
        return {}
    path = Path(raw).expanduser()
    if not path.is_file():
        return {}
    try:
        return ads_from_payload(json.loads(path.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        log.warning("marketplace catalog file unreadable path=%s", path, exc_info=True)
        return {}


def _fetch_http() -> dict[str, dict[str, Any]]:
    url = marketplace_base_url() + "/api/v1/export"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SEC) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return ads_from_payload(payload)


def pin_ads(ads: dict[str, dict[str, Any]] | None) -> None:
    """Test hook: pin an in-memory catalog (None = unpin)."""
    global _ads, _ads_at, _pinned
    with _lock:
        if ads is None:
            _ads = None
            _ads_at = 0.0
            _pinned = False
            return
        _ads = {str(k): dict(v) for k, v in ads.items() if str(k).strip()}
        _ads_at = time.monotonic()
        _pinned = True


def reset_ads() -> None:
    pin_ads(None)


def refresh_ads(*, force: bool = False) -> dict[str, dict[str, Any]]:
    global _ads, _ads_at
    with _lock:
        if _pinned and _ads is not None:
            return _ads
        now = time.monotonic()
        if not force and _ads is not None and (now - _ads_at) < ttl_sec():
            return _ads
        fetched = _load_file_catalog()
        source = "file" if fetched else ""
        if not fetched:
            try:
                fetched = _fetch_http()
                source = "http"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                log.warning("marketplace ads fetch failed: %s", exc)
                fetched = {}
        if fetched:
            _ads = fetched
            _ads_at = now
            if source == "http":
                _write_cache(fetched)
            log.info("marketplace ads loaded source=%s count=%s", source or "cache", len(fetched))
            return _ads
        cached = _read_cache()
        if cached:
            _ads = cached
            _ads_at = now
            log.warning("marketplace ads using disk cache count=%s", len(cached))
            return _ads
        if _ads is not None:
            return _ads
        _ads = {}
        _ads_at = now
        return _ads


def current_ads() -> dict[str, dict[str, Any]]:
    return refresh_ads()


class AdsView(Mapping[str, dict[str, Any]]):
    """dict-like view of the marketplace-backed planner ads."""

    def _data(self) -> dict[str, dict[str, Any]]:
        return refresh_ads()

    def __getitem__(self, key: str) -> dict[str, Any]:
        return self._data()[key]

    def __iter__(self):
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return self._data().get(key, default)

    def items(self):
        return self._data().items()

    def keys(self):
        return self._data().keys()

    def values(self):
        return self._data().values()


def overlay_service_ads(svc: dict[str, Any], *, preserve: frozenset[str] | None = None) -> dict[str, Any]:
    """Refresh one heartbeat service's planner fields from marketplace."""
    keep = preserve or frozenset()
    out = dict(svc)
    caps: list[dict[str, Any]] = []
    ads = current_ads()
    for cap in svc.get("capabilities") or []:
        if not isinstance(cap, dict):
            continue
        cid = str(cap.get("capability_id") or "").strip()
        merged = dict(cap)
        ad = ads.get(cid) or {}
        if ad:
            for key in (
                "kind",
                "composition",
                "role",
                "planner_recognize",
                "typical_triggers",
                "do_not_dispatch",
                "decomposes_to",
                "prefer_when",
            ):
                if key in keep and merged.get(key) not in (None, "", []):
                    continue
                val = ad.get(key)
                if val not in (None, "", []):
                    merged[key] = list(val) if isinstance(val, list) else val
        caps.append(merged)
    out["capabilities"] = caps
    return out
