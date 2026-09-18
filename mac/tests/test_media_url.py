"""播放前媒体 URL 预检（plugins/media_url.py）与四个能力入口的接线。"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from mac_edge.plugins import media_url


class ProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop(media_url.ENV_DISABLE, None)

    def test_ok_statuses_pass(self) -> None:
        for status in (200, 206):
            with self.subTest(status=status):
                seen: list[str] = []
                media_url.verify_media_url(
                    "http://192.168.3.84:8080/a.mp3",
                    fetcher=lambda u: (seen.append(u) or (status, "audio/mpeg", "4370112")),
                )
                self.assertEqual(seen, ["http://192.168.3.84:8080/a.mp3"])

    def test_404_is_clear_failure_without_url_in_message(self) -> None:
        url = "http://192.168.3.84:8080/missing.mp3"
        with self.assertRaises(media_url.MediaUrlError) as ctx:
            media_url.verify_media_url(
                url, what="音频", fetcher=lambda u: (404, "text/html", "482")
            )
        message = str(ctx.exception)
        self.assertIn("取不到", message)
        self.assertIn("404", message)
        self.assertIn("文件不在", message)
        self.assertIn("电视会没声音", message)
        # 用户文案里不出现 URL（运维细节只进日志）
        self.assertNotIn("http://", message)

    def test_server_error_hint(self) -> None:
        with self.assertRaises(media_url.MediaUrlError) as ctx:
            media_url.verify_media_url("http://x/a.mp3", fetcher=lambda u: (500, "", ""))
        self.assertIn("200", str(ctx.exception)) if False else None
        self.assertIn("500", str(ctx.exception))
        self.assertIn("报错", str(ctx.exception))

    def test_connection_error_is_human(self) -> None:
        def boom(_u: str):
            raise ConnectionError("conn refused")

        with self.assertRaises(media_url.MediaUrlError) as ctx:
            media_url.verify_media_url("http://10.0.0.1/a.mp3", fetcher=boom)
        self.assertIn("连接失败", str(ctx.exception))
        self.assertIn("确认提供文件的机器在线", str(ctx.exception))

    def test_empty_url_is_clear_failure(self) -> None:
        with self.assertRaises(media_url.MediaUrlError):
            media_url.verify_media_url("   ")

    def test_kill_switch_skips_probe(self) -> None:
        with mock.patch.dict(os.environ, {media_url.ENV_DISABLE: "0"}):
            called: list[str] = []
            media_url.verify_media_url(
                "http://x/a.mp3", fetcher=lambda u: (called.append(u) or (404, "", ""))
            )
            self.assertEqual(called, [])


class WiringTests(unittest.TestCase):
    """四个入口：探针失败 → 各自的中文失败；成功 → 照常播放。"""

    def setUp(self) -> None:
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        os.environ.pop(media_url.ENV_DISABLE, None)

    def _failing_probe(self, *_a: object, **_k: object) -> None:
        raise media_url.MediaUrlError("音频取不到（HTTP 404）（文件不在），电视会没声音。")

    def test_display_audio_probe_failure_raises_chinese(self) -> None:
        from mac_edge.asset.types import AssetRef
        from mac_edge.plugins import xiaomi_tv_display as tv

        asset = mock.MagicMock()
        asset.require_ref.return_value = AssetRef(asset_id="asset_a1", type="audio", mime_type="audio/mpeg")
        asset.http_url.return_value = "http://192.168.3.84:8080/a.mp3"
        with self.assertRaises(tv.XiaomiTvError) as ctx:
            tv.audio_from_params({}, asset=asset, probe_fn=self._failing_probe, play_fn=lambda *a, **k: "ok")
        self.assertIn("取不到", str(ctx.exception))

    def test_display_audio_probe_ok_then_plays(self) -> None:
        from mac_edge.asset.types import AssetRef
        from mac_edge.plugins import xiaomi_tv_display as tv

        asset = mock.MagicMock()
        asset.require_ref.return_value = AssetRef(asset_id="asset_a1", type="audio", mime_type="audio/mpeg")
        asset.http_url.return_value = "http://192.168.3.84:8080/a.mp3"
        probes: list[str] = []
        played: list[str] = []
        msg, outputs = tv.audio_from_params(
            {},
            asset=asset,
            probe_fn=lambda url, **kw: probes.append(url),
            play_fn=lambda url, **kw: (played.append(url) or "dlna audio ok"),
        )
        self.assertEqual(probes, played)
        self.assertIn("cast_status=accepted", msg)

    def test_display_photo_probe_failure_raises(self) -> None:
        from mac_edge.asset.types import AssetRef
        from mac_edge.plugins import xiaomi_tv_display as tv

        asset = mock.MagicMock()
        asset.require_ref.return_value = AssetRef(asset_id="asset_p1", type="image", mime_type="image/jpeg")
        asset.http_url.return_value = "http://192.168.3.84:8080/p.jpg"
        with mock.patch.object(tv, "play_photo", return_value="dlna ok") as play:
            with self.assertRaises(tv.XiaomiTvError):
                tv.photo_from_params({}, asset=asset, probe_fn=self._failing_probe)
        play.assert_not_called()

    def test_display_slideshow_probes_every_url(self) -> None:
        from mac_edge.asset.types import AssetRef
        from mac_edge.plugins import xiaomi_tv_display as tv

        refs = [AssetRef(asset_id=f"asset_p{i}", type="image") for i in (1, 2, 3)]
        asset = mock.MagicMock()
        asset.require_refs.return_value = refs
        asset.http_url.side_effect = [f"http://192.168.3.84:8080/p{i}.jpg" for i in (1, 2, 3)]
        probed: list[str] = []
        with mock.patch.object(tv, "play_slideshow", return_value="dlna ok"):
            tv.slideshow_from_params(
                {}, asset=asset, probe_fn=lambda url, **kw: probed.append(url)
            )
        self.assertEqual(len(probed), 3)

    def test_xiaodu_play_probe_failure_raises_chinese(self) -> None:
        from mac_edge.asset.types import AssetRef
        from mac_edge.plugins import xiaodu_speaker as xs

        asset = mock.MagicMock()
        asset.require_ref.return_value = AssetRef(asset_id="asset_a1", type="audio", mime_type="audio/mpeg")
        asset.http_url.return_value = "http://192.168.3.84:8080/a.mp3"
        with self.assertRaises(xs.XiaoduSpeakerError) as ctx:
            xs.play_from_params({}, asset=asset, probe_fn=self._failing_probe)
        self.assertIn("取不到", str(ctx.exception))

    def test_xiaodu_play_probe_ok_then_plays(self) -> None:
        from mac_edge.asset.types import AssetRef
        from mac_edge.plugins import xiaodu_speaker as xs

        asset = mock.MagicMock()
        asset.require_ref.return_value = AssetRef(asset_id="asset_a1", type="audio", mime_type="audio/mpeg")
        asset.http_url.return_value = "http://192.168.3.84:8080/a.mp3"
        with mock.patch.object(xs, "play_url", return_value="xiaodu playing on 小度") as play:
            with mock.patch.object(xs, "resolve_device"):
                msg, outputs = xs.play_from_params(
                    {}, asset=asset, probe_fn=lambda url, **kw: None
                )
        play.assert_called_once()
        self.assertEqual(outputs["asset_id"], "asset_a1")


if __name__ == "__main__":
    unittest.main()
