"""eurlex — fetch EU legal documents from the CELLAR REST API by CELEX number.

Vendored from the user's "Eur-Lex API Pipeline" engine (CELLAR REST, no API key,
no scraping). Extended here with ``extract_metadata`` (dates / OJ reference) and
``celex_from_uri`` (work-URI -> CELEX) for the compliance pipeline's Fetch step.
"""

from .fetch import get_document, fetch_document, fetch_rdf
from .rdf import (
    find_expression_uri,
    extract_relationships,
    extract_metadata,
    celex_from_uri,
    is_celex,
)
from .search import search_documents

__all__ = [
    "get_document",
    "fetch_document",
    "fetch_rdf",
    "find_expression_uri",
    "extract_relationships",
    "extract_metadata",
    "celex_from_uri",
    "is_celex",
    "search_documents",
]
