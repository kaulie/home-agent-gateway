"""Ledger must not treat foreign/blocked intents as local open work."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mac_edge.local_ledger import LocalLedger, STEP_WAITING, STEP_SUCCEEDED


EID = "edge-mac"
OTHER = "edge-phone"


class LedgerForeignPruneTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = LocalLedger(Path(self.tmp.name) / "ledger.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_snapshot_open_skips_blocked_on_foreign_predecessor(self) -> None:
        self.ledger.ingest_peek(
            [
                {
                    "id": "z1",
                    "status": "intent_dispatched",
                    "execution_plan": [
                        {
                            "step": 1,
                            "status": STEP_WAITING,
                            "assigned_edge_id": OTHER,
                            "capability": "camera.capture",
                        },
                        {
                            "step": 2,
                            "status": STEP_WAITING,
                            "assigned_edge_id": EID,
                            "capability": "notify.speak",
                        },
                    ],
                }
            ],
            EID,
        )
        self.assertEqual(self.ledger.snapshot_open(EID), [])

    def test_snapshot_open_keeps_locally_runnable(self) -> None:
        self.ledger.ingest_peek(
            [
                {
                    "id": "ok1",
                    "status": "intent_dispatched",
                    "execution_plan": [
                        {
                            "step": 1,
                            "status": STEP_WAITING,
                            "assigned_edge_id": EID,
                            "capability": "music.play",
                        }
                    ],
                }
            ],
            EID,
        )
        open_ids = [str(r.get("id")) for r in self.ledger.snapshot_open(EID)]
        self.assertEqual(open_ids, ["ok1"])

    def test_prune_drops_synced_foreign_blocked(self) -> None:
        self.ledger.ingest_peek(
            [
                {
                    "id": "z2",
                    "status": "intent_dispatched",
                    "execution_plan": [
                        {
                            "step": 1,
                            "status": STEP_WAITING,
                            "assigned_edge_id": OTHER,
                            "capability": "camera.capture",
                        },
                        {
                            "step": 2,
                            "status": STEP_WAITING,
                            "assigned_edge_id": EID,
                            "capability": "notify.speak",
                        },
                    ],
                }
            ],
            EID,
        )
        # Mark synced so prune may drop (no pending Brain replay).
        with self.ledger._lock:
            self.ledger._intents["z2"]["synced"] = True
            self.ledger._persist_unlocked()
        self.assertEqual(self.ledger.prune_blocked_foreign(EID), 1)
        self.assertIsNone(self.ledger.get("z2"))

    def test_local_after_foreign_pred_succeeded(self) -> None:
        self.ledger.ingest_peek(
            [
                {
                    "id": "chain",
                    "status": "running",
                    "execution_plan": [
                        {
                            "step": 1,
                            "status": STEP_SUCCEEDED,
                            "assigned_edge_id": OTHER,
                            "capability": "camera.capture",
                        },
                        {
                            "step": 2,
                            "status": STEP_WAITING,
                            "assigned_edge_id": EID,
                            "capability": "notify.speak",
                        },
                    ],
                }
            ],
            EID,
        )
        open_ids = [str(r.get("id")) for r in self.ledger.snapshot_open(EID)]
        self.assertEqual(open_ids, ["chain"])


if __name__ == "__main__":
    unittest.main()
