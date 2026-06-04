"""Pydantic v2 inter-agent contracts.

Every object that crosses an agent boundary or a pipeline stage is defined here,
not inside the agent modules. One home means:
  - no circular imports (Mapping depends on Extract's output type, etc.)
  - the language seam is visible: human-language fields (scope_description,
    raw_text, section_title) are isolated so a translation layer can wrap them
    later without touching agent logic.
"""
