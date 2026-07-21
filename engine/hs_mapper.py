"""Resolution Engine — Job 2: HS Code ↔ Regulation Mapping.

Lookup-table-driven matching of regulation HS codes against the hs_nomenclature
reference data, with a confidence-scored fuzzy fallback (e.g. an 8-digit code when
only the 6-digit parent is known). Exact matches auto-approve; anything fuzzy /
below threshold is routed to the Review UI (review_status='pending') rather than
guessed. Supports the reverse query the Compliance Wizard needs: given an HS code,
which regulations may apply.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.enums import MatchType, ReviewStatus
from db.models import HsNomenclature, HsRegulationMap
from db.session import session_scope

log = logging.getLogger(__name__)


def _digits(code: str) -> str:
    return re.sub(r"\D", "", code or "")


def map_regulation_hs_codes(regulation_id, hs_codes: list[str]) -> None:
    """Resolve each of a regulation's HS codes and write hs_regulation_map rows.

    Idempotent per regulation: prior machine guesses are cleared first, so a re-ingest
    whose HS set shrank stops surfacing the codes it dropped. This is the authoritative
    re-resolve entry point — map_inferred_hs_codes runs after it and stays additive.
    """
    with session_scope() as s:
        _clear_machine_mappings(s, regulation_id)
        for raw in hs_codes:
            code = _digits(raw)
            if len(code) < 6:
                _upsert(s, code or raw, regulation_id, 0.3, "fuzzy", "pending")
                continue
            if s.execute(select(HsNomenclature.hs_code).where(HsNomenclature.hs_code == code)).first():
                _upsert(s, code, regulation_id, 1.0, "exact", "auto-approved")
                continue
            # Fall back to the 6-digit parent if that exists in the nomenclature.
            six = code[:6]
            if s.execute(select(HsNomenclature.hs_code).where(HsNomenclature.hs_code == six)).first():
                _upsert(s, six, regulation_id, 0.7, "fuzzy", "pending")
                continue
            # Unknown code: keep it, low confidence, for reviewer adjudication.
            _upsert(s, code, regulation_id, 0.3, "fuzzy", "pending")


def map_inferred_hs_codes(regulation_id, candidates: list[dict]) -> int:
    """Persist LLM-inferred HS candidates as 'inferred', review-pending mappings.

    Additive and non-destructive: a code already mapped for this regulation (e.g. a
    literal 'exact' match) is left untouched, so inference can only ADD candidates,
    never downgrade a stronger match. Returns the number of new rows written.
    """
    if not candidates:
        return 0
    written = 0
    with session_scope() as s:
        for cand in candidates:
            code = _digits(cand.get("hs_code", ""))
            if len(code) < 6:
                continue
            exists = s.execute(
                select(HsRegulationMap.id).where(
                    HsRegulationMap.regulation_id == regulation_id,
                    HsRegulationMap.hs_code == code,
                )
            ).first()
            if exists:
                continue
            s.add(
                HsRegulationMap(
                    hs_code=code,
                    regulation_id=regulation_id,
                    confidence=cand.get("confidence", 0.3),
                    match_type="inferred",
                    review_status="pending",
                )
            )
            written += 1
    return written


def _clear_machine_mappings(s, regulation_id) -> None:
    """Delete this regulation's untouched machine guesses before re-resolving.

    Only rows the engine wrote and no reviewer has acted on: 'manual' rows and anything
    human-approved or rejected stay: those are a reviewer's decision, and a rejected row
    that we deleted would simply reappear as pending on the next ingest. This is the same
    line _upsert draws by keeping review_status out of its update set.
    """
    n = s.execute(
        delete(HsRegulationMap).where(
            HsRegulationMap.regulation_id == regulation_id,
            HsRegulationMap.reviewer_id.is_(None),
            HsRegulationMap.match_type != MatchType.MANUAL.value,
            HsRegulationMap.review_status.in_(
                [ReviewStatus.PENDING.value, ReviewStatus.AUTO_APPROVED.value]
            ),
        )
    ).rowcount
    if n:
        log.info("map_regulation_hs_codes: cleared %d stale machine mapping(s) for %s",
                 n, regulation_id)


def _upsert(s, hs_code, regulation_id, confidence, match_type, review_status) -> None:
    stmt = pg_insert(HsRegulationMap).values(
        hs_code=hs_code,
        regulation_id=regulation_id,
        confidence=confidence,
        match_type=match_type,
        review_status=review_status,
    )
    # On re-ingest, refresh confidence/match_type but DO NOT clobber a reviewer's
    # decision (review_status is intentionally excluded from the update set).
    stmt = stmt.on_conflict_do_update(
        constraint="uq_hs_regulation",
        set_={"confidence": stmt.excluded.confidence, "match_type": stmt.excluded.match_type},
    )
    s.execute(stmt)


def find_regulations_by_hs(hs_code: str) -> list[dict]:
    """Reverse query: regulations whose mapped HS codes match the given code.

    Returns one dict per regulation (best match kept):
    {regulation_id, confidence, match_type, matched_code, hs_review_status}.
    Includes fuzzy/prefix matches so the wizard never misses a candidate.
    """
    u = _digits(hs_code)
    with session_scope() as s:
        rows = s.execute(
            select(
                HsRegulationMap.regulation_id,
                HsRegulationMap.hs_code,
                HsRegulationMap.confidence,
                HsRegulationMap.match_type,
                HsRegulationMap.review_status,
            )
        ).all()

    best: dict = {}
    for reg_id, code, conf, mtype, rstatus in rows:
        score = _match_score(u, _digits(code), conf or 0.0)
        if score is None:
            continue
        cur = best.get(reg_id)
        if cur is None or score > cur["confidence"]:
            best[reg_id] = {
                "regulation_id": reg_id,
                "confidence": round(score, 3),
                "match_type": mtype,
                "matched_code": code,
                "hs_review_status": rstatus,
            }
    return list(best.values())


def _match_score(u: str, code: str, stored: float) -> float | None:
    """Score a user code against a mapped code. None = no match."""
    if not u or not code:
        return None
    if u == code:
        return stored  # exact
    if len(u) >= 6 and len(code) >= 6 and u[:6] == code[:6]:
        if u.startswith(code) or code.startswith(u):
            return stored * 0.85  # one is a prefix of the other (e.g. 6 vs 8 digit)
        return stored * 0.7  # share the 6-digit heading but diverge below
    return None
