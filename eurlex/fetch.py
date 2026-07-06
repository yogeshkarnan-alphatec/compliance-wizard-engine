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
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

from .rdf import find_expression_uri

CELLAR_RESOURCE = "http://publications.europa.eu/resource/celex/{celex}"
TEXT_TAGS = ("p", "li", "h1", "h2", "h3", "h4")

# Manifestation formats tried, in order, at the expression URI. XHTML is preferred
# (well-formed, parses as XML); older OJ documents (pre-~2004, e.g. 31993L0068) have
# no XHTML manifestation and 404, so we fall back to the text/html manifestation.
_XHTML_ACCEPT = "application/xhtml+xml"
_HTML_ACCEPT = "text/html"


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


class _HTMLTextExtractor(HTMLParser):
    """Flatten non-XML HTML to block text, one logical block per line.

    Used for the text/html fallback: the OJ HTML served for older documents is not
    well-formed XML (unbalanced/unclosed <p> tags are common), so ElementTree can't
    parse it and a nesting-depth approach mis-groups it. Instead we insert a line break
    at every block-level boundary and keep all text between them, then drop empty lines.
    This is robust to malformed nesting and preserves paragraph granularity (e.g. each
    'Article N' lands on its own line) so the downstream segmenter can split on headings.
    """

    _BREAK = set(TEXT_TAGS) | {"br", "div", "tr", "table"}
    _SKIP = {"script", "style", "head"}  # non-content: never emit their text

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_startendtag(self, tag, attrs):  # self-closing, e.g. <br/>
        if tag in self._BREAK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip > 0:
            self._skip -= 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_data(self, data):
        if self._skip == 0:
            self._parts.append(data)

    @property
    def text(self) -> str:
        lines = [ln.strip() for ln in "".join(self._parts).splitlines()]
        return "\n".join(ln for ln in lines if ln)


def _extract_html_text(html_text):
    """Extract block text from a non-XML HTML manifestation. Returns None if nothing found."""
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html_text)
    except Exception:  # noqa: BLE001 — malformed HTML: caller falls back to raw text
        return None
    return parser.text or None


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

    # Step 2: fetch the manifestation from the expression URI. Prefer XHTML; fall back
    # to text/html for older documents that have no XHTML manifestation (which 404).
    doc = None
    fmt = None
    for accept in (_XHTML_ACCEPT, _HTML_ACCEPT):
        resp = http.get(
            expression_uri,
            headers={"Accept": accept},
            allow_redirects=True,
            timeout=60,
        )
        if resp.status_code == 200:
            doc, fmt = resp, accept
            break
        print(f"  [{celex}] {accept} fetch failed: HTTP {resp.status_code}")
    if doc is None:
        return None

    # Step 3: extract text. XHTML parses as XML; the HTML fallback is not well-formed
    # XML, so use the HTML parser. Both fall back to raw response text as a last resort.
    if fmt == _XHTML_ACCEPT:
        text = _extract_text(doc.text) or doc.text
    else:
        text = _extract_html_text(doc.text) or doc.text

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
