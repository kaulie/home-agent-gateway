"""Unit tests for xiaodu.speaker plugin."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mac_edge.plugins import xiaodu_speaker as xs


class XiaoduSpeakerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # 缓存指到临时目录：单测绝不读/写仓库里的 mac/data
        self._env = mock.patch.dict(
            os.environ,
            {
                "MAC_EDGE_XIAODU_CACHE": str(Path(self._tmp.name) / "xiaodu_renderer.json"),
                "MAC_EDGE_XIAODU_IP": "",
                "MAC_EDGE_XIAODU_DISCOVER": "0",
            },
            clear=False,
        )
        self._env.start()
        xs.bind_server(None)

    def tearDown(self) -> None:
        xs.bind_server(None)
        self._env.stop()

    def test_play_url_sends_stop_seturi_play(self) -> None:
        """xiaodu.play：把已有音频 URL 交给小度（Stop + SetAVTransportURI + Play）。"""
        calls: list[tuple[str, str]] = []

        def fake_post(du_ip: str, action: str, body: str, *, timeout_sec: float = 8.0) -> None:
            calls.append((action, body))

        with mock.patch.object(xs, "_upnp_post", side_effect=fake_post):
            with mock.patch.object(
                xs,
                "resolve_device",
                return_value=xs.XiaoduDevice(ip="192.168.3.47", source="cache"),
            ):
                msg = xs.play_url(
                    "http://192.168.3.84:9527/api/v1/assets/asset_x/content?intent_id=787"
                )
        self.assertIn("xiaodu playing", msg)
        self.assertEqual(
            [a.rsplit("#", 1)[-1] for a, _b in calls],
            ["Stop", "SetAVTransportURI", "Play"],
        )
        self.assertIn("asset_x", calls[1][1])

    def test_play_url_requires_http(self) -> None:
        with self.assertRaises(xs.XiaoduSpeakerError):
            xs.play_url("/tmp/a.mp3")
        with self.assertRaises(xs.XiaoduSpeakerError):
            xs.play_url("")

    def test_play_url_heals_when_cached_device_is_gone(self) -> None:
        """缓存设备播放失败 → 丢缓存重新探测 → 用新设备重试一次（与 speak 同策略）。"""
        played: list[str] = []

        def fake_play(device: xs.XiaoduDevice, uri: str) -> None:
            played.append(device.ip)
            if len(played) == 1:
                raise xs.XiaoduSpeakerError("UPnP request failed (Play): timeout")

        devices = [
            xs.XiaoduDevice(ip="192.168.3.47", source="cache"),
            xs.XiaoduDevice(ip="192.168.3.48", source="discovered"),
        ]
        with mock.patch.object(xs, "resolve_device", side_effect=devices):
            with mock.patch.object(xs, "play_device", side_effect=fake_play):
                msg = xs.play_url("http://192.168.3.84:9527/a.mp3")
        self.assertIn("xiaodu playing", msg)
        self.assertEqual(played, ["192.168.3.47", "192.168.3.48"])

    def test_play_from_params_uses_asset_url(self) -> None:
        """asset_ref(audio) → asset.http_url() → 交给小度播放；产出 status_text。"""
        from mac_edge.asset.types import AssetRef

        ref = AssetRef(asset_id="asset_a1", type="audio", mime_type="audio/mpeg")
        asset = mock.MagicMock()
        asset.require_ref.return_value = ref
        asset.http_url.return_value = "http://192.168.3.84:9527/asset_a1.mp3"
        with mock.patch.object(xs, "play_url", return_value="xiaodu playing on 小度") as fn:
            msg, outputs = xs.play_from_params(
                {"asset_ref": ref.to_dict()},
                asset=asset,
                probe_fn=lambda *_a, **_k: None,  # 单测不探网络
            )
        self.assertEqual(fn.call_args[0][0], "http://192.168.3.84:9527/asset_a1.mp3")
        self.assertIn("xiaodu playing", msg)
        self.assertEqual(outputs["status_text"], "已在小度音箱播放最新音频")
        self.assertEqual(outputs["asset_id"], "asset_a1")

    def test_play_from_params_rejects_non_audio(self) -> None:
        from mac_edge.asset.types import AssetError, AssetRef

        asset = mock.MagicMock()
        asset.require_ref.return_value = AssetRef(asset_id="img_1", type="image", mime_type="image/jpeg")
        with self.assertRaises(xs.XiaoduSpeakerError) as ctx:
            xs.play_from_params({"asset_ref": "{}"}, asset=asset)
        self.assertIn("audio", str(ctx.exception))

        asset.require_ref.side_effect = AssetError("missing or invalid asset_ref")
        with self.assertRaises(xs.XiaoduSpeakerError):
            xs.play_from_params({}, asset=asset)

    def test_advertises_xiaodu_play(self) -> None:
        """xiaodu.speaker 服务同时广告 xiaodu.speak 与 xiaodu.play。"""
        from mac_edge.services import default_services

        env = {"MAC_EDGE_ROLE": "laptop", "MAC_EDGE_SERVICE_WHITELIST": ""}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(xs, "xiaodu_configured", return_value=True):
                with mock.patch(
                    "mac_edge.services.xiaodu_configured", return_value=True, create=True
                ):
                    ids = {
                        str(c["capability_id"])
                        for s in default_services()
                        for c in (s.get("capabilities") or [])
                    }
        self.assertIn("xiaodu.speak", ids)
        self.assertIn("xiaodu.play", ids)

    def test_speak_from_params_requires_text(self) -> None:
        with self.assertRaises(xs.XiaoduSpeakerError) as ctx:
            xs.speak_from_params({})
        self.assertIn("text", str(ctx.exception).lower())

    def test_play_uri_sends_stop_seturi_play(self) -> None:
        calls: list[tuple[str, str, float]] = []

        def fake_post(
            du_ip: str,
            action: str,
            body: str,
            *,
            timeout_sec: float = 8.0,
        ) -> None:
            calls.append((action, body, timeout_sec))

        with mock.patch.object(xs, "_upnp_post", side_effect=fake_post):
            xs.play_uri("192.168.3.47", "http://192.168.3.73:8000/tts_1.mp3")

        self.assertEqual(len(calls), 3)
        self.assertIn("Stop", calls[0][0])
        self.assertEqual(calls[0][2], xs.UPNP_STOP_TIMEOUT_SEC)
        self.assertIn("SetAVTransportURI", calls[1][0])
        self.assertIn("http://192.168.3.73:8000/tts_1.mp3", calls[1][1])
        self.assertIn("Play", calls[2][0])

    def test_play_uri_continues_when_stop_times_out(self) -> None:
        calls: list[str] = []

        def fake_post(
            du_ip: str,
            action: str,
            body: str,
            *,
            timeout_sec: float = 8.0,
        ) -> None:
            calls.append(action)
            if "Stop" in action:
                raise xs.XiaoduSpeakerError("UPnP request failed (Stop): timed out")

        with mock.patch.object(xs, "_upnp_post", side_effect=fake_post):
            xs.play_uri("192.168.3.47", "http://192.168.3.73:8000/tts_2.mp3")

        self.assertEqual(len(calls), 3)
        self.assertIn("Stop", calls[0])
        self.assertIn("SetAVTransportURI", calls[1])
        self.assertIn("Play", calls[2])

    def test_speak_synthesizes_and_plays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            server = xs.XiaoduTtsHttpServer(data_dir=data_dir, http_port=0)
            server.start()
            xs.bind_server(server)
            self.addCleanup(server.stop)
            self.addCleanup(lambda: xs.bind_server(None))

            async def fake_synthesize(text: str, voice: str, path: Path) -> None:
                path.write_bytes(b"\xff" * 128)

            upnp_calls: list[str] = []

            def fake_post(
                du_ip: str,
                action: str,
                body: str,
                *,
                timeout_sec: float = 8.0,
            ) -> None:
                upnp_calls.append(action)

            with mock.patch.dict(
                os.environ,
                {"MAC_EDGE_XIAODU_IP": "192.168.3.47", "MAC_EDGE_XIAODU_PUBLIC_HOST": "192.168.3.73"},
                clear=False,
            ):
                with mock.patch.object(xs, "_synthesize", side_effect=fake_synthesize):
                    with mock.patch.object(xs, "_upnp_post", side_effect=fake_post):
                        msg = xs.speak("欢迎回家")

            self.assertTrue(msg.startswith("xiaodu spoke:"))
            self.assertIn("欢迎回家", msg)
            self.assertEqual(len(upnp_calls), 3)
            mp3_files = list(server.serve_dir.glob("tts_*.mp3"))
            self.assertEqual(len(mp3_files), 1)
            self.assertGreaterEqual(mp3_files[0].stat().st_size, 64)

    def test_xiaodu_configured(self) -> None:
        # 没覆盖、没缓存、探测关掉 → 不广告
        with mock.patch.dict(
            os.environ, {"MAC_EDGE_XIAODU_DISCOVER": "0", "MAC_EDGE_XIAODU_IP": ""}, clear=False
        ):
            self.assertFalse(xs.xiaodu_configured())
        # 显式覆盖 → 广告（老行为）
        with mock.patch.dict(os.environ, {"MAC_EDGE_XIAODU_IP": "192.168.3.47"}, clear=False):
            self.assertTrue(xs.xiaodu_configured())
        # 显式关闭 → 不广告（即使有覆盖）
        with mock.patch.dict(
            os.environ,
            {"MAC_EDGE_XIAODU_IP": "192.168.3.47", "MAC_EDGE_XIAODU": "0"},
            clear=False,
        ):
            self.assertFalse(xs.xiaodu_configured())

    def test_xiaodu_configured_by_discovery(self) -> None:
        """不写死地址也能广告：SSDP 现场探测到就广告。"""
        with mock.patch.dict(
            os.environ,
            {"MAC_EDGE_XIAODU_IP": "", "MAC_EDGE_XIAODU": "", "MAC_EDGE_XIAODU_DISCOVER": ""},
            clear=False,
        ):
            with mock.patch.object(
                xs, "discover_xiaodu", return_value=xs.XiaoduDevice(ip="192.168.3.47")
            ):
                self.assertTrue(xs.xiaodu_configured())

    def test_from_env_returns_none_without_ip(self) -> None:
        with mock.patch.dict(
            os.environ, {"MAC_EDGE_XIAODU_IP": "", "MAC_EDGE_XIAODU_DISCOVER": "0"}, clear=False
        ):
            self.assertIsNone(xs.XiaoduTtsHttpServer.from_env(Path("/tmp/xiaodu_test")))

    def test_public_url_uses_override_host(self) -> None:
        server = xs.XiaoduTtsHttpServer(data_dir=Path("/tmp/xiaodu_test2"), http_port=8000)
        with mock.patch.dict(
            os.environ, {"MAC_EDGE_XIAODU_PUBLIC_HOST": "192.168.3.84"}, clear=False
        ):
            with mock.patch.object(xs.lan, "is_local_ip", return_value=True):
                url = server.public_url("tts_99.mp3")
        self.assertEqual(url, "http://192.168.3.84:8000/tts_99.mp3")

    def test_public_url_ignores_stale_override(self) -> None:
        """写死但过期的本机地址（.73）不能再用 —— 按目标设备探测（.84）。"""
        server = xs.XiaoduTtsHttpServer(data_dir=Path("/tmp/xiaodu_test3"), http_port=8000)
        with mock.patch.dict(
            os.environ, {"MAC_EDGE_XIAODU_PUBLIC_HOST": "192.168.3.73"}, clear=False
        ):
            with mock.patch.object(xs.lan, "is_local_ip", return_value=False):
                with mock.patch.object(xs.lan, "local_ips", return_value=["192.168.3.84"]):
                    with mock.patch.object(xs.lan, "local_ip_for", return_value="192.168.3.84"):
                        host = xs.public_host("192.168.3.47")
                        url = server.public_url("tts_99.mp3", host=host)
        self.assertEqual(url, "http://192.168.3.84:8000/tts_99.mp3")


class XiaoduDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache = Path(self._tmp.name) / "xiaodu_renderer.json"
        self._env = mock.patch.dict(
            os.environ,
            {
                "MAC_EDGE_XIAODU_CACHE": str(self.cache),
                "MAC_EDGE_XIAODU_IP": "",
                "MAC_EDGE_XIAODU_NAME": "",
                "MAC_EDGE_XIAODU": "",
                "MAC_EDGE_XIAODU_DISCOVER": "",
                "MAC_EDGE_XIAODU_PUBLIC_HOST": "",
            },
            clear=False,
        )
        self._env.start()
        xs.bind_server(None)

    def tearDown(self) -> None:
        xs.bind_server(None)
        self._env.stop()

    def _desc(
        self,
        ip: str,
        name: str = "小度智能音箱-8432",
        manufacturer: str = "DuerOS",
        model: str = "DuerOS-Render",
    ):
        from mac_edge.plugins.lan_discovery import DeviceDescription

        return DeviceDescription(
            location=f"http://{ip}:49494/description.xml",
            ip=ip,
            friendly_name=name,
            manufacturer=manufacturer,
            model_name=model,
            services={xs.lan.AV_TRANSPORT: f"http://{ip}:49494/upnp/control/rendertransport1"},
        )

    def _resp(self, ip: str):
        return xs.lan.SsdpResponse(ip=ip, location=f"http://{ip}:49494/description.xml")

    def test_discover_returns_probed_device(self) -> None:
        with mock.patch.object(xs.lan, "ssdp_search", return_value=[self._resp("192.168.3.47")]):
            with mock.patch.object(
                xs.lan, "fetch_device_description", return_value=self._desc("192.168.3.47")
            ):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=True) as probe:
                    device = xs.discover_xiaodu(timeout_sec=0.1)
        self.assertIsNotNone(device)
        self.assertEqual(device.ip, "192.168.3.47")
        self.assertEqual(
            device.control_url, "http://192.168.3.47:49494/upnp/control/rendertransport1"
        )
        probe.assert_called_once()

    def test_discover_skips_unprobeable_device(self) -> None:
        """探活不通 = 不采信（同网段可能还有别的 DuerOS/休眠设备）。"""
        with mock.patch.object(xs.lan, "ssdp_search", return_value=[self._resp("192.168.3.99")]):
            with mock.patch.object(
                xs.lan, "fetch_device_description", return_value=self._desc("192.168.3.99")
            ):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=False):
                    self.assertIsNone(xs.discover_xiaodu(timeout_sec=0.1))

    def test_discover_skips_foreign_devices(self) -> None:
        with mock.patch.object(xs.lan, "ssdp_search", return_value=[self._resp("192.168.3.59")]):
            with mock.patch.object(
                xs.lan,
                "fetch_device_description",
                return_value=self._desc(
                    "192.168.3.59", name="客厅电视", manufacturer="Xiaomi", model="MiTV"
                ),
            ):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=True):
                    self.assertIsNone(xs.discover_xiaodu(timeout_sec=0.1))



class TransportControlTests(unittest.TestCase):
    """pause / resume / stop：小度一套、小米电视一套（共用 av_transport 解析）。"""

    def test_parse_action_aliases(self) -> None:
        from mac_edge.plugins import av_transport as av

        for raw, want in (
            ("pause", av.ACTION_PAUSE),
            ("暂停", av.ACTION_PAUSE),
            ("先停一下", av.ACTION_PAUSE),
            (None, av.ACTION_PAUSE),  # 缺省 = 暂停（最常见诉求）
            ("resume", av.ACTION_RESUME),
            ("继续播放", av.ACTION_RESUME),
            ("接着放", av.ACTION_RESUME),
            ("stop", av.ACTION_STOP),
            ("停止小度播放", av.ACTION_STOP) if False else ("停止", av.ACTION_STOP),
            ("别放了", av.ACTION_STOP),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(av.parse_action(raw), want)

    def test_parse_action_rejects_unknown(self) -> None:
        from mac_edge.plugins import av_transport as av

        with self.assertRaises(av.TransportActionError):
            av.parse_action("快进")

    def test_xiaodu_control_sends_pause(self) -> None:
        calls: list[tuple[str, str]] = []

        def fake_post(device: xs.XiaoduDevice, action: str, body: str, **kw: object) -> None:
            calls.append((action, body))

        with mock.patch.object(xs, "_post", side_effect=fake_post):
            with mock.patch.object(
                xs,
                "resolve_device",
                return_value=xs.XiaoduDevice(ip="192.168.3.47", control_url="http://x/av", source="cache"),
            ):
                msg = xs.control("暂停")
        self.assertIn("已暂停", msg)
        self.assertEqual(calls[0][0].rsplit("#", 1)[-1], "Pause")
        self.assertIn("<InstanceID>0</InstanceID>", calls[0][1])

    def test_xiaodu_control_idle_device_is_not_an_error(self) -> None:
        """设备没在放东西（UPnP 701）→ 给用户人话，不报错。"""
        with mock.patch.object(
            xs,
            "resolve_device",
            return_value=xs.XiaoduDevice(ip="192.168.3.47", source="cache"),
        ):
            with mock.patch.object(
                xs,
                "_post",
                side_effect=xs.XiaoduSpeakerError("UPnP HTTP 500: <errorCode>701</errorCode>"),
            ):
                text, outputs = xs.control_from_params({"action": "pause"})
        self.assertIn("没有在播放", text)
        self.assertEqual(outputs["status_text"], text)

    def test_xiaodu_control_maps_three_actions(self) -> None:
        seen: list[str] = []

        def fake_post(device: xs.XiaoduDevice, action: str, body: str, **kw: object) -> None:
            seen.append(action.rsplit("#", 1)[-1])

        with mock.patch.object(xs, "_post", side_effect=fake_post):
            with mock.patch.object(
                xs,
                "resolve_device",
                return_value=xs.XiaoduDevice(ip="192.168.3.47", control_url="http://x/av"),
            ):
                for raw in ("pause", "resume", "stop"):
                    xs.control(raw)
        self.assertEqual(seen, ["Pause", "Play", "Stop"])

    def test_tv_control_sends_pause_and_maps_actions(self) -> None:
        from mac_edge.plugins import xiaomi_tv_display as tv

        posted: list[str] = []

        def post_fn(_url: str, envelope: str, _headers: dict[str, str]) -> int:
            posted.append(envelope)
            return 200

        renderer = {"friendly_name": "小米电视 S Pro", "control_url": "http://192.168.3.20/av"}
        for raw, want in (("暂停", "Pause"), ("继续", "Play"), ("停止", "Stop")):
            with self.subTest(raw=raw):
                posted.clear()
                msg = tv.control_audio(raw, renderer=renderer, post_fn=post_fn)
                self.assertIn("dlna", msg)
                self.assertIn(want, posted[0])

    def test_tv_control_from_params_status_text(self) -> None:
        from mac_edge.plugins import xiaomi_tv_display as tv

        with mock.patch.object(tv, "control_audio", return_value="dlna pause ok → tv") as fn:
            text, outputs = tv.audio_control_from_params({"action": "暂停"})
        self.assertEqual(fn.call_args[0][0], "暂停")
        self.assertEqual(text, "小米电视已暂停")
        self.assertEqual(outputs["status_text"], "小米电视已暂停")

    def test_both_services_advertise_control_caps(self) -> None:
        from mac_edge.services import default_services

        env = {
            "MAC_EDGE_ROLE": "laptop",
            "MAC_EDGE_SERVICE_WHITELIST": "",
            "MAC_EDGE_DISPLAY_BACKEND": "xiaomi",
            "MAC_EDGE_XIAOMI_TV": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch("mac_edge.services.xiaodu_configured", return_value=True, create=True):
                services = default_services()
        caps = {
            str(c["capability_id"]): str(s["service_id"])
            for s in services
            for c in (s.get("capabilities") or [])
        }
        self.assertEqual(caps.get("xiaodu.control"), "xiaodu.speaker")
        self.assertEqual(caps.get("display.audio.control"), "xiaomi.tv.display")


if __name__ == "__main__":
    unittest.main()


    def test_resolve_prefers_override_then_discovers_and_caches(self) -> None:
        # 显式覆盖优先，且不探测
        with mock.patch.object(xs.lan, "ssdp_search") as ssdp:
            device = xs.resolve_device(override_ip="192.168.3.50")
        self.assertEqual(device.source, "override")
        self.assertEqual(device.ip, "192.168.3.50")
        ssdp.assert_not_called()

        # 没覆盖 → SSDP 探测 → 落缓存
        with mock.patch.object(xs.lan, "ssdp_search", return_value=[self._resp("192.168.3.47")]):
            with mock.patch.object(
                xs.lan, "fetch_device_description", return_value=self._desc("192.168.3.47")
            ):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=True):
                    found = xs.resolve_device()
        self.assertEqual(found.source, "discovered")
        cached = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertEqual(cached["ip"], "192.168.3.47")
        self.assertEqual(cached["control_url"], found.control_url)

        # 有缓存 → 先缓存（但仍要探活通过）
        with mock.patch.object(xs.lan, "ssdp_search") as ssdp2:
            with mock.patch.object(
                xs.lan, "fetch_device_description", return_value=self._desc("192.168.3.47")
            ):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=True):
                    again = xs.resolve_device()
        self.assertEqual(again.source, "cache")
        ssdp2.assert_not_called()

    def test_resolve_drops_stale_cache_and_rediscovers(self) -> None:
        xs.lan.write_cache(
            self.cache,
            {"ip": "192.168.3.47", "location": "http://192.168.3.47:49494/description.xml"},
        )
        fetches = [xs.lan.LanDiscoveryError("timeout"), self._desc("192.168.3.48")]
        with mock.patch.object(xs.lan, "fetch_device_description", side_effect=fetches):
            with mock.patch.object(xs.lan, "ssdp_search", return_value=[self._resp("192.168.3.48")]):
                with mock.patch.object(xs.lan, "probe_av_transport", return_value=True):
                    device = xs.resolve_device()
        self.assertEqual(device.ip, "192.168.3.48")
        self.assertEqual(device.source, "discovered")
        self.assertEqual(json.loads(self.cache.read_text(encoding="utf-8"))["ip"], "192.168.3.48")

    def test_resolve_without_any_device_is_explicit(self) -> None:
        with mock.patch.object(xs.lan, "ssdp_search", return_value=[]):
            with self.assertRaises(xs.XiaoduSpeakerError) as ctx:
                xs.resolve_device()
        self.assertIn("没有找到小度音箱", str(ctx.exception))

    def test_speak_heals_when_cached_device_is_gone(self) -> None:
        """缓存地址播放失败 → 丢缓存重新探测 → 用新地址重试一次。"""
        with tempfile.TemporaryDirectory() as tmp:
            server = xs.XiaoduTtsHttpServer(data_dir=Path(tmp), http_port=0)
            server.start()
            xs.bind_server(server)
            self.addCleanup(server.stop)

            async def fake_synthesize(text: str, voice: str, path: Path) -> None:
                path.write_bytes(b"\xff" * 128)

            played: list[tuple[str, str]] = []

            def fake_play(device: xs.XiaoduDevice, uri: str) -> None:
                played.append((device.ip, uri))
                if len(played) == 1:
                    raise xs.XiaoduSpeakerError("UPnP request failed (Play): timeout")

            devices = [
                xs.XiaoduDevice(ip="192.168.3.47", source="cache"),
                xs.XiaoduDevice(ip="192.168.3.48", source="discovered"),
            ]
            with mock.patch.object(xs, "resolve_device", side_effect=devices):
                with mock.patch.object(xs, "_synthesize", side_effect=fake_synthesize):
                    with mock.patch.object(xs, "play_device", side_effect=fake_play):
                        msg = xs.speak("欢迎回家")
        self.assertTrue(msg.startswith("xiaodu spoke:"))
        self.assertEqual([ip for ip, _uri in played], ["192.168.3.47", "192.168.3.48"])
        self.assertTrue(all("tts_" in uri for _ip, uri in played))
