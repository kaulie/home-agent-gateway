"""Gateway reads planner ads from the marketplace API."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from mac_edge.capability_ads import attach, composition_of, decomposes_to
from mac_edge.marketplace_catalog import (
    ads_from_payload,
    overlay_service_ads,
    pin_ads,
    reset_ads,
)


SAMPLE = {
    "capabilities": [
        {
            "capability_id": "xiaodu.play",
            "kind": "output",
            "composition": "atomic",
            "role": "小度音箱音频播放器",
            "planner_recognize": "把一条可拉流的 http(s) 音频 URL 交给客厅小度",
            "typical_triggers": ["用小度播放"],
            "do_not_dispatch": ["本机网易云开播"],
            "in_catalog": True,
        },
        {
            "capability_id": "camera.capture_and_upload",
            "kind": "action",
            "composition": "composite",
            "role": "拍照并上传器",
            "planner_recognize": "拍一张并上传",
            "typical_triggers": ["拍张照片我看一下"],
            "do_not_dispatch": ["投屏本身"],
            "decomposes_to": ["camera.capture", "asset.upload"],
            "prefer_when": "优先本能力",
            "in_catalog": True,
        },
        {
            "capability_id": "climate.set",
            "kind": "action",
            "composition": "atomic",
            "role": "空调控制器",
            "planner_recognize": "控制空调",
            "typical_triggers": ["开空调"],
            "do_not_dispatch": ["开灯"],
            "in_catalog": True,
        },
    ]
}


class MarketplaceCatalogTest(unittest.TestCase):
    def tearDown(self) -> None:
        reset_ads()

    def test_pin_ads_drives_attach(self) -> None:
        pin_ads(ads_from_payload(SAMPLE))
        cap = attach("xiaodu.play", input_schema={"url": {"type": "string"}})
        self.assertEqual(cap["role"], "小度音箱音频播放器")
        self.assertEqual(cap["packages"] if "packages" in cap else None, None)
        self.assertEqual(composition_of("camera.capture_and_upload"), "composite")
        self.assertEqual(
            decomposes_to("camera.capture_and_upload"),
            ["camera.capture", "asset.upload"],
        )

    def test_overlay_refreshes_service_and_preserves_climate(self) -> None:
        pin_ads(ads_from_payload(SAMPLE))
        generic = overlay_service_ads(
            {
                "service_id": "xiaodu.play",
                "capabilities": [
                    {
                        "capability_id": "xiaodu.play",
                        "role": "stale",
                        "planner_recognize": "stale",
                    }
                ],
            }
        )
        self.assertEqual(generic["capabilities"][0]["role"], "小度音箱音频播放器")
        named = overlay_service_ads(
            {
                "service_id": "climate.living_room",
                "capabilities": [
                    {
                        "capability_id": "climate.set",
                        "role": "客厅空调控制器",
                        "planner_recognize": "控制「客厅空调」",
                        "typical_triggers": ["打开客厅空调"],
                    }
                ],
            },
            preserve=frozenset({"role", "planner_recognize", "typical_triggers"}),
        )
        cap = named["capabilities"][0]
        self.assertEqual(cap["role"], "客厅空调控制器")
        self.assertEqual(cap["planner_recognize"], "控制「客厅空调」")
        self.assertEqual(cap["do_not_dispatch"], ["开灯"])

    def test_http_fetch(self) -> None:
        payload = json.dumps(SAMPLE).encode("utf-8")

        class _Resp:
            def read(self) -> bytes:
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        reset_ads()
        with patch("mac_edge.marketplace_catalog.urllib.request.urlopen", return_value=_Resp()):
            from mac_edge.marketplace_catalog import refresh_ads

            ads = refresh_ads(force=True)
        self.assertIn("xiaodu.play", ads)


if __name__ == "__main__":
    unittest.main()
