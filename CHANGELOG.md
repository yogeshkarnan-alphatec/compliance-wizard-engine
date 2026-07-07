# Changelog

## 2026-07-07
- Wired the `AssessmentType` and `ProductionType` enums into the pipeline as a single source of truth — the Extract agent now constrains the LLM to their values and the Mapping agent normalizes to those same values — by [@yogeshkarnan-alphatec](https://github.com/yogeshkarnan-alphatec).
- Removed redundant, unreferenced code with no effect on the runtime or tests — the dead `EurLexAdapter` and `NationalPortalAdapter` modules, the orphaned `_CELEX` regex (and its now-dead `import re`), and the stale `SESSION_2026-06-22.md` notes — by [@yogeshkarnan-alphatec](https://github.com/yogeshkarnan-alphatec).
