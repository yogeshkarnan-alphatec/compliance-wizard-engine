# Changelog

## 2026-07-13
- Brought the React Review UI to full parity with the retired Jinja pages before removing them — Regulation Detail now renders the Fields "Reference / segment" column with the per-item provenance table (value / reference / segment / per-item confidence / status), the condition Type / Structured / enum / bool / raw-text columns, relationship confidence and HS-mapping status; the Review Queue regains its Jurisdiction column and the min/max confidence filters — by [@yogeshkarnan-alphatec](https://github.com/yogeshkarnan-alphatec).
- Removed the now-redundant server-rendered Jinja UI (`ui/templates`, `ui/routes`, `ui/deps.py`, `ui/static`) and its usages: the FastAPI app is JSON-API-only with the React SPA as the sole UI, the template-only pagination helpers (`page_url`, `PER_PAGE_OPTIONS`, `page_window`) and the `jinja2` dependency are gone, and the regulations-index test now exercises `/api/regulations` — by [@yogeshkarnan-alphatec](https://github.com/yogeshkarnan-alphatec).

## 2026-07-07
- Wired the `AssessmentType` and `ProductionType` enums into the pipeline as a single source of truth — the Extract agent now constrains the LLM to their values and the Mapping agent normalizes to those same values — by [@yogeshkarnan-alphatec](https://github.com/yogeshkarnan-alphatec).
- Removed redundant, unreferenced code with no effect on the runtime or tests — the dead `EurLexAdapter` and `NationalPortalAdapter` modules, the orphaned `_CELEX` regex (and its now-dead `import re`), and the stale `SESSION_2026-06-22.md` notes — by [@yogeshkarnan-alphatec](https://github.com/yogeshkarnan-alphatec).
