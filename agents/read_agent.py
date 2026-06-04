"""Agent 1 — Read Agent.

Layout-aware PDF text extraction with PyMuPDF (fitz). Deterministic, no LLM.
Splits the document into logical segments (article / annex / chapter / section)
and preserves page numbers + a bounding box per segment so downstream provenance
("p.12, Art.3") and the Review UI's source-snippet view have real coordinates.

Why PyMuPDF: it preserves layout and per-block page coordinates, which pdfplumber
does not expose as cleanly — and those coordinates are the spec's source-tracking
requirement.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

import fitz  # PyMuPDF

from schemas.read import ReadOutput, TextSegment

# Heading detection. English-only for now; this regex is the single language
# assumption in this agent, isolated here so a translation layer can swap it.
_HEADING = re.compile(
    r"^\s*(article\s+\d+|annex\s+[ivxlcdm0-9]+|chapter\s+[ivxlcdm0-9]+|section\s+\d+|"
    r"art\.?\s*\d+)\b",
    re.IGNORECASE,
)


class ReadAgent:
    name = "read"

    def run(self, file_path: str, job_id: UUID, metadata_hints: dict | None = None) -> ReadOutput:
        doc = fitz.open(file_path)
        try:
            blocks = self._extract_blocks(doc)
        finally:
            doc.close()
        segments = self._segment(blocks)
        return ReadOutput(
            job_id=job_id,
            segments=segments,
            metadata_hints=metadata_hints or {},
            extracted_at=datetime.now(timezone.utc),
        )

    def _extract_blocks(self, doc: "fitz.Document") -> list[dict]:
        """Flatten the document into ordered text blocks with page + bbox."""
        out: list[dict] = []
        for pno in range(doc.page_count):
            page = doc[pno]
            for b in page.get_text("blocks"):
                # block tuple: (x0, y0, x1, y1, text, block_no, block_type)
                x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
                text = (text or "").strip()
                if text:
                    out.append({"page": pno + 1, "bbox": (x0, y0, x1, y1), "text": text})
        return out

    def _segment(self, blocks: list[dict]) -> list[TextSegment]:
        """Group blocks into segments, starting a new one at each heading."""
        segments: list[TextSegment] = []
        cur: dict | None = None
        idx = 0

        def finish(c: dict, i: int) -> TextSegment:
            return TextSegment(
                section_title=c["title"],
                text=c["text"].strip(),
                page_start=c["page_start"],
                page_end=c["page_end"],
                bbox=c["bbox"],
                segment_index=i,
            )

        for b in blocks:
            first_line = b["text"].splitlines()[0][:120] if b["text"] else ""
            if _HEADING.match(first_line):
                if cur is not None:
                    segments.append(finish(cur, idx))
                    idx += 1
                cur = {
                    "title": first_line.strip(),
                    "text": b["text"],
                    "page_start": b["page"],
                    "page_end": b["page"],
                    "bbox": b["bbox"],
                }
            elif cur is None:
                # Preamble before the first heading becomes an untitled segment.
                cur = {
                    "title": None,
                    "text": b["text"],
                    "page_start": b["page"],
                    "page_end": b["page"],
                    "bbox": b["bbox"],
                }
            else:
                cur["text"] += "\n" + b["text"]
                cur["page_end"] = b["page"]

        if cur is not None:
            segments.append(finish(cur, idx))
        return segments
