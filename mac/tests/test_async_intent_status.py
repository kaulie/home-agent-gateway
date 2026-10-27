"""Non-terminal intent status must not block on Brain RTT (intent #839)."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules.setdefault("httpx", MagicMock())

from mac_edge.brain_client import BrainClient
from mac_edge.config import Config, Identity
from mac_edge.executor import _try_post_intent_status


class AsyncIntentStatusTest(unittest.TestCase):
    def test_dispatched_uses_background_post(self) -> None:
        brain = MagicMock()
        with patch("mac_edge.local_ledger.active", return_value=None):
            ok = _try_post_intent_status(
                brain,
                "839",
                status="intent_dispatched",
                edge_id="edge-node-x",
            )
        self.assertTrue(ok)
        brain.post_intent_status_bg.assert_called_once()
        brain.post_intent_status.assert_not_called()
        kwargs = brain.post_intent_status_bg.call_args.kwargs
        self.assertEqual(kwargs["status"], "intent_dispatched")
        self.assertEqual(kwargs["edge_node_id"], "edge-node-x")

    def test_running_uses_background_post(self) -> None:
        brain = MagicMock()
        with patch("mac_edge.local_ledger.active", return_value=None):
            ok = _try_post_intent_status(
                brain,
                "839",
                status="running",
                edge_id="edge-node-x",
                message="executing",
            )
        self.assertTrue(ok)
        brain.post_intent_status_bg.assert_called_once()
        brain.post_intent_status.assert_not_called()

    def test_failed_without_ledger_stays_synchronous(self) -> None:
        """No ledger → need a sync Brain post or the terminal is lost."""
        brain = MagicMock()
        brain.post_intent_status.return_value = {"ok": True}
        with patch("mac_edge.local_ledger.active", return_value=None):
            ok = _try_post_intent_status(
                brain,
                "839",
                status="failed",
                edge_id="edge-node-x",
                message="login required",
            )
        self.assertTrue(ok)
        brain.post_intent_status.assert_called_once()
        brain.post_intent_status_bg.assert_not_called()

    def test_failed_with_ledger_uses_background_post(self) -> None:
        """Intent #846: do not block FAIL path on Brain http_timeout."""
        brain = MagicMock()
        ledger = MagicMock()
        with patch("mac_edge.local_ledger.active", return_value=ledger):
            ok = _try_post_intent_status(
                brain,
                "846",
                status="failed",
                edge_id="edge-node-x",
                message="请先登录实名账号，执行 ncm-cli login 完成登录",
            )
        self.assertTrue(ok)
        ledger.set_intent_status.assert_called_once()
        brain.post_intent_status_bg.assert_called_once()
        brain.post_intent_status.assert_not_called()


class AsyncTerminalStepStatusTest(unittest.TestCase):
    def test_failed_step_with_ledger_uses_background_post(self) -> None:
        from mac_edge.executor import STEP_FAILED, _try_post_step_status

        brain = MagicMock()
        ledger = MagicMock()
        with patch("mac_edge.local_ledger.active", return_value=ledger):
            ok = _try_post_step_status(
                brain,
                "846",
                1,
                status=STEP_FAILED,
                edge_id="edge-node-x",
                msg="请先登录实名账号，执行 ncm-cli login 完成登录",
                outputs={"netease_login": {"logged_in": False}},
            )
        self.assertTrue(ok)
        ledger.set_step_status.assert_called_once()
        brain.post_step_status_bg.assert_called_once()
        ledger.post_terminal_step_now.assert_not_called()
        brain.post_step_status.assert_not_called()

    def test_succeeded_step_with_ledger_still_posts_terminal_now(self) -> None:
        from mac_edge.executor import STEP_SUCCEEDED, _try_post_step_status

        brain = MagicMock()
        ledger = MagicMock()
        ledger.post_terminal_step_now.return_value = True
        with patch("mac_edge.local_ledger.active", return_value=ledger):
            ok = _try_post_step_status(
                brain,
                "846",
                1,
                status=STEP_SUCCEEDED,
                edge_id="edge-node-x",
                outputs={"timing": {"total": 1}},
            )
        self.assertTrue(ok)
        ledger.post_terminal_step_now.assert_called_once()
        brain.post_step_status_bg.assert_not_called()


class IntentStatusBgEpochTest(unittest.TestCase):
    """intent #844: RUNNING must not cancel an in-flight dispatched post."""

    def setUp(self) -> None:
        self.cfg = Config(
            brain_base_url="http://example",
            interval_sec=3.0,
            identity=Identity(),
            data_dir=Path("/tmp/mac-edge-test-epoch"),
            cast_display_url="http://127.0.0.1:9095/endpoint/display",
            capability_timeout_sec=300.0,
        )
        self.client = BrainClient(self.cfg)
        self.posts: list[str] = []

        def _capture(intent_id, *, status, edge_node_id, message="", ts_ms=None):
            self.posts.append(str(status))
            return {"ok": True}

        self.client.post_intent_status = _capture  # type: ignore[method-assign]

    def test_dispatched_survives_subsequent_running_epoch_bump(self) -> None:
        self.client.post_intent_status_bg(
            "844", status="intent_dispatched", edge_node_id="edge-x"
        )
        self.client.post_intent_status_bg(
            "844", status="running", edge_node_id="edge-x", message="exec"
        )
        # Report pool is tiny; give both bg tasks a moment.
        deadline = time.time() + 2.0
        while time.time() < deadline and len(self.posts) < 2:
            time.sleep(0.05)
        self.assertIn("intent_dispatched", self.posts)
        self.assertIn("running", self.posts)


if __name__ == "__main__":
    unittest.main()
