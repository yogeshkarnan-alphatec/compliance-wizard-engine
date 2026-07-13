"""JSON API — the Compliance Wizard query. Mirrors ui/routes/wizard.py's programmatic endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from engine.wizard_matcher import query as run_query
from schemas.wizard import WizardQuery, WizardResult

router = APIRouter(prefix="/api")


@router.post("/wizard/query", response_model=list[WizardResult])
def wizard_query(wq: WizardQuery) -> list[WizardResult]:
    """{hs_code, product_attributes} -> [WizardResult]. Never silently drops a candidate."""
    return run_query(wq)
