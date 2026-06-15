"""Text/XHTML -> TextSegment list, parallel to the PDF ReadAgent.

Used when a document is acquired via the EUR-Lex engine (CELLAR returns XHTML/text,
not a PDF), so there are no page numbers or bounding boxes. Segmentation reuses the
same heading detection as the PDF reader so the downstream agents stay source-agnostic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from agents.read_agent import _HEADING
from schemas.read import ReadOutput, TextSegment


def segment_text(text: str, job_id: UUID, metadata_hints: dict | None = None) -> ReadOutput:
    """Split plain text (one block per line, as eurlex.get_document returns) into segments.

    Starts a new segment at each heading line (Article/Annex/Chapter/Section); text
    before the first heading becomes an untitled preamble segment. Pages/bbox are 0/None
    since XHTML has no layout coordinates.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    segments: list[TextSegment] = []
    cur: dict | None = None
    idx = 0

    def finish(c: dict, i: int) -> TextSegment:
        return TextSegment(
            section_title=c["title"], text=c["text"].strip(),
            page_start=0, page_end=0, bbox=None, segment_index=i,
        )

    for ln in lines:
        if _HEADING.match(ln[:120]):
            if cur is not None:
                segments.append(finish(cur, idx))
                idx += 1
            cur = {"title": ln[:120], "text": ln}
        elif cur is None:
            cur = {"title": None, "text": ln}
        else:
            cur["text"] += "\n" + ln

    if cur is not None:
        segments.append(finish(cur, idx))

    return ReadOutput(
        job_id=job_id, segments=segments,
        metadata_hints=metadata_hints or {}, extracted_at=datetime.now(timezone.utc),
    )
