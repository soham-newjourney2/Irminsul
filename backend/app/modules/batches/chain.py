"""Tamper-evidence hash chain for batch events. Not a blockchain.

hash_n = sha256(prev_hash + canonical_json(event fields)). Timestamps are normalised to
milliseconds (BSON precision) before hashing so stored events re-verify byte-for-byte.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

GENESIS_HASH = "0" * 64
HASHED_FIELDS = (
    "batch_id",
    "seq",
    "type",
    "actor_id",
    "actor_role",
    "event_time",
    "received_at",
    "source",
    "payload",
)


def to_ms(dt: datetime) -> datetime:
    dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=dt.microsecond // 1000 * 1000)


def _encode(value: Any) -> str:
    if isinstance(value, datetime):
        v = to_ms(value)
        return v.strftime("%Y-%m-%dT%H:%M:%S.") + f"{v.microsecond // 1000:03d}Z"
    if isinstance(value, ObjectId):
        return str(value)
    raise TypeError(f"Not hashable in chain: {type(value).__name__}")


def canonical(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_encode
    )


def event_hash(prev_hash: str, event: dict[str, Any]) -> str:
    content = {k: event.get(k) for k in HASHED_FIELDS}
    return hashlib.sha256((prev_hash + canonical(content)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    events: int
    head_hash: str
    first_invalid_seq: int | None = None
    reason: str | None = None


def verify_chain(events: list[dict[str, Any]], head_seq: int, head_hash: str) -> VerifyResult:
    """Events must be sorted by seq. Checks continuity, links, hashes, and the stored head."""
    prev = GENESIS_HASH
    for expected_seq, ev in enumerate(events):
        if ev.get("seq") != expected_seq:
            return VerifyResult(False, len(events), prev, expected_seq, "missing_or_reordered")
        if ev.get("prev_hash") != prev:
            return VerifyResult(False, len(events), prev, expected_seq, "broken_link")
        if event_hash(prev, ev) != ev.get("hash"):
            return VerifyResult(False, len(events), prev, expected_seq, "hash_mismatch")
        prev = ev["hash"]
    if head_seq != len(events) - 1 or head_hash != prev:
        return VerifyResult(False, len(events), prev, len(events), "head_mismatch")
    return VerifyResult(True, len(events), prev)
