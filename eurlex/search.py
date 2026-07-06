"""Search EU legislation by title via the public CELLAR SPARQL endpoint.

The rest of this package fetches a document once you know its CELEX id. This module
covers the step before that: a human types a directive name, and we return matching
works (CELEX + title + type) so they can pick the right one to ingest. No API key,
no scraping — same contract as the CELLAR REST fetch.

Scope is deliberately narrowed to sector-3 legislation (Directives / Regulations /
Decisions) so the result list isn't drowned in court cases, opinions, and OJ-C
communications that also mention the search terms.
"""

from __future__ import annotations

import logging

import requests

from config import EURLEX_SEARCH_LIMIT, EURLEX_SPARQL_ENDPOINT

log = logging.getLogger(__name__)

# CELEX descriptor letter -> human document type (sector-3 legislation only).
_DESCRIPTOR_TO_TYPE = {"L": "Directive", "R": "Regulation", "D": "Decision"}

# Same shape the pipeline uses to recognise a CELEX: sector digit + 4-digit year +
# 1-2 letter descriptor + 3-4 digit number. Applied in SPARQL to keep results clean.
_CELEX_LEGISLATION = "^3[0-9]{4}[A-Z]{1,2}[0-9]{3,4}$"

# ISO 639-3 -> CELLAR language-authority URI.
_LANG_URI = "http://publications.europa.eu/resource/authority/language/{lang}"


def _escape(term: str) -> str:
    r"""Escape a term for embedding in a SPARQL double-quoted string literal.

    Backslash first (so we don't double-escape), then the quote. This is what keeps
    a user typing `"machinery"` or a stray `\` from breaking — or injecting into —
    the query.
    """
    return term.replace("\\", "\\\\").replace('"', '\\"')


def _build_query(query: str, limit: int, language: str) -> str:
    # One CONTAINS filter per whitespace token (AND semantics) so "machinery safety"
    # matches titles containing both words in any order, not the exact phrase.
    tokens = [t for t in query.split() if t]
    title_filters = "\n".join(
        f'  FILTER(CONTAINS(LCASE(STR(?title)), "{_escape(t.lower())}"))' for t in tokens
    )
    lang_uri = _LANG_URI.format(lang=language)
    return f"""PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?celex ?title WHERE {{
  ?work cdm:resource_legal_id_celex ?celex .
  ?exp cdm:expression_belongs_to_work ?work ;
       cdm:expression_uses_language <{lang_uri}> ;
       cdm:expression_title ?title .
{title_filters}
  FILTER(REGEX(STR(?celex), "{_CELEX_LEGISLATION}"))
}} ORDER BY DESC(?celex) LIMIT {int(limit)}"""


def search_documents(
    query: str,
    *,
    limit: int | None = None,
    language: str = "ENG",
    timeout: float = 30.0,
    session: requests.Session | None = None,
) -> list[dict]:
    """Return sector-3 EU legislation whose title matches every word in ``query``.

    Args:
        query: Free-text directive name, e.g. "machinery safety".
        limit: Max rows (defaults to EURLEX_SEARCH_LIMIT).
        language: ISO 639-3 language code for the title, default ENG.
        timeout: Per-request timeout in seconds.
        session: Optional reused/mocked requests session.

    Returns:
        ``[{"celex", "title", "document_type"}]``, newest CELEX first. Empty list
        for a blank query.

    Raises:
        RuntimeError: on network failure or a non-200 from the endpoint, so the
        caller can show "search unavailable" rather than a silent empty result.
    """
    query = (query or "").strip()
    if not query:
        return []
    limit = limit or EURLEX_SEARCH_LIMIT

    http = session or requests
    try:
        resp = http.get(
            EURLEX_SPARQL_ENDPOINT,
            params={
                "query": _build_query(query, limit, language),
                "format": "application/sparql-results+json",
            },
            headers={"Accept": "application/sparql-results+json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        log.warning("EUR-Lex search request failed: %s", exc)
        raise RuntimeError(f"EUR-Lex search is unavailable: {exc}") from exc

    if resp.status_code != 200:
        log.warning("EUR-Lex search HTTP %s for %r", resp.status_code, query)
        raise RuntimeError(f"EUR-Lex search returned HTTP {resp.status_code}.")

    try:
        bindings = resp.json()["results"]["bindings"]
    except (ValueError, KeyError) as exc:
        raise RuntimeError("EUR-Lex search returned an unexpected response.") from exc

    results: list[dict] = []
    for b in bindings:
        celex = b.get("celex", {}).get("value")
        title = b.get("title", {}).get("value", "")
        if not celex:
            continue
        descriptor = celex[5] if len(celex) > 5 else ""
        results.append({
            "celex": celex,
            "title": title,
            "document_type": _DESCRIPTOR_TO_TYPE.get(descriptor, "Other"),
        })
    return results
