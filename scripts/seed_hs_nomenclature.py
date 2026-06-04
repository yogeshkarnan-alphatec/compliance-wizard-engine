"""One-time import of HS / CN nomenclature reference data.

Reads a CSV (default: data/hs_nomenclature_seed.csv) and upserts rows into the
hs_nomenclature table. The bundled CSV is a representative sample; to load the
full published WCO 6-digit / EU CN 8-digit list, point --csv at that file using
the same columns: hs_code,description,level,parent_code,source.

Idempotent: re-running updates existing rows (matched on hs_code) and inserts new
ones, so it is safe to run after extending the CSV.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import HsNomenclature
from db.session import session_scope

DEFAULT_CSV = Path(__file__).resolve().parents[1] / "data" / "hs_nomenclature_seed.csv"


def seed(csv_path: Path) -> int:
    rows: list[dict] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            code = row["hs_code"].strip()
            if not code:
                continue
            rows.append(
                {
                    "hs_code": code,
                    "description": (row.get("description") or "").strip() or None,
                    "level": int(row["level"]),
                    "parent_code": (row.get("parent_code") or "").strip() or None,
                    "source": (row.get("source") or "WCO").strip(),
                }
            )

    if not rows:
        return 0

    with session_scope() as s:
        # ON CONFLICT (hs_code) DO UPDATE — Postgres upsert keeps the import idempotent.
        stmt = pg_insert(HsNomenclature).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["hs_code"],
            set_={
                "description": stmt.excluded.description,
                "level": stmt.excluded.level,
                "parent_code": stmt.excluded.parent_code,
                "source": stmt.excluded.source,
            },
        )
        s.execute(stmt)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed HS/CN nomenclature reference data")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()
    n = seed(args.csv)
    print(f"Seeded/updated {n} HS nomenclature row(s) from {args.csv}")


if __name__ == "__main__":
    main()
