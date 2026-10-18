from __future__ import annotations

import re
import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def next_claim_id(existing: list[str]) -> str:
    nums = []
    for cid in existing:
        m = re.fullmatch(r"CLM-(\d+)", cid)
        if m:
            nums.append(int(m.group(1)))
    return f"CLM-{(max(nums) + 1 if nums else 1):04d}"
