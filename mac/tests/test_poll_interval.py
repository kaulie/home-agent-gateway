"""Intent discovery must not wait for idle MAC_EDGE_INTERVAL_SEC (intent #842)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("httpx", MagicMock())

from mac_edge.agent import EdgeAgent
from mac_edge.config import Config, Identity


class PollIntervalTest(unittest.TestCase):
    def test_discovery_uses_busy_even_when_ledger_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(
                brain_base_url="http://127.0.0.1:9527",
                interval_sec=3.0,
                busy_interval_sec=0.5,
                identity=Identity(),
                data_dir=Path(tmp),
            )
            agent = EdgeAgent(cfg)
            agent._ledger = MagicMock()
            agent._ledger.snapshot_open.return_value = []
            agent._edge_id = "edge-node-x"
            self.assertEqual(agent._poll_interval_sec(), 0.5)


if __name__ == "__main__":
    unittest.main()
