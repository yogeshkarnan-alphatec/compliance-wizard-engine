"""Compliance Wizard query endpoint — POST /wizard/query (JSON API) + a form UI.

POST /wizard/query : the spec's programmatic endpoint. Accepts a WizardQuery JSON
body, returns list[WizardResult] JSON.

GET /wizard, POST /wizard : a minimal server-rendered form so a human can run a
query without a separate client. The form posts product_attributes as a JSON
object in a textarea (no JS, no build step).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request

from engine.wizard_matcher import query as run_query
from schemas.wizard import WizardQuery, WizardResult
from ui.deps import TEMPLATES

router = APIRouter()


@router.post("/wizard/query", response_model=list[WizardResult])
def wizard_query(wq: WizardQuery) -> list[WizardResult]:
    """Programmatic JSON endpoint: {hs_code, product_attributes} -> [WizardResult]."""
    return run_query(wq)


@router.get("/wizard")
def wizard_form(request: Request):
    return TEMPLATES.TemplateResponse(
        request, "wizard.html", {"results": None, "hs_code": "", "attrs_json": "{}", "error": None}
    )


@router.post("/wizard")
def wizard_form_submit(request: Request, hs_code: str = Form(...), product_attributes: str = Form("{}")):
    error = None
    results = None
    try:
        attrs = json.loads(product_attributes or "{}")
        if not isinstance(attrs, dict):
            raise ValueError("product_attributes must be a JSON object")
        results = run_query(WizardQuery(hs_code=hs_code, product_attributes=attrs))
    except (json.JSONDecodeError, ValueError) as exc:
        error = f"Invalid product_attributes JSON: {exc}"
    return TEMPLATES.TemplateResponse(
        request,
        "wizard.html",
        {"results": results, "hs_code": hs_code, "attrs_json": product_attributes, "error": error},
    )
