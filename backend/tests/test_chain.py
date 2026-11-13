"""Hash-chain unit tests: valid chains verify; any tampering is detected."""

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId

from backend.app.modules.batches.chain import GENESIS_HASH, canonical, event_hash, verify_chain


def _chain(n: int = 4) -> tuple[list[dict[str, Any]], int, str]:
    batch_id = ObjectId()
    t0 = datetime(2026, 11, 13, 10, 0, 0, 123456, tzinfo=UTC)
    prev = GENESIS_HASH
    events = []
    for i in range(n):
        ev: dict[str, Any] = {
            "batch_id": batch_id,
            "seq": i,
            "type": "created" if i == 0 else "listed",
            "actor_id": ObjectId(),
            "actor_role": "farmer",
            "event_time": t0 + timedelta(minutes=i),
            "received_at": t0 + timedelta(minutes=i),
            "source": "user",
            "payload": {"qty_kg": 1000 - i, "note": "আলু"},
            "prev_hash": prev,
        }
        ev["hash"] = event_hash(prev, ev)
        prev = ev["hash"]
        events.append(ev)
    return events, n - 1, prev


def test_valid_chain_verifies() -> None:
    events, head_seq, head = _chain()
    result = verify_chain(events, head_seq, head)
    assert result.valid
    assert result.events == 4


def test_millisecond_normalisation_survives_bson_round_trip() -> None:
    events, head_seq, head = _chain()
    stored = copy.deepcopy(events)
    for ev in stored:  # BSON keeps milliseconds only
        for k in ("event_time", "received_at"):
            ev[k] = ev[k].replace(microsecond=ev[k].microsecond // 1000 * 1000)
    assert verify_chain(stored, head_seq, head).valid


def test_canonical_is_order_independent() -> None:
    assert canonical({"b": 1, "a": [1, 2]}) == canonical({"a": [1, 2], "b": 1})


def test_tampered_payload_detected() -> None:
    events, head_seq, head = _chain()
    events[2]["payload"]["qty_kg"] = 1
    r = verify_chain(events, head_seq, head)
    assert not r.valid
    assert (r.first_invalid_seq, r.reason) == (2, "hash_mismatch")


def test_recomputed_hash_breaks_next_link() -> None:
    events, head_seq, head = _chain()
    events[1]["payload"]["qty_kg"] = 1
    events[1]["hash"] = event_hash(events[1]["prev_hash"], events[1])
    r = verify_chain(events, head_seq, head)
    assert (r.valid, r.first_invalid_seq, r.reason) == (False, 2, "broken_link")


def test_deleted_middle_event_detected() -> None:
    events, head_seq, head = _chain()
    del events[1]
    r = verify_chain(events, head_seq, head)
    assert (r.valid, r.first_invalid_seq, r.reason) == (False, 1, "missing_or_reordered")


def test_deleted_last_event_detected_by_head() -> None:
    events, head_seq, head = _chain()
    events.pop()
    r = verify_chain(events, head_seq, head)
    assert (r.valid, r.reason) == (False, "head_mismatch")


def test_changed_actor_or_time_detected() -> None:
    events, head_seq, head = _chain()
    events[0]["event_time"] += timedelta(days=1)
    assert not verify_chain(events, head_seq, head).valid
