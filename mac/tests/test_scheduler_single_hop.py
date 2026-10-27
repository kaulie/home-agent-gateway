"""Scheduler posts a single intent_dispatched hop (no scheduled+dispatched pair)."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

sys.modules.setdefault("httpx", MagicMock())

from mac_edge.scheduler import IntentScheduler


class SchedulerSingleHopTest(unittest.TestCase):
    def test_parsed_posts_only_dispatched(self) -> None:
        sched = IntentScheduler()
        intent = {
            "id": "835",
            "status": "intent_parsed",
            "execution_plan": [
                {
                    "step": 1,
                    "capability": "music.play",
                    "assigned_edge_id": "edge-node-x",
                    "status": 0,
                }
            ],
        }
        with patch("mac_edge.scheduler._ledger_active", return_value=None), patch(
            "mac_edge.scheduler._try_post_intent_status", return_value=True
        ) as post:
            sched.handle(intent, edge_id="edge-node-x", brain=MagicMock())
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["status"], "intent_dispatched")

    def test_legacy_scheduled_still_upgrades_once(self) -> None:
        sched = IntentScheduler()
        intent = {
            "id": "836",
            "status": "intent_scheduled",
            "execution_plan": [
                {
                    "step": 1,
                    "capability": "music.play",
                    "assigned_edge_id": "edge-node-x",
                    "status": 0,
                }
            ],
        }
        with patch("mac_edge.scheduler._ledger_active", return_value=None), patch(
            "mac_edge.scheduler._try_post_intent_status", return_value=True
        ) as post:
            sched.handle(intent, edge_id="edge-node-x", brain=MagicMock())
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["status"], "intent_dispatched")


if __name__ == "__main__":
    unittest.main()
