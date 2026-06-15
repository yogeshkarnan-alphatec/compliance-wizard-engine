"""RDF metadata handling for CELLAR works.

When a WORK URI is fetched with no ``Accept`` header, CELLAR returns an RDF/XML
metadata graph (not the legal text). This module extracts what that graph is
useful for:

  * ``find_expression_uri`` — the language expression URI needed to fetch text.
  * ``extract_relationships`` — the amendment / citation / repeal edges that
    describe how a work relates to the rest of EU law.
  * ``extract_metadata`` — best-effort publication / entry-into-force dates + OJ
    reference (added for the compliance pipeline's Fetch step).
  * ``celex_from_uri`` — pull a CELEX id out of a CELLAR work/resource URI.
"""

import re
from xml.etree import ElementTree as ET

RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
CDM_NS = "http://publications.europa.eu/ontology/cdm#"

# Relationship predicates worth surfacing for a compliance tool.
RELATIONSHIP_PREDICATES = (
    "work_amends_work",
    "work_amended_by_work",
    "work_repeals_work",
    "work_repealed_by_work",
    "work_cites_work",
    "work_related_to_work",
)


def find_expression_uri(rdf_text, language="ENG"):
    """Return the language expression URI from an RDF metadata graph.

    The expression URI encodes the language (e.g. ``.ENG``), so no language
    parameter is needed when fetching the manifestation from it.

    Args:
        rdf_text (str): The RDF/XML response body.
        language (str): ISO 639-3 language code, e.g. ``ENG``, ``DEU``, ``FRA``.

    Returns:
        str | None: The first matching expression URI, or None if not found.
    """
    matches = sorted(set(re.findall(
        r"http://publications\.europa\.eu/resource/[^\s\"<>]+\." + re.escape(language),
        rdf_text,
    )))
    return matches[0] if matches else None


def extract_relationships(rdf_bytes):
    """Extract relationship edges (amends, repeals, cites, …) from an RDF graph.

    Args:
        rdf_bytes (bytes): The raw RDF/XML response content.

    Returns:
        dict[str, list[str]]: Predicate name → list of related work URIs.
    """
    root = ET.fromstring(rdf_bytes)
    edges = {pred: [] for pred in RELATIONSHIP_PREDICATES}

    for desc in root.iter(f"{{{RDF_NS}}}Description"):
        for pred in RELATIONSHIP_PREDICATES:
            for el in desc.findall(f"{{{CDM_NS}}}{pred}"):
                uri = el.get(f"{{{RDF_NS}}}resource")
                if uri:
                    edges[pred].append(uri)

    return {pred: uris for pred, uris in edges.items() if uris}


# --- additions for the compliance pipeline ---------------------------------

# CELEX ids look like 32014L0035 (sector digit + 4-digit year + descriptor + number).
_CELEX_IN_URI = re.compile(r"(3\d{4}[A-Z]{1,2}\d{3,4})")

# CDM predicate local-names that may carry dates / OJ reference. Names are
# best-effort and should be confirmed against a real RDF sample; the function
# never raises so a miss simply yields None (Fetch must never fail the pipeline).
_DATE_PUBLICATION_HINTS = ("date_publication", "datepublication", "date_document")
_DATE_EIF_HINTS = ("entry-into-force", "entry_into_force", "date_entry")
_OJ_HINTS = ("official-journal", "official_journal", "published_in")


def celex_from_uri(uri):
    """Best-effort: pull a CELEX id out of a CELLAR work/resource URI, else None."""
    m = _CELEX_IN_URI.search(uri or "")
    return m.group(1) if m else None


def extract_metadata(rdf_bytes):
    """Best-effort publication / entry-into-force dates + OJ reference.

    Returns ``{publication_date, entry_into_force_date, oj_reference}`` with None
    for anything not found. Defensive: any parse issue yields an all-None dict.
    """
    out = {"publication_date": None, "entry_into_force_date": None, "oj_reference": None}
    try:
        root = ET.fromstring(rdf_bytes)
    except (ET.ParseError, TypeError):
        return out

    for desc in root.iter(f"{{{RDF_NS}}}Description"):
        for child in list(desc):
            local = child.tag.split("}")[-1].lower()
            text = (child.text or "").strip()
            resource = child.get(f"{{{RDF_NS}}}resource")
            if text and any(h in local for h in _DATE_EIF_HINTS):
                out["entry_into_force_date"] = out["entry_into_force_date"] or text
            elif text and any(h in local for h in _DATE_PUBLICATION_HINTS):
                out["publication_date"] = out["publication_date"] or text
            if any(h in local for h in _OJ_HINTS):
                ref = text or resource
                if ref:
                    out["oj_reference"] = out["oj_reference"] or ref
    return out
