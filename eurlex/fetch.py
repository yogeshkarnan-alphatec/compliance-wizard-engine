"""The fetch pipeline: CELEX number -> RDF -> expression URI -> XHTML -> text.

Two entry points:

  * ``get_document``  — fetch and return text + raw artifacts in memory.
  * ``fetch_document`` — fetch and persist everything into a per-CELEX folder
    (``rdf.xml``, ``source.xhtml``, ``text.txt``, ``meta.json``), caching the
    expression URI in ``meta.json`` so the ~60 MB RDF graph is fetched only once.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from .rdf import find_expression_uri

CELLAR_RESOURCE = "http://publications.europa.eu/resource/celex/{celex}"
TEXT_TAGS = ("p", "li", "h1", "h2", "h3", "h4")


def _extract_text(xhtml_text):
    """Extract paragraph/heading text from an XHTML document, one block per line."""
    xhtml = xhtml_text.replace(' xmlns="http://www.w3.org/1999/xhtml"', "")
    try:
        root = ET.fromstring(xhtml)
    except ET.ParseError:
        return None  # caller falls back to raw text

    paragraphs = []
    for elem in root.iter():
        if elem.tag in TEXT_TAGS:
            text = "".join(elem.itertext()).strip()
            if text:
                paragraphs.append(text)
    return "\n".join(paragraphs)


def get_document(celex, language="ENG", session=None, expression_uri=None):
    """Fetch a EU legal document by CELEX number.

    Args:
        celex (str): CELEX number, e.g. ``"32016R0679"``.
        language (str): ISO 639-3 language code. Defaults to ``ENG``.
        session (requests.Session | None): Reused HTTP session, optional.
        expression_uri (str | None): If known (cached), skip the RDF fetch.

    Returns:
        dict | None: ``{text, expression_uri, rdf, xhtml, language}`` on success,
        where ``rdf``/``xhtml`` are the raw response bytes. None if any step fails.
    """
    http = session or requests
    rdf_bytes = None

    # Step 1: fetch RDF metadata graph to discover the expression URI (unless cached).
    if expression_uri is None:
        rdf = http.get(
            CELLAR_RESOURCE.format(celex=celex),
            headers={},                      # no Accept header — returns RDF at WORK level
            params={"language": language},
            allow_redirects=True,
            timeout=60,
        )
        if rdf.status_code != 200:
            print(f"  [{celex}] RDF fetch failed: HTTP {rdf.status_code}")
            return None
        rdf_bytes = rdf.content

        expression_uri = find_expression_uri(rdf.text, language)
        if not expression_uri:
            print(f"  [{celex}] No .{language} expression URI found in RDF.")
            return None
        time.sleep(1)  # polite delay before the next request

    # Step 2: fetch the XHTML manifestation from the expression URI.
    doc = http.get(
        expression_uri,
        headers={"Accept": "application/xhtml+xml"},
        allow_redirects=True,
        timeout=60,
    )
    if doc.status_code != 200:
        print(f"  [{celex}] XHTML fetch failed: HTTP {doc.status_code}")
        return None

    # Step 3: extract text (fall back to raw XHTML if parsing fails).
    text = _extract_text(doc.text)
    if text is None:
        text = doc.text

    return {
        "text": text,
        "expression_uri": expression_uri,
        "rdf": rdf_bytes,
        "xhtml": doc.content,
        "language": language,
    }


def fetch_document(celex, out_root, title=None, eli=None, language="ENG",
                   session=None, refresh=False):
    """Fetch a document and persist it into ``out_root/<celex>/``.

    Writes ``rdf.xml`` (when fetched), ``source.xhtml``, ``text.txt`` and a
    ``meta.json`` provenance record. If ``meta.json`` already carries an
    ``expression_uri`` and ``refresh`` is False, the RDF step is skipped.

    Returns:
        dict | None: The meta.json record, or None on failure.
    """
    doc_dir = Path(out_root) / celex
    doc_dir.mkdir(parents=True, exist_ok=True)
    meta_path = doc_dir / "meta.json"

    cached_uri = None
    if meta_path.exists() and not refresh:
        cached_uri = json.loads(meta_path.read_text(encoding="utf-8")).get("expression_uri")

    result = get_document(celex, language=language, session=session,
                          expression_uri=cached_uri)
    if result is None:
        return None

    if result["rdf"] is not None:
        (doc_dir / "rdf.xml").write_bytes(result["rdf"])
    (doc_dir / "source.xhtml").write_bytes(result["xhtml"])
    (doc_dir / "text.txt").write_text(result["text"], encoding="utf-8")

    meta = {
        "celex": celex,
        "title": title,
        "eli": eli,
        "expression_uri": result["expression_uri"],
        "language": language,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "consolidated": celex.startswith("0"),
        "sizes": {
            "rdf_bytes": len(result["rdf"]) if result["rdf"] is not None else None,
            "xhtml_bytes": len(result["xhtml"]),
            "text_chars": len(result["text"]),
        },
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta
