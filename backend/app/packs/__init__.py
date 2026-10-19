"""Skill Packs: one skill.md file per kind of business (skills/grocery.skill.md, skills/fashion.skill.md ...), whose
frontmatter is validated by the Pydantic schema in schema.py, compiled by skill.py and loaded by loader.py.

A pack changes, on the same ledger: categories, forecast seasonality (via Pack.engine_doc()), KPIs and healthy
ranges (benchmarks.py), leak detectors registered by name (registry.py, detectors.py, leaks.py), financing fit
(financing.py) and readiness weights (readiness.py). Packs are config only: they cannot add code or actions.
"""
