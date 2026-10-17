"""Quarantined extractor (invariant 2). Untrusted content (emails, PDFs, invoice photos, uploads) goes only here.

The extractor has no tools. It returns Pydantic-validated fields (enums, IDs, fact refs, validated short
strings), flags instruction-like text, and marks every extracted value provenance="untrusted" (invariant 3).
"""
