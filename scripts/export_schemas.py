from __future__ import annotations

"""Export versioned JSON schemas for the pipeline's public contracts.

Contracts written to pipeline/schemas/:
  - content payload contracts (what each generator must produce)
  - structured-output contracts for the optional LLM stages

Run from the repo root or backend/:
    python scripts/export_schemas.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.content import CarouselPayload, ReelPayload, StaticPayload  # noqa: E402
from app.schemas.pipeline import (  # noqa: E402
    ClaimCandidateList,
    EvidenceAssessment,
    ResearchSynthesis,
    SafetyReview,
)

OUT_DIR = REPO_ROOT / "pipeline" / "schemas"

EXPORTS = {
    "carousel_payload": CarouselPayload,
    "static_payload": StaticPayload,
    "reel_payload": ReelPayload,
    "research_synthesis": ResearchSynthesis,
    "claim_candidate_list": ClaimCandidateList,
    "evidence_assessment": EvidenceAssessment,
    "safety_review": SafetyReview,
}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in EXPORTS.items():
        schema = model.model_json_schema(mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["title"] = model.__name__
        path = OUT_DIR / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path.relative_to(REPO_ROOT).as_posix())
    for w in written:
        print(f"wrote {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
