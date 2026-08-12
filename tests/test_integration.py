"""End-to-end integration: adapter → queue → agentic pipeline → engine → wizard.

The model is mocked at the chat_model seam; everything else is real (PDF parsing,
segmentation, mapping/validation, DB persistence, resolution engine, wizard query).
"""

from schemas.wizard import WizardQuery


def test_full_pipeline_then_wizard(mock_chat_model, sample_pdf, cleanup_regs, cleanup_jobs):
    # 1. Mock the agentic Extractor to return an LVD-style record (the Critic ACCEPTs by
    #    default). An uploaded PDF carries no CELEX, so the graph skips enrichment — no
    #    network stub needed; everything downstream (map/validate/persist/resolve) is real.
    from schemas.common import ExtractedField
    from schemas.extract import ExtractionResult, RawApplicabilityCondition

    mock_chat_model(ExtractionResult(
        scope_description=ExtractedField(value="electrical equipment", reference="Art.1",
                                         confidence=0.95, source_segment_index=0),
        hs_codes=[ExtractedField(value="8501.10", reference="Annex",
                                 confidence=0.9, source_segment_index=0)],
        applicability_conditions=[RawApplicabilityCondition(
            parameter_name="rated voltage vdc", operator="<", value="75", unit="V DC",
            condition_type="exclusion", reference="Art.1", confidence=0.9,
            raw_text="below 75 V DC")],
        regulation_mentions=["Directive 9999/1/EU"],  # fictional id — see cleanup note below
    ))

    # 2. Ingest via the adapter (writes the jobs row), then run the pipeline.
    from adapters.upload import UploadAdapter
    from pipeline import run_pipeline

    pdf = sample_pdf("Article 1 Scope\nApplies to electrical equipment. Not below 75 V DC.")
    job = UploadAdapter().fetch(pdf)
    cleanup_jobs.append(job.id)
    source_id = f"UPLOAD:{job.id}"
    # "39999L0001" is the fictional stub from the mention above — never a real CELEX, so
    # teardown can't delete genuine ingested data (the suite shares the real Postgres).
    cleanup_regs.extend([source_id, "39999L0001"])

    run_pipeline(job.id)

    # 3. Persisted regulation with fields + the structured condition + HS map.
    from sqlalchemy import func, select
    from db.models import ApplicabilityCondition, Regulation, RegulationField
    from db.session import session_scope

    with session_scope() as s:
        reg = s.execute(select(Regulation).where(Regulation.source_id == source_id)).scalar_one()
        reg_id = reg.id
        assert reg.ingestion_status == "ingested"
        n_fields = s.scalar(select(func.count()).select_from(RegulationField)
                            .where(RegulationField.regulation_id == reg_id))
        n_conds = s.scalar(select(func.count()).select_from(ApplicabilityCondition)
                           .where(ApplicabilityCondition.regulation_id == reg_id))
        assert n_fields >= 2 and n_conds == 1

    # 4. Wizard reflects the LVD exclusion logic end-to-end.
    from engine.wizard_matcher import query

    def status(attrs):
        res = [r for r in query(WizardQuery(hs_code="8501.10", product_attributes=attrs))
               if r.regulation_id == reg_id]
        return res[0]

    excluded = status({"rated_voltage_vdc": 24})
    assert excluded.applicability_status == "EXCLUDED"
    assert any("HS match" in e for e in excluded.evidence_references)
    assert status({"rated_voltage_vdc": 230}).applicability_status == "APPLIES"
    possibly = status({})
    assert possibly.applicability_status == "POSSIBLY_APPLIES"
    assert possibly.missing_attributes == ["rated_voltage_vdc"]
