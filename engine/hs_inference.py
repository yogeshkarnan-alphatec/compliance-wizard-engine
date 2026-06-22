"""Resolution Engine — infer candidate HS codes for a directive.

Framework directives (Low Voltage, EMC, Machinery, ...) almost never cite HS/CN
codes, so literal extraction finds none and the Compliance Wizard can't surface
them for a product. This proposes likely **6-digit** HS subheadings from the
directive's scope + summary via the audited LLM seam (llm_client → llm_audit_log),
then VALIDATES every proposal against the seeded hs_nomenclature so no invented code
survives. Survivors are returned confidence-scored for hs_regulation_map, where they
are written review_status='pending' — inference never auto-approves.
"""

from __future__ import annotations

import json
import logging
import re
from uuid import UUID

from sqlalchemy import select

import llm_client
from config import HS_INFERENCE_MAX_CODES
from db.models import HsNomenclature
from db.session import session_scope

log = logging.getLogger(__name__)

# Inferred matches are heuristic; cap their confidence so they always rank below a
# literal exact match and clearly read as "needs a human" in the review UI.
_MAX_INFERRED_CONFIDENCE = 0.6

_SYSTEM = (
    "You are a customs-classification assistant. Given the scope of an EU product "
    "regulation, identify the Harmonized System (HS) product categories the regulation "
    "most plausibly governs. Respond ONLY with a single JSON object. Propose 6-digit HS "
    "subheadings (the international WCO level). Be inclusive of the product families in "
    "scope but do not invent codes you are unsure about."
)


def infer_hs_codes(scope_text: str, summary: str | None = None, job_id: UUID | None = None) -> list[dict]:
    """Return [{hs_code, confidence}] of validated 6-digit candidates (possibly empty)."""
    context = "\n".join(p for p in (summary, scope_text) if p and p.strip()).strip()
    if not context:
        return []

    prompt = (
        "Regulation scope / summary:\n"
        f"{context}\n\n"
        "Return JSON: {\"hs_codes\": [{\"code\": \"<6-digit HS code>\", "
        "\"confidence\": <0..1>, \"reason\": \"<short justification>\"}]}. "
        f"Give at most {HS_INFERENCE_MAX_CODES} of the most relevant codes, most confident first."
    )
    resp = llm_client.complete(prompt, agent="hs_inference", job_id=job_id, json_mode=True)
    data = _loads(resp.text)
    raw = data.get("hs_codes") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []

    out: list[dict] = []
    seen: set[str] = set()
    with session_scope() as s:
        for item in raw:
            if not isinstance(item, dict):
                continue
            code6 = re.sub(r"\D", "", str(item.get("code", "")))[:6]
            if len(code6) < 6 or code6 in seen:
                continue
            # Validate against the seeded nomenclature — drop anything unknown.
            if not s.execute(
                select(HsNomenclature.hs_code).where(HsNomenclature.hs_code == code6)
            ).first():
                continue
            seen.add(code6)
            try:
                conf = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            conf = round(min(max(conf, 0.0), _MAX_INFERRED_CONFIDENCE), 3)
            out.append({"hs_code": code6, "confidence": conf})
            if len(out) >= HS_INFERENCE_MAX_CODES:
                break
    return out


def _loads(text: str) -> dict:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
