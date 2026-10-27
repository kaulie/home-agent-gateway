"""Local intent/step ledger: scheduling source of truth while Brain is a sync target.

Peek from Brain only *adds* work. Local status/beat drive execution. Each status
change is appended to ``sync_queue`` with its local ``ts_ms``. On reconnect,
flush replays the full queue in order (not a snapshot of the latest status).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from mac_edge.brain_client import BrainClient, BrainError
from mac_edge.execution_timing import parse_execution_timing, timing_gate
from mac_edge.brain_time import BRAIN_CLOCK
from mac_edge.multi_brain import remember_intent_origin
from mac_edge.timing_beats import get_beat, set_beat

log = logging.getLogger("mac_edge.ledger")

STEP_WAITING = 0
STEP_RUNNING = 1
STEP_SUCCEEDED = 2
STEP_FAILED = 3

# Brain rejections for queued events that can never be applied (the intent or
# step has already moved past them — e.g. a stale RUNNING after the intent
# became terminal). Such an event must not block the replay queue forever; it
# is dropped and flushing continues (terminal success/fail events still carry
# their outputs/msgs and are accepted by Brain even after the intent terminal).
_OBSOLETE_REPLAY_MARKERS = (
    "intent is terminal",
    "cannot return to running",
    "cannot regress",
    "status already updated before",
)


def _is_obsolete_replay(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in _OBSOLETE_REPLAY_MARKERS)


_active: "LocalLedger | None" = None
_active_lock = threading.Lock()


def bind(ledger: LocalLedger | None) -> None:
    global _active
    with _active_lock:
        _active = ledger


def active() -> LocalLedger | None:
    with _active_lock:
        return _active


class LocalLedger:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()
        self._intents: dict[str, dict[str, Any]] = {}
        self._ghost_guard: dict[str, dict[str, Any]] = {}
        self._load()
        self._hydrate_beats()

    # --- persistence ---

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("ledger: failed to read %s: %s", self._path, e)
            return
        raw = data.get("intents") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            iid = str(item.get("id") or item.get("intent_id") or "").strip()
            if not iid:
                continue
            self._intents[iid] = _normalize_record(item)
            _remember_record_origin(self._intents[iid])

    def _persist_unlocked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"intents": [self._intents[k] for k in sorted(self._intents)]}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def _hydrate_beats(self) -> None:
        with self._lock:
            items = list(self._intents.items())
        for iid, rec in items:
            for step in rec.get("execution_plan") or []:
                if not isinstance(step, dict):
                    continue
                n = int(step.get("step") or 0)
                beat = int(step.get("beat") or 0)
                set_beat(iid, n, beat)

    # --- ingest ---

    def ingest_peek(self, peeked: list[dict[str, Any]], edge_id: str) -> int:
        """Accept new Brain intents. Never overwrite this edge's status/beat/synced."""
        added = 0
        dirty = False
        with self._lock:
            for item in peeked:
                if not isinstance(item, dict):
                    continue
                iid = str(item.get("id") or item.get("intent_id") or "").strip()
                if not iid:
                    continue
                if iid not in self._intents:
                    if self._is_stale_brain_ghost(item):
                        log.info(
                            "ledger: ignore stale Brain ghost intent %s (already synced locally)",
                            iid,
                        )
                        continue
                    self._intents[iid] = _normalize_record(item, from_brain=True)
                    added += 1
                    dirty = True
                    log.info("ledger: accept intent %s from Brain", iid)
                elif _is_recycled_brain_intent(self._intents[iid], item):
                    self._intents[iid] = _normalize_record(item, from_brain=True)
                    added += 1
                    dirty = True
                    log.info("ledger: replace recycled intent %s from Brain", iid)
                elif _merge_foreign_progress(self._intents[iid], item, edge_id):
                    dirty = True
            if dirty:
                self._persist_unlocked()
        if added:
            self._hydrate_beats()
        return added

    def snapshot_open(self, edge_id: str) -> list[dict[str, Any]]:
        """Working copies of intents that still have local work for this edge."""
        eid = (edge_id or "").strip()
        now = BRAIN_CLOCK.now_ms()
        with self._lock:
            records = [json.loads(json.dumps(v)) for v in self._intents.values()]
        out: list[dict[str, Any]] = []
        for rec in records:
            iid = str(rec.get("id") or "").strip()
            if not iid:
                continue
            if _record_has_remaining_work(rec, iid, eid, now):
                out.append(rec)
        return out

    def prune_blocked_foreign(self, edge_id: str) -> int:
        """Drop ledger rows that cannot run here (foreign/blocked predecessors).

        Keeps rows with unsynced sync_queue so Brain still gets status replay.
        """
        eid = (edge_id or "").strip()
        if not eid:
            return 0
        now = BRAIN_CLOCK.now_ms()
        dropped = 0
        with self._lock:
            doomed: list[str] = []
            for iid, rec in self._intents.items():
                if _record_has_remaining_work(rec, iid, eid, now):
                    continue
                if rec.get("synced") is not True:
                    continue
                # Any step still has a pending sync event?
                busy_queue = False
                for step in rec.get("execution_plan") or []:
                    if isinstance(step, dict) and step.get("sync_queue"):
                        busy_queue = True
                        break
                if busy_queue:
                    continue
                doomed.append(iid)
            for iid in doomed:
                self._intents.pop(iid, None)
                dropped += 1
            if dropped:
                self._persist_unlocked()
        if dropped:
            log.info(
                "ledger: pruned %s blocked/foreign intent(s) (edge_id=%s)",
                dropped,
                eid,
            )
        return dropped

    def get(self, intent_id: str) -> dict[str, Any] | None:
        iid = str(intent_id).strip()
        with self._lock:
            rec = self._intents.get(iid)
            if rec is None:
                return None
            return json.loads(json.dumps(rec))

    def overlay_intent(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Replace Brain snapshot fields with local plan/status when we own it."""
        iid = str(intent.get("id") or intent.get("intent_id") or "").strip()
        local = self.get(iid) if iid else None
        if local is None:
            return intent
        merged = dict(intent)
        merged["execution_plan"] = local.get("execution_plan")
        merged["status"] = local.get("status")
        merged["intent_status"] = local.get("status")
        if local.get("step_outputs"):
            merged["step_outputs"] = local["step_outputs"]
        return merged

    # --- local writes ---

    def set_step_status(
        self,
        intent_id: str,
        step_num: int,
        status: int,
        *,
        outputs: dict[str, Any] | None = None,
        ts_ms: int | None = None,
        msg: str | None = None,
    ) -> None:
        iid = str(intent_id).strip()
        n = int(step_num)
        st = int(status)
        ts = int(ts_ms) if ts_ms is not None else BRAIN_CLOCK.now_ms()
        note = str(msg).strip() if msg else ""
        with self._lock:
            rec = self._intents.get(iid)
            if rec is None:
                return
            for step in rec.get("execution_plan") or []:
                if not isinstance(step, dict):
                    continue
                if int(step.get("step") or 0) != n:
                    continue
                prev = int(step.get("status") or STEP_WAITING)
                step["status"] = st
                step["beat"] = int(get_beat(iid, n))
                if note:
                    step["msg"] = note
                if outputs:
                    step["outputs"] = dict(outputs)
                    bags = rec.setdefault("step_outputs", {})
                    if not isinstance(bags, dict):
                        bags = {}
                        rec["step_outputs"] = bags
                    old = bags.get(str(n)) if isinstance(bags.get(str(n)), dict) else {}
                    bags[str(n)] = {**old, **outputs}
                queued = _enqueue_step_event(
                    step, st, ts, outputs=outputs, prev=prev, msg=note or None
                )
                if queued:
                    step["synced"] = False
                break
            self._persist_unlocked()

    def set_intent_status(
        self,
        intent_id: str,
        status: str,
        *,
        ts_ms: int | None = None,
    ) -> None:
        iid = str(intent_id).strip()
        wire = str(status or "").strip().lower()
        with self._lock:
            rec = self._intents.get(iid)
            if rec is None:
                return
            if str(rec.get("status") or "").strip().lower() == wire:
                return
            rec["status"] = wire
            if ts_ms is not None:
                try:
                    rec["status_ts_ms"] = int(ts_ms)
                except (TypeError, ValueError):
                    rec["status_ts_ms"] = None
            else:
                rec["status_ts_ms"] = None
            # Keep every hop so a later terminal flush can still deliver
            # intent_dispatched after a lost background POST (intent #847).
            hist = rec.get("status_history")
            if not isinstance(hist, list):
                hist = []
                rec["status_history"] = hist
            try:
                hist_ts = int(ts_ms) if ts_ms is not None else None
            except (TypeError, ValueError):
                hist_ts = None
            hist.append({"status": wire, "ts_ms": hist_ts, "synced": False})
            rec["synced"] = False
            self._persist_unlocked()

    def note_beat(self, intent_id: str, step_num: int, beat: int) -> None:
        iid = str(intent_id).strip()
        n = int(step_num)
        b = max(0, int(beat))
        with self._lock:
            rec = self._intents.get(iid)
            if rec is None:
                return
            for step in rec.get("execution_plan") or []:
                if not isinstance(step, dict):
                    continue
                if int(step.get("step") or 0) != n:
                    continue
                step["beat"] = b
                break
            self._persist_unlocked()

    def mark_step_synced(
        self,
        intent_id: str,
        step_num: int,
        *,
        status: int | None = None,
        seq: int | None = None,
    ) -> None:
        iid = str(intent_id).strip()
        n = int(step_num)
        with self._lock:
            rec = self._intents.get(iid)
            if rec is None:
                return
            for step in rec.get("execution_plan") or []:
                if not isinstance(step, dict):
                    continue
                if int(step.get("step") or 0) != n:
                    continue
                q = step.setdefault("sync_queue", [])
                if not q:
                    step["synced"] = True
                    break
                head = q[0] if isinstance(q[0], dict) else {}
                if seq is not None and int(head.get("seq") or 0) != int(seq):
                    break
                if status is not None and int(head.get("status") or 0) != int(status):
                    break
                q.pop(0)
                step["synced"] = not q
                break
            self._drop_if_done_unlocked(iid, rec)
            self._persist_unlocked()

    def post_terminal_step_now(
        self,
        brain: BrainClient,
        edge_id: str,
        intent_id: str,
        step_num: int,
        *,
        status: int,
        outputs: dict[str, Any] | None = None,
        ts_ms: int | None = None,
        msg: str | None = None,
    ) -> bool:
        """Push a terminal step to Brain without waiting on ``_flush_lock``.

        Intent #843: capability failed in ~3s, but ``_try_post_step_status``
        blocked ~15s on a background RUNNING flush that held the flush lock
        across slow Brain RTTs. Terminal outcomes must reach Brain immediately
        so clients leave the journey without waiting for that backlog.
        """
        eid = (edge_id or "").strip()
        iid = str(intent_id).strip()
        n = int(step_num)
        st = int(status)
        if st not in (STEP_SUCCEEDED, STEP_FAILED) or not eid or not iid:
            return False

        # Peek only — keep the event queued until Brain accepts (or rejects as
        # obsolete) so a failed direct post can still be flushed later.
        peeked = self._peek_step_event(iid, n, status=st)
        if peeked is None:
            peeked = {
                "status": st,
                "ts_ms": int(ts_ms) if ts_ms is not None else BRAIN_CLOCK.now_ms(),
                "seq": None,
                "outputs": dict(outputs) if outputs else None,
                "msg": str(msg).strip() if msg else None,
            }

        outs = peeked.get("outputs") if isinstance(peeked.get("outputs"), dict) else None
        if outs is None and outputs:
            outs = dict(outputs)
        try:
            ts_i = int(peeked["ts_ms"]) if peeked.get("ts_ms") is not None else None
        except (TypeError, ValueError):
            ts_i = None
        note = str(peeked.get("msg") or "").strip() or None
        try:
            brain.post_step_status(
                iid,
                n,
                step_status=st,
                edge_node_id=eid,
                outputs=outs,
                ts_ms=ts_i,
                msg=note,
            )
        except BrainError as e:
            if _is_obsolete_replay(str(e)):
                log.warning(
                    "ledger: terminal step %s/%s status=%s already on Brain (%s)",
                    iid,
                    n,
                    st,
                    e,
                )
                self._discard_leading_non_terminal(iid, n)
                self._discard_matching_step_event(iid, n, status=st)
                return True
            log.warning(
                "ledger: terminal step %s/%s status=%s direct post failed: %s",
                iid,
                n,
                st,
                e,
            )
            return False

        # Drop stale RUNNING ahead of the terminal event, then the terminal itself.
        self._discard_leading_non_terminal(iid, n)
        self._discard_matching_step_event(iid, n, status=st)
        return True

    def _peek_step_event(
        self,
        intent_id: str,
        step_num: int,
        *,
        status: int,
    ) -> dict[str, Any] | None:
        """Copy the first queued event matching status (leave queue intact)."""
        iid = str(intent_id).strip()
        n = int(step_num)
        st = int(status)
        with self._lock:
            rec = self._intents.get(iid)
            if rec is None:
                return None
            for step in rec.get("execution_plan") or []:
                if not isinstance(step, dict):
                    continue
                if int(step.get("step") or 0) != n:
                    continue
                q = step.get("sync_queue") or []
                if not isinstance(q, list):
                    return None
                for raw in q:
                    if not isinstance(raw, dict):
                        continue
                    if int(raw.get("status") or 0) != st:
                        continue
                    return json.loads(json.dumps(raw))
                return None
        return None

    def _discard_matching_step_event(
        self,
        intent_id: str,
        step_num: int,
        *,
        status: int,
    ) -> None:
        """Remove the first queued event matching status."""
        iid = str(intent_id).strip()
        n = int(step_num)
        st = int(status)
        with self._lock:
            rec = self._intents.get(iid)
            if rec is None:
                return
            for step in rec.get("execution_plan") or []:
                if not isinstance(step, dict):
                    continue
                if int(step.get("step") or 0) != n:
                    continue
                q = step.get("sync_queue") or []
                if not isinstance(q, list):
                    return
                for idx, raw in enumerate(q):
                    if not isinstance(raw, dict):
                        continue
                    if int(raw.get("status") or 0) != st:
                        continue
                    q.pop(idx)
                    step["synced"] = not bool(q)
                    self._drop_if_done_unlocked(iid, rec)
                    self._persist_unlocked()
                    return
                return

    def _discard_leading_non_terminal(self, intent_id: str, step_num: int) -> None:
        iid = str(intent_id).strip()
        n = int(step_num)
        with self._lock:
            rec = self._intents.get(iid)
            if rec is None:
                return
            for step in rec.get("execution_plan") or []:
                if not isinstance(step, dict):
                    continue
                if int(step.get("step") or 0) != n:
                    continue
                q = step.get("sync_queue") or []
                if not isinstance(q, list) or not q:
                    return
                changed = False
                while q and isinstance(q[0], dict):
                    head_st = int(q[0].get("status") or 0)
                    if head_st in (STEP_SUCCEEDED, STEP_FAILED):
                        break
                    q.pop(0)
                    changed = True
                if changed:
                    step["synced"] = not bool(q)
                    self._persist_unlocked()
                return

    def mark_intent_synced(
        self,
        intent_id: str,
        *,
        status: str | None = None,
    ) -> None:
        iid = str(intent_id).strip()
        with self._lock:
            rec = self._intents.get(iid)
            if rec is None:
                return
            wire = str(status or "").strip().lower() if status is not None else None
            hist = rec.get("status_history")
            if isinstance(hist, list) and wire:
                for ev in hist:
                    if not isinstance(ev, dict):
                        continue
                    if str(ev.get("status") or "").strip().lower() != wire:
                        continue
                    if ev.get("synced") is True:
                        continue
                    ev["synced"] = True
                    break
            current = str(rec.get("status") or "").strip().lower()
            if isinstance(hist, list) and hist:
                if all(isinstance(e, dict) and e.get("synced") is True for e in hist):
                    rec["synced"] = True
            elif wire is None or not current or wire == current:
                rec["synced"] = True
            self._drop_if_done_unlocked(iid, rec)
            self._persist_unlocked()

    def _drop_if_done_unlocked(self, iid: str, rec: dict[str, Any]) -> None:
        if rec.get("synced") is not True:
            return
        plan = rec.get("execution_plan") or []
        if not all(isinstance(s, dict) and s.get("synced") is True for s in plan):
            return
        wire = str(rec.get("status") or "").strip().lower()
        if wire not in ("succeeded", "failed"):
            return
        now = BRAIN_CLOCK.now_ms()
        # One-shot: later waiting steps will not run after intent failed.
        # Only keep the record if a recurring series is still open.
        if _recurring_series_open(rec, iid, now):
            return
        self._remember_ghost_unlocked(iid, rec)
        del self._intents[iid]
        log.info("ledger: drop terminal synced intent %s", iid)

    def _remember_ghost_unlocked(self, iid: str, rec: dict[str, Any]) -> None:
        self._ghost_guard[iid] = {
            "base_ms": _intent_base_ms(rec),
            "text": str(rec.get("text") or "").strip(),
            "caps": _plan_caps(rec),
            "wire": str(rec.get("status") or "").strip().lower(),
            "dropped_at_ms": BRAIN_CLOCK.now_ms(),
        }

    def _is_stale_brain_ghost(self, item: dict[str, Any]) -> bool:
        iid = str(item.get("id") or item.get("intent_id") or "").strip()
        guard = self._ghost_guard.get(iid)
        if guard is None:
            return False
        if BRAIN_CLOCK.now_ms() - int(guard.get("dropped_at_ms") or 0) > 120_000:
            return False
        peek_wire = str(
            item.get("status") or item.get("intent_status") or ""
        ).strip().lower()
        if peek_wire in ("succeeded", "failed"):
            self._ghost_guard.pop(iid, None)
            return False
        if guard.get("text") and str(item.get("text") or "").strip() != guard["text"]:
            return False
        if guard.get("caps") and _plan_caps(item) != guard["caps"]:
            return False
        peek_base = _intent_base_ms(item)
        if guard.get("base_ms") is not None and peek_base != guard["base_ms"]:
            return False
        return True

    # --- flush ---

    def flush_to_brain(
        self,
        brain: BrainClient,
        edge_id: str,
        *,
        prefer_intent_id: str | None = None,
    ) -> int:
        """Replay every queued step event in order, then unsynced intent status.

        ``prefer_intent_id`` drains that intent's step/intent queue first so a
        live RUNNING flush is not stuck behind unrelated sync backlog.
        """
        eid = (edge_id or "").strip()
        if not eid:
            return 0
        with self._flush_lock:
            return self._flush_to_brain_unlocked(
                brain, eid, prefer_intent_id=prefer_intent_id
            )

    def _flush_to_brain_unlocked(
        self,
        brain: BrainClient,
        edge_id: str,
        *,
        prefer_intent_id: str | None = None,
    ) -> int:
        posted = 0
        prefer = str(prefer_intent_id or "").strip() or None
        while True:
            job = self._next_queued_event(prefer_intent_id=prefer)
            if job is None:
                break
            iid, n, ev = job
            st = int(ev.get("status") or 0)
            # Terminal steps keep their outputs. A FAILED step can still carry a
            # product for the upper layer (e.g. ncm-cli login info the Brain turns
            # into a login link) — never drop it on the way to Brain.
            outputs = ev.get("outputs") if st in (STEP_SUCCEEDED, STEP_FAILED) else None
            if not isinstance(outputs, dict):
                outputs = None
            ts_ms = ev.get("ts_ms")
            try:
                ts_i = int(ts_ms) if ts_ms is not None else None
            except (TypeError, ValueError):
                ts_i = None
            seq = ev.get("seq")
            try:
                seq_i = int(seq) if seq is not None else None
            except (TypeError, ValueError):
                seq_i = None
            note = str(ev.get("msg") or "").strip() or None
            try:
                brain.post_step_status(
                    iid,
                    n,
                    step_status=st,
                    edge_node_id=edge_id,
                    outputs=outputs,
                    ts_ms=ts_i,
                    msg=note,
                )
            except BrainError as e:
                if _is_obsolete_replay(str(e)):
                    log.warning(
                        "ledger: drop obsolete step %s/%s status=%s (Brain: %s)",
                        iid,
                        n,
                        st,
                        e,
                    )
                    self._discard_queued_event(iid, n)
                    continue
                log.warning(
                    "ledger: flush step %s/%s status=%s ts=%s failed: %s",
                    iid,
                    n,
                    st,
                    ts_i,
                    e,
                )
                return posted
            self.mark_step_synced(iid, n, status=st, seq=seq_i)
            posted += 1
        with self._lock:
            intent_jobs: list[tuple[str, str, int | None]] = []
            for iid, rec in self._intents.items():
                hist = rec.get("status_history")
                if isinstance(hist, list) and hist:
                    for ev in hist:
                        if not isinstance(ev, dict) or ev.get("synced") is True:
                            continue
                        wire = str(ev.get("status") or "").strip().lower()
                        if not wire:
                            continue
                        try:
                            ts_i = (
                                int(ev["ts_ms"])
                                if ev.get("ts_ms") is not None
                                else None
                            )
                        except (TypeError, ValueError):
                            ts_i = None
                        intent_jobs.append((iid, wire, ts_i))
                    continue
                if rec.get("synced") is True:
                    continue
                wire = str(rec.get("status") or "").strip().lower() or "running"
                try:
                    ts_i = (
                        int(rec["status_ts_ms"])
                        if rec.get("status_ts_ms") is not None
                        else None
                    )
                except (TypeError, ValueError):
                    ts_i = None
                intent_jobs.append((iid, wire, ts_i))
        if prefer:
            intent_jobs.sort(key=lambda row: 0 if row[0] == prefer else 1)
        for iid, wire, status_ts in intent_jobs:
            rec = self.get(iid)
            if rec is None:
                continue
            # Intent #843: after a terminal step already reached Brain, a late
            # RUNNING flush must not burn another RTT (or block the next flush).
            # Intent #847: still deliver intent_dispatched — skipping it left
            # status_log as parsed→failed and froze the client on 意图解析完成.
            if wire == "running" and _record_has_local_terminal_step(rec):
                log.info(
                    "ledger: skip stale intent %s status=%s (local step already terminal)",
                    iid,
                    wire,
                )
                self.mark_intent_synced(iid, status=wire)
                continue
            try:
                ts_i: int | None
                try:
                    ts_i = int(status_ts) if status_ts is not None else None
                except (TypeError, ValueError):
                    ts_i = None
                brain.post_intent_status(
                    iid,
                    status=wire,
                    edge_node_id=edge_id,
                    message="ledger flush",
                    ts_ms=ts_i,
                )
            except BrainError as e:
                if _is_obsolete_replay(str(e)):
                    log.warning(
                        "ledger: drop obsolete intent %s status=%s (Brain: %s)",
                        iid,
                        wire,
                        e,
                    )
                    self.mark_intent_synced(iid, status=wire)
                    continue
                log.warning("ledger: flush intent %s status=%s failed: %s", iid, wire, e)
                return posted
            self.mark_intent_synced(iid, status=wire)
            posted += 1
        if posted:
            log.info("ledger: flushed %s record(s) to Brain", posted)
        return posted

    def _next_queued_event(
        self,
        *,
        prefer_intent_id: str | None = None,
    ) -> tuple[str, int, dict[str, Any]] | None:
        prefer = str(prefer_intent_id or "").strip() or None

        def _scan(items: list[tuple[str, dict[str, Any]]]) -> tuple[str, int, dict[str, Any]] | None:
            for iid, rec in items:
                for step in rec.get("execution_plan") or []:
                    if not isinstance(step, dict):
                        continue
                    q = step.get("sync_queue") or []
                    if not q or not isinstance(q[0], dict):
                        continue
                    n = int(step.get("step") or 0)
                    return iid, n, json.loads(json.dumps(q[0]))
            return None

        with self._lock:
            items = list(self._intents.items())
            if prefer:
                preferred = [(iid, rec) for iid, rec in items if iid == prefer]
                rest = [(iid, rec) for iid, rec in items if iid != prefer]
                hit = _scan(preferred)
                if hit is not None:
                    return hit
                return _scan(rest)
            return _scan(items)

    def _discard_queued_event(self, intent_id: str, step_num: int) -> None:
        """Drop the head sync event for a step Brain will never accept.

        Called when Brain rejects the replay as obsolete (intent/step already
        terminal). Keeping it would stall every later event's flush forever, so
        remove it and let the queue keep draining (later terminal events still
        carry outputs/msgs to Brain).
        """
        iid = str(intent_id).strip()
        n = int(step_num)
        with self._lock:
            rec = self._intents.get(iid)
            if rec is None:
                return
            for step in rec.get("execution_plan") or []:
                if not isinstance(step, dict):
                    continue
                if int(step.get("step") or 0) != n:
                    continue
                q = step.get("sync_queue") or []
                if isinstance(q, list) and q:
                    q.pop(0)
                step["synced"] = not bool(step.get("sync_queue") or [])
                break
            self._persist_unlocked()


def _normalize_record(item: dict[str, Any], *, from_brain: bool = False) -> dict[str, Any]:
    rec = dict(item)
    iid = str(rec.get("id") or rec.get("intent_id") or "").strip()
    rec["id"] = iid
    rec["status"] = str(rec.get("status") or rec.get("intent_status") or "running").strip().lower()
    rec["synced"] = True if from_brain else bool(rec.get("synced", False))
    plan_in = rec.get("execution_plan")
    plan: list[dict[str, Any]] = []
    if isinstance(plan_in, list):
        for raw in plan_in:
            if not isinstance(raw, dict):
                continue
            step = dict(raw)
            try:
                st = int(step.get("status", step.get("step_status", STEP_WAITING)))
            except (TypeError, ValueError):
                st = STEP_WAITING
            step["status"] = st
            try:
                beat = int(step.get("beat") or 0)
            except (TypeError, ValueError):
                beat = 0
            step["beat"] = beat
            if from_brain:
                step["synced"] = True
                step["sync_queue"] = []
                step["sync_seq"] = 0
            else:
                step["synced"] = bool(step.get("synced", False))
                try:
                    step["sync_seq"] = int(step.get("sync_seq") or 0)
                except (TypeError, ValueError):
                    step["sync_seq"] = 0
                q_in = step.get("sync_queue")
                q: list[dict[str, Any]] = []
                if isinstance(q_in, list):
                    for ev in q_in:
                        if isinstance(ev, dict) and "status" in ev:
                            q.append(dict(ev))
                step["sync_queue"] = q
                if q:
                    step["synced"] = False
            plan.append(step)
    rec["execution_plan"] = plan
    _remember_record_origin(rec)
    return rec


def _remember_record_origin(rec: dict[str, Any]) -> None:
    iid = str(rec.get("id") or rec.get("intent_id") or "").strip()
    origin = str(rec.get("_brain_origin") or rec.get("brain_origin") or "").strip()
    if iid and origin:
        remember_intent_origin(iid, origin)


_SYNC_QUEUE_CAP = 1024


def _enqueue_step_event(
    step: dict[str, Any],
    status: int,
    ts_ms: int,
    *,
    outputs: dict[str, Any] | None,
    prev: int,
    msg: str | None = None,
) -> bool:
    """Append every local status change with its timestamp for later Brain replay."""
    st = int(status)
    if st == prev:
        return False
    q = step.setdefault("sync_queue", [])
    if not isinstance(q, list):
        q = []
        step["sync_queue"] = q
    if q and int(q[-1].get("status") or 0) == st:
        return False
    try:
        seq = int(step.get("sync_seq") or 0) + 1
    except (TypeError, ValueError):
        seq = 1
    step["sync_seq"] = seq
    item: dict[str, Any] = {"status": st, "ts_ms": int(ts_ms), "seq": seq}
    if outputs and st in (STEP_SUCCEEDED, STEP_FAILED):
        item["outputs"] = dict(outputs)
    note = str(msg or "").strip()
    if note:
        item["msg"] = note
    q.append(item)
    if len(q) > _SYNC_QUEUE_CAP:
        dropped = len(q) - _SYNC_QUEUE_CAP
        del q[:dropped]
        log.warning("ledger: dropped %s oldest unsynced step events (cap=%s)", dropped, _SYNC_QUEUE_CAP)
    return True


def _merge_foreign_outputs(local: dict[str, Any], peeked: dict[str, Any]) -> bool:
    """Copy Brain step_outputs we do not already have (cross-edge predecessors)."""
    bags = peeked.get("step_outputs")
    if not isinstance(bags, dict) or not bags:
        return False
    dest = local.setdefault("step_outputs", {})
    if not isinstance(dest, dict):
        dest = {}
        local["step_outputs"] = dest
    changed = False
    for key, val in bags.items():
        if not isinstance(val, dict):
            continue
        old = dest.get(key) if isinstance(dest.get(key), dict) else None
        if old is None:
            dest[key] = dict(val)
            changed = True
            continue
        merged = dict(old)
        for k, v in val.items():
            if k not in merged:
                merged[k] = v
                changed = True
        dest[key] = merged
    return changed


def _peek_step_status(step: dict[str, Any]) -> int | None:
    raw = step.get("status", step.get("step_status"))
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _merge_foreign_progress(
    local: dict[str, Any], peeked: dict[str, Any], edge_id: str
) -> bool:
    """Follow other nodes' step status/outputs. Never overwrite this edge's steps."""
    changed = _merge_foreign_outputs(local, peeked)
    eid = (edge_id or "").strip()
    peeked_plan = peeked.get("execution_plan")
    local_plan = local.get("execution_plan")
    if not eid or not isinstance(peeked_plan, list) or not isinstance(local_plan, list):
        return changed
    peek_by_n: dict[int, dict[str, Any]] = {}
    for src in peeked_plan:
        if not isinstance(src, dict):
            continue
        try:
            n = int(src.get("step") or 0)
        except (TypeError, ValueError):
            continue
        if n:
            peek_by_n[n] = src
    dest_bags = local.setdefault("step_outputs", {})
    if not isinstance(dest_bags, dict):
        dest_bags = {}
        local["step_outputs"] = dest_bags
    peek_bags = peeked.get("step_outputs")
    if not isinstance(peek_bags, dict):
        peek_bags = {}
    for step in local_plan:
        if not isinstance(step, dict):
            continue
        assigned = str(step.get("assigned_edge_id") or "").strip()
        if not assigned or assigned == eid:
            continue
        try:
            n = int(step.get("step") or 0)
        except (TypeError, ValueError):
            continue
        src = peek_by_n.get(n)
        if src is None:
            continue
        new_st = _peek_step_status(src)
        if new_st is not None:
            try:
                old_st = int(step.get("status", STEP_WAITING))
            except (TypeError, ValueError):
                old_st = STEP_WAITING
            if new_st != old_st:
                step["status"] = new_st
                changed = True
        note = str(src.get("msg") or "").strip()
        if note and str(step.get("msg") or "").strip() != note:
            step["msg"] = note
            changed = True
        bag: dict[str, Any] = {}
        raw_bag = peek_bags.get(str(n))
        if isinstance(raw_bag, dict):
            bag.update(raw_bag)
        src_out = src.get("outputs")
        if isinstance(src_out, dict):
            bag.update(src_out)
        photo = src.get("photo_url")
        if isinstance(photo, str) and photo.strip():
            bag.setdefault("photo_url", photo.strip())
        if bag:
            old_bag = dest_bags.get(str(n)) if isinstance(dest_bags.get(str(n)), dict) else {}
            merged = {**old_bag, **bag}
            if merged != old_bag:
                dest_bags[str(n)] = merged
                step["outputs"] = dict(merged)
                changed = True
    return changed


def _plan_caps(rec: dict[str, Any]) -> tuple[tuple[int, str], ...]:
    out: list[tuple[int, str]] = []
    for step in rec.get("execution_plan") or []:
        if not isinstance(step, dict):
            continue
        try:
            n = int(step.get("step") or 0)
        except (TypeError, ValueError):
            continue
        cap = str(step.get("capability") or "").strip()
        out.append((n, cap))
    return tuple(out)


def _intent_base_ms(rec: dict[str, Any]) -> int | None:
    raw = rec.get("intent_base_time")
    if raw is None:
        raw = rec.get("base_time")
    try:
        if raw is None or raw == "":
            return None
        return int(raw)
    except (TypeError, ValueError):
        return None


def _is_recycled_brain_intent(local: dict[str, Any], peeked: dict[str, Any]) -> bool:
    """Brain reuses integer ids after restart; a new job must replace the old row."""
    peek_base = _intent_base_ms(peeked)
    local_base = _intent_base_ms(local)
    if peek_base is not None and local_base != peek_base:
        return True
    local_wire = str(local.get("status") or "").strip().lower()
    if local_wire not in ("succeeded", "failed"):
        return False
    peek_text = str(peeked.get("text") or "").strip()
    local_text = str(local.get("text") or "").strip()
    if peek_text and peek_text != local_text:
        return True
    peek_caps = _plan_caps(peeked)
    local_caps = _plan_caps(local)
    return bool(peek_caps) and peek_caps != local_caps


def _recurring_series_open(rec: dict[str, Any], intent_id: str, now_ms: int) -> bool:
    plan = rec.get("execution_plan") or []
    if not isinstance(plan, list):
        return False
    for step in plan:
        if not isinstance(step, dict):
            continue
        timing = parse_execution_timing(step)
        if not timing.is_recurring:
            continue
        n = int(step.get("step") or 0)
        beat = int(step.get("beat") or get_beat(intent_id, n))
        gate = timing_gate(timing, now_ms, beat)
        if not gate.terminal:
            return True
    return False


def _record_has_local_terminal_step(rec: dict[str, Any]) -> bool:
    """True when any step is already SUCCEEDED/FAILED locally."""
    for step in rec.get("execution_plan") or []:
        if not isinstance(step, dict):
            continue
        try:
            st = int(step.get("status", STEP_WAITING))
        except (TypeError, ValueError):
            st = STEP_WAITING
        if st in (STEP_SUCCEEDED, STEP_FAILED):
            return True
    return False


def _record_has_remaining_work(
    rec: dict[str, Any],
    intent_id: str,
    edge_id: str,
    now_ms: int,
) -> bool:
    """True only when this edge still has a locally assigned runnable step.

    Intent #838 was delayed ~12s because the ledger kept 11 cross-edge
    intents (camera on phone, etc.) as "open". Empty assignee or foreign
    assignee must not keep the control loop in busy-poll / enqueue thrash.
    Steps blocked on unfinished predecessors also do not count — they cannot
    run until the other edge finishes.
    """
    plan = rec.get("execution_plan") or []
    if not isinstance(plan, list) or not plan:
        return False
    eid = (edge_id or "").strip()
    if not eid:
        return False
    ordered = sorted(
        [s for s in plan if isinstance(s, dict)],
        key=lambda s: int(s.get("step") or 0),
    )
    for step in ordered:
        assigned = str(step.get("assigned_edge_id") or "").strip()
        if assigned != eid:
            continue
        n = int(step.get("step") or 0)
        # Blocked on a predecessor (often another edge) — not local work yet.
        preds_ok = True
        for pred in ordered:
            pn = int(pred.get("step") or 0)
            if pn >= n:
                break
            try:
                pst = int(pred.get("status", STEP_WAITING))
            except (TypeError, ValueError):
                pst = STEP_WAITING
            if pst != STEP_SUCCEEDED:
                preds_ok = False
                break
        if not preds_ok:
            continue
        timing = parse_execution_timing(step)
        beat = int(step.get("beat") or get_beat(intent_id, n))
        if timing.is_recurring:
            gate = timing_gate(timing, now_ms, beat)
            if not gate.terminal:
                return True
            continue
        try:
            st = int(step.get("status", STEP_WAITING))
        except (TypeError, ValueError):
            st = STEP_WAITING
        if st in (STEP_WAITING, STEP_RUNNING):
            return True
    return False
