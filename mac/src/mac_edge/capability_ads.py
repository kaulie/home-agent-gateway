"""Planner-facing capability ads — sourced from the marketplace API.

Wire fields (heartbeat / CAPABILITY_REGISTRY):
  kind, composition, role, planner_recognize, typical_triggers[], do_not_dispatch[]
plus input_schema / output_schema (filled by services.py).
Composite rows also carry decomposes_to[] and prefer_when.

`kind` is system placement: input | action | output | system.
`composition` is orthogonal: atomic | composite. Missing → atomic.
`system` = Brain-side catalog / inventory (not bound to a Runtime).
`description` is not the planning contract.

Declaration text lives in home-agent-capabilty-marketplace. This module only reads it.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from mac_edge.marketplace_catalog import AdsView, current_ads

log = logging.getLogger("mac_edge.capability_ads")

Kind = Literal["input", "action", "output", "system"]
VALID_KINDS = frozenset({"input", "action", "output", "system"})
Composition = Literal["atomic", "composite"]
VALID_COMPOSITIONS = frozenset({"atomic", "composite"})

CAPTURE_AND_UPLOAD_PREFER_WHEN = (
    "拍照后还有后续动作要消费这张照片（给人看、变成 Asset、vision、投屏）时，"
    "优先本能力，不要把 decomposes_to 拆成多步"
)
POINT_TO_CHARACTER_PREFER_WHEN = (
    "要认手指指的那个字时，优先本能力，"
    "不要把 decomposes_to 拆成多步，也不要用整页 OCR"
)

_EMPTY_AD: dict[str, Any] = {
    "kind": "",
    "role": "",
    "planner_recognize": "",
    "typical_triggers": [],
    "do_not_dispatch": [],
    "composition": "atomic",
}


def _ad(
    *,
    kind: Kind,
    role: str,
    planner_recognize: str,
    typical_triggers: list[str],
    do_not_dispatch: list[str],
    composition: Composition = "atomic",
    decomposes_to: list[str] | None = None,
    prefer_when: str | None = None,
) -> dict[str, Any]:
    k = str(kind or "").strip().lower()
    if k not in VALID_KINDS:
        raise ValueError(f"invalid capability kind={kind!r}; expected input|action|output|system")
    comp = str(composition or "atomic").strip().lower()
    if comp not in VALID_COMPOSITIONS:
        raise ValueError(
            f"invalid capability composition={composition!r}; expected atomic|composite"
        )
    out: dict[str, Any] = {
        "kind": k,
        "role": role,
        "planner_recognize": planner_recognize,
        "typical_triggers": list(typical_triggers),
        "do_not_dispatch": list(do_not_dispatch),
        "composition": comp,
    }
    if comp == "composite":
        parts = [str(x).strip() for x in (decomposes_to or []) if str(x).strip()]
        if not parts:
            raise ValueError("composite capability requires non-empty decomposes_to")
        when = str(prefer_when or "").strip()
        if not when:
            raise ValueError("composite capability requires prefer_when")
        out["decomposes_to"] = parts
        out["prefer_when"] = when
    return out


ADS = AdsView()


def named_appliance_overrides(
    appliance_name: str,
    *,
    generic_triggers: list[str] | None = None,
) -> dict[str, Any]:
    """Planner fields that distinguish one bound appliance from another instance.

    Named triggers come first. Generic triggers (if any) are extras after the
    named ones so two edges never advertise identical generic-only ads.
    """
    name = str(appliance_name or "").strip()
    if not name:
        return {}
    named = [
        f"打开{name}",
        f"关掉{name}",
        f"关闭{name}",
        f"开{name}",
        f"关{name}",
    ]
    extras: list[str] = []
    for trigger in generic_triggers or []:
        text = str(trigger or "").strip()
        if text and text not in named and text not in extras:
            extras.append(text)
    return {
        "role": f"{name}控制器",
        "planner_recognize": (
            f"控制「{name}」：开关、制冷/制热/送风、设定温度、风速、扫风。"
            f"仅当用户点名该设备时使用本实例，不要派给其它同 capability 的在线节点。"
        ),
        "typical_triggers": named + extras,
    }


def attach(
    capability_id: str,
    *,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
    role: str | None = None,
    planner_recognize: str | None = None,
    typical_triggers: list[str] | None = None,
    do_not_dispatch: list[str] | None = None,
) -> dict[str, Any]:
    """Build a full capability dict for heartbeat / KNOWN_CAPABILITIES."""
    ads = current_ads()
    base = ads.get(capability_id)
    if base is None:
        log.warning("marketplace has no ad for %s; stubbing planner fields", capability_id)
        base = _EMPTY_AD
    out = {"capability_id": capability_id, **base}
    if role is not None:
        out["role"] = str(role)
    if planner_recognize is not None:
        out["planner_recognize"] = str(planner_recognize)
    if typical_triggers is not None:
        out["typical_triggers"] = list(typical_triggers)
    if do_not_dispatch is not None:
        out["do_not_dispatch"] = list(do_not_dispatch)
    out["input_schema"] = dict(input_schema or {})
    out["output_schema"] = dict(output_schema or {})
    return out


def composition_of(capability_id: str) -> str:
    ad = ADS.get(str(capability_id or "").strip()) or {}
    c = str(ad.get("composition") or "atomic").strip().lower()
    return c if c in VALID_COMPOSITIONS else "atomic"


def decomposes_to(capability_id: str) -> list[str]:
    ad = ADS.get(str(capability_id or "").strip()) or {}
    raw = ad.get("decomposes_to") or []
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]
