"""Non-terminal intent status must not block on Brain RTT (intent #839)."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

sys.modules.setdefault("httpx", MagicMock())

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

    def test_failed_stays_synchronous(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
