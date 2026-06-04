"""Controlled vocabularies, defined once.

Why this file exists: the same enumerations appear in two places — SQLAlchemy
CHECK constraints (DB layer) and Pydantic Literals/validators (contract layer).
Defining them once here keeps the DB and the inter-agent contracts from drifting
apart. All members are str-valued so they serialize cleanly to JSON and TEXT.

These are CLOSED vocabularies (enum coercion targets). Deliberately NOT enums:
  - jurisdiction  (EU/UK/EAEU/DE/...) — open-ended, spec says do not hardcode
  - field_name    — large controlled list, lives in code as constants, not a CHECK
  - parameter_name — extensible via the product_attributes table at runtime
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """str-backed enum: member.value is the stored string; member is JSON-safe."""

    def __str__(self) -> str:  # so f-strings and SQL render the value, not "Class.MEMBER"
        return self.value


# --- Marking (spec: EAC | CE | Ex | UKCA) ----------------------------------
class Marking(StrEnum):
    EAC = "EAC"
    CE = "CE"
    EX = "Ex"
    UKCA = "UKCA"


# --- Conformity assessment / body / production -----------------------------
class AssessmentType(StrEnum):
    FIRST_PARTY = "1st-party"
    THIRD_PARTY = "3rd-party"


class BodyType(StrEnum):
    NOTIFIED = "notified"
    ACCREDITED = "accredited"
    CERTIFIED = "certified"


class ProductionType(StrEnum):
    SINGLE = "single"
    BATCH = "batch"
    SERIAL = "serial"


# --- Applicability conditions ----------------------------------------------
class ConditionType(StrEnum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


# Operators the wizard matcher knows how to evaluate. raw_text conditions that
# use anything outside this set are kept as is_structured=False → UNCERTAIN.
class Operator(StrEnum):
    GT = ">"
    LT = "<"
    GTE = ">="
    LTE = "<="
    EQ = "=="
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"


# --- Regulation relationships (typed edge table) ---------------------------
class RelationType(StrEnum):
    AMENDS = "amends"
    AMENDED_BY = "amended_by"
    REFERENCES = "references"
    SUPERSEDES = "supersedes"
    SUPERSEDED_BY = "superseded_by"
    RELATED = "related"


# Inverse pairs the resolution engine auto-maintains (A amends B ⇒ B amended_by A).
# RELATED and REFERENCES are their own inverse for our purposes.
RELATION_INVERSE: dict[RelationType, RelationType] = {
    RelationType.AMENDS: RelationType.AMENDED_BY,
    RelationType.AMENDED_BY: RelationType.AMENDS,
    RelationType.SUPERSEDES: RelationType.SUPERSEDED_BY,
    RelationType.SUPERSEDED_BY: RelationType.SUPERSEDES,
    RelationType.REFERENCES: RelationType.REFERENCES,
    RelationType.RELATED: RelationType.RELATED,
}


class RelationSource(StrEnum):
    TEXT_EXTRACTED = "text_extracted"
    API_SOURCED = "api_sourced"  # higher default confidence than text_extracted


# --- Review lifecycle ------------------------------------------------------
class ReviewStatus(StrEnum):
    PENDING = "pending"
    AUTO_APPROVED = "auto-approved"
    HUMAN_APPROVED = "human-approved"
    REJECTED = "rejected"


# --- Jobs queue ------------------------------------------------------------
class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


# --- Regulation ingestion lifecycle ----------------------------------------
class IngestionStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    INGESTED = "ingested"
    STUB = "stub"          # created by resolution engine for a not-yet-ingested mention
    FAILED = "failed"


# --- HS ↔ regulation match provenance --------------------------------------
class MatchType(StrEnum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    MANUAL = "manual"


# --- product_attributes value typing ---------------------------------------
class AttributeValueType(StrEnum):
    RANGE = "range"
    ENUM = "enum"
    BOOLEAN = "boolean"


# --- HS nomenclature source ------------------------------------------------
class HsSource(StrEnum):
    WCO = "WCO"        # 6-digit international
    EU_CN = "EU_CN"    # 8-digit Combined Nomenclature
