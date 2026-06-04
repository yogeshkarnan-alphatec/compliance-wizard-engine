"""Seed the DB-backed controlled vocabularies from the data/*.json files.

The JSON files are the SEED; the DB tables (product_attributes,
certification_bodies, certification_body_aliases) are the runtime source of truth
(the Review UI extends them live). This loader is idempotent — matched on the
unique natural keys (attribute_name, canonical_name, alias) — so it can be re-run
after editing the JSON without creating duplicates.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config import CERT_BODY_ALIASES_SEED, PRODUCT_ATTRIBUTES_SEED
from db.models import CertificationBody, CertificationBodyAlias, ProductAttribute
from db.session import session_scope


def seed_product_attributes() -> int:
    data = json.loads(PRODUCT_ATTRIBUTES_SEED.read_text(encoding="utf-8"))
    attrs = data["attributes"]
    rows = [
        {
            "attribute_name": name,
            "unit": spec.get("unit"),
            "value_type": spec["type"],
            "enum_values": spec.get("values"),
            "added_by": "seed",
        }
        for name, spec in attrs.items()
    ]
    with session_scope() as s:
        stmt = pg_insert(ProductAttribute).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["attribute_name"],
            set_={
                "unit": stmt.excluded.unit,
                "value_type": stmt.excluded.value_type,
                "enum_values": stmt.excluded.enum_values,
            },
        )
        s.execute(stmt)
    return len(rows)


def seed_certification_bodies() -> tuple[int, int]:
    data = json.loads(CERT_BODY_ALIASES_SEED.read_text(encoding="utf-8"))
    bodies = data["bodies"]
    n_bodies = 0
    n_aliases = 0
    with session_scope() as s:
        for body in bodies:
            existing = s.execute(
                select(CertificationBody).where(
                    CertificationBody.canonical_name == body["canonical_name"]
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = CertificationBody(
                    canonical_name=body["canonical_name"],
                    body_type=body.get("body_type"),
                    jurisdiction=body.get("jurisdiction"),
                    identifier=body.get("identifier"),
                )
                s.add(existing)
                s.flush()
                n_bodies += 1
            else:
                existing.body_type = body.get("body_type")
                existing.jurisdiction = body.get("jurisdiction")
                existing.identifier = body.get("identifier")

            # Canonical name is also a usable alias for matching.
            for alias in {body["canonical_name"], *body.get("aliases", [])}:
                present = s.execute(
                    select(CertificationBodyAlias.id).where(CertificationBodyAlias.alias == alias)
                ).first()
                if present is None:
                    s.add(CertificationBodyAlias(alias=alias, canonical_body_id=existing.id))
                    n_aliases += 1
    return n_bodies, n_aliases


def main() -> None:
    n_attrs = seed_product_attributes()
    n_bodies, n_aliases = seed_certification_bodies()
    print(f"Seeded {n_attrs} product attribute(s).")
    print(f"Seeded {n_bodies} new certification body/bodies, {n_aliases} new alias(es).")


if __name__ == "__main__":
    main()
