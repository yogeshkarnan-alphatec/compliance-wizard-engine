"""SQLAlchemy 2.0 ORM models — the full relational schema.

Design notes (the WHY):
  - regulation_fields is EAV (one row per extracted value) so every value carries
    its own provenance + review_status. The Review UI's Field Detail view operates
    on a single row at a time; arrays (hs_codes, markings, standards) are simply
    multiple rows sharing a field_name. See db/enums.py for closed vocabularies.
  - applicability_conditions stores BOTH structured (min/max/enum/bool) and raw
    fallback (raw_text + is_structured=False) so an ambiguous clause becomes a
    wizard UNCERTAIN result rather than being silently dropped.
  - Enum columns use native_enum=False → a VARCHAR + CHECK IN(...) constraint,
    matching the spec's hand-written DDL while staying DRY with enums.py.
  - gen_random_uuid() is core in PostgreSQL 13+; no pgcrypto extension needed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from db import enums as e


class Base(DeclarativeBase):
    pass


def enum_col(enum_cls):
    """VARCHAR + CHECK IN(...) backed by a Python str-enum (stores .value).

    create_constraint=True emits the DB-level CHECK (the SQLAlchemy 2.0 default
    is False). The CHECK is named after the enum class, e.g. ReviewStatus →
    "reviewstatus"; reused across tables it's still unique per-table in Postgres.
    This keeps create_all() (used in tests) in parity with the Alembic migration.
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda ec: [m.value for m in ec],
        length=32,
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now(), nullable=False)


def _conf_check() -> CheckConstraint:
    # A fresh instance per table: a Constraint object can only be associated with
    # one Table, so this must NOT be a shared module-level singleton.
    return CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="confidence_range")


# ---------------------------------------------------------------------------
# regulations — one row per regulation/directive (real or stub)
# ---------------------------------------------------------------------------
class Regulation(Base):
    __tablename__ = "regulations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[str] = mapped_column(Text, unique=True)  # CELEX / national id, normalized
    title: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)  # LLM-extracted plain-English overview
    jurisdiction: Mapped[str | None] = mapped_column(Text)  # open vocab: EU/UK/EAEU/DE/...
    document_type: Mapped[str | None] = mapped_column(Text)
    publication_date: Mapped[date | None] = mapped_column()
    entry_into_force_date: Mapped[date | None] = mapped_column()
    oj_reference: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    ingestion_status: Mapped[str] = mapped_column(
        enum_col(e.IngestionStatus),
        default=e.IngestionStatus.QUEUED.value,
        server_default=text(f"'{e.IngestionStatus.QUEUED.value}'"),
    )
    created_by: Mapped[str | None] = mapped_column(Text)  # 'adapter' | 'resolution_engine'
    metadata_hints: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    fields: Mapped[list["RegulationField"]] = relationship(
        back_populates="regulation", cascade="all, delete-orphan"
    )
    conditions: Mapped[list["ApplicabilityCondition"]] = relationship(
        back_populates="regulation", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# regulation_fields — EAV taxonomy with per-value provenance (load-bearing)
# ---------------------------------------------------------------------------
class RegulationField(Base):
    __tablename__ = "regulation_fields"
    __table_args__ = (
        _conf_check(),
        Index("ix_regulation_fields_reg_field", "regulation_id", "field_name"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    regulation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE")
    )
    field_name: Mapped[str] = mapped_column(Text)  # controlled, e.g. 'scope_description', 'hs_code'
    value_text: Mapped[str | None] = mapped_column(Text)
    value_json: Mapped[dict | None] = mapped_column(JSONB)  # canonical structured values
    reference: Mapped[str | None] = mapped_column(Text)  # "p.12, Art.3(1)"
    confidence: Mapped[float | None] = mapped_column(Float)
    source_segment_index: Mapped[int | None] = mapped_column(Integer)  # → ReadOutput segment
    extracted_by: Mapped[str | None] = mapped_column(Text)
    mapped_by: Mapped[str | None] = mapped_column(Text)
    validated_at: Mapped[datetime | None] = mapped_column()
    review_status: Mapped[str] = mapped_column(
        enum_col(e.ReviewStatus),
        default=e.ReviewStatus.PENDING.value,
        server_default=text(f"'{e.ReviewStatus.PENDING.value}'"),
    )
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    regulation: Mapped["Regulation"] = relationship(back_populates="fields")


# ---------------------------------------------------------------------------
# applicability_conditions — structured + raw fallback (load-bearing)
# ---------------------------------------------------------------------------
class ApplicabilityCondition(Base):
    __tablename__ = "applicability_conditions"
    __table_args__ = (
        _conf_check(),
        Index("ix_appl_cond_reg", "regulation_id"),
        Index("ix_appl_cond_param", "parameter_name"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    regulation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE")
    )
    parameter_name: Mapped[str | None] = mapped_column(Text)  # normalized to product_attributes
    operator: Mapped[str | None] = mapped_column(enum_col(e.Operator))
    value_min: Mapped[float | None] = mapped_column(Float)
    value_max: Mapped[float | None] = mapped_column(Float)
    value_enum: Mapped[list | None] = mapped_column(JSONB)  # list[str]
    value_bool: Mapped[bool | None] = mapped_column()  # boolean attrs (has_radio_module)
    unit: Mapped[str | None] = mapped_column(Text)
    condition_type: Mapped[str] = mapped_column(enum_col(e.ConditionType))
    is_structured: Mapped[bool] = mapped_column(default=True)  # False ⇒ wizard UNCERTAIN
    raw_text: Mapped[str | None] = mapped_column(Text)  # original sentence, always kept
    reference: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    review_status: Mapped[str] = mapped_column(
        enum_col(e.ReviewStatus),
        default=e.ReviewStatus.PENDING.value,
        server_default=text(f"'{e.ReviewStatus.PENDING.value}'"),
    )
    created_at: Mapped[datetime] = _created_at()

    regulation: Mapped["Regulation"] = relationship(back_populates="conditions")


# ---------------------------------------------------------------------------
# hs_nomenclature — seeded HS/CN reference data
# ---------------------------------------------------------------------------
class HsNomenclature(Base):
    __tablename__ = "hs_nomenclature"

    id: Mapped[uuid.UUID] = _uuid_pk()
    hs_code: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    level: Mapped[int] = mapped_column(Integer)  # 6 / 8 / 10
    parent_code: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(enum_col(e.HsSource))
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# hs_regulation_map — resolved HS ↔ regulation links
# ---------------------------------------------------------------------------
class HsRegulationMap(Base):
    __tablename__ = "hs_regulation_map"
    __table_args__ = (
        _conf_check(),
        UniqueConstraint("hs_code", "regulation_id", name="uq_hs_regulation"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    hs_code: Mapped[str] = mapped_column(Text)
    regulation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE")
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    match_type: Mapped[str] = mapped_column(enum_col(e.MatchType))
    review_status: Mapped[str] = mapped_column(
        enum_col(e.ReviewStatus),
        default=e.ReviewStatus.PENDING.value,
        server_default=text(f"'{e.ReviewStatus.PENDING.value}'"),
    )
    reviewer_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# regulation_relationships — typed edge table (graph via recursive CTE)
# ---------------------------------------------------------------------------
class RegulationRelationship(Base):
    __tablename__ = "regulation_relationships"
    __table_args__ = (
        _conf_check(),
        UniqueConstraint(
            "source_reg_id", "target_reg_id", "relation_type", name="uq_relationship_edge"
        ),
        CheckConstraint("source_reg_id <> target_reg_id", name="no_self_edge"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_reg_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE")
    )
    target_reg_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulations.id", ondelete="CASCADE")
    )
    relation_type: Mapped[str] = mapped_column(enum_col(e.RelationType))
    reference: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(enum_col(e.RelationSource))
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# certification_bodies + aliases
# ---------------------------------------------------------------------------
class CertificationBody(Base):
    __tablename__ = "certification_bodies"

    id: Mapped[uuid.UUID] = _uuid_pk()
    canonical_name: Mapped[str] = mapped_column(Text, unique=True)
    body_type: Mapped[str | None] = mapped_column(enum_col(e.BodyType))
    jurisdiction: Mapped[str | None] = mapped_column(Text)
    identifier: Mapped[str | None] = mapped_column(Text)  # e.g. notified-body number
    created_at: Mapped[datetime] = _created_at()

    aliases: Mapped[list["CertificationBodyAlias"]] = relationship(
        back_populates="body", cascade="all, delete-orphan"
    )


class CertificationBodyAlias(Base):
    __tablename__ = "certification_body_aliases"

    id: Mapped[uuid.UUID] = _uuid_pk()
    alias: Mapped[str] = mapped_column(Text, unique=True)
    canonical_body_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("certification_bodies.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = _created_at()

    body: Mapped["CertificationBody"] = relationship(back_populates="aliases")


# ---------------------------------------------------------------------------
# jobs — the only handoff between adapters and the pipeline
# ---------------------------------------------------------------------------
class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status", "status"),)  # for SKIP LOCKED polling

    id: Mapped[uuid.UUID] = _uuid_pk()
    file_path: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)  # CELEX / national id
    jurisdiction: Mapped[str | None] = mapped_column(Text)
    metadata_hints: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(
        enum_col(e.JobStatus),
        default=e.JobStatus.QUEUED.value,
        server_default=text(f"'{e.JobStatus.QUEUED.value}'"),
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    claimed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    errors: Mapped[list["JobError"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobError(Base):
    __tablename__ = "job_errors"

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    stage: Mapped[str | None] = mapped_column(Text)  # which agent/stage failed
    error_message: Mapped[str | None] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()

    job: Mapped["Job"] = relationship(back_populates="errors")


# ---------------------------------------------------------------------------
# llm_audit_log — every prompt + response (never discarded)
# ---------------------------------------------------------------------------
class LlmAuditLog(Base):
    __tablename__ = "llm_audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")  # nullable: standalone engine calls
    )
    agent: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    prompt: Mapped[str | None] = mapped_column(Text)
    response: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# product_attributes — controlled vocabulary for applicability parameters
# (DB is source of truth; seeded from data/product_attributes.json)
# ---------------------------------------------------------------------------
class ProductAttribute(Base):
    __tablename__ = "product_attributes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    attribute_name: Mapped[str] = mapped_column(Text, unique=True)
    unit: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(enum_col(e.AttributeValueType))
    enum_values: Mapped[list | None] = mapped_column(JSONB)  # for value_type='enum'
    added_by: Mapped[str | None] = mapped_column(Text)  # 'seed' | 'review_ui'
    created_at: Mapped[datetime] = _created_at()
