"""skill.md: the one file format for Skill Packs, built-in and uploaded alike (format: docs/skills/FORMAT.md).

A skill is a Markdown file. Its YAML frontmatter is the machine-readable pack (packs/schema.py); the Markdown body
describes the business type for the owner. `parse_skill` compiles the file into the Pack model the engine runs.

An uploaded skill is untrusted input, so compiling is also the security boundary:
- Strict schema: unknown fields, YAML aliases and non-plain values are rejected with one clear error per problem.
- Detectors are referenced by registered name only (registry.py); a skill configures thresholds, never adds code.
- Reserved keys (policy, tiers, caps, mandates, gateway, tools ...) are rejected anywhere in the file: those live
  in gateway/policy.yaml and owner-signed mandates, which no skill can reach (invariants 1 and 5).
- Text that reads like instructions to an AI is rejected in the frontmatter (IDs and labels can reach the planner)
  and flagged in the body (which is shown to the owner as data and never reaches the planner, invariant 2).
- Raw HTML is rejected, so the body renders as plain Markdown.
- An unverified skill runs with its planner-reachable labels (display name, category, KPI, detector, band and
  financing labels) rebuilt in code from its IDs: the planner never sees a word an uploader wrote. The skill's
  own wording stays in `authored`, for the owner's preview.

A skill signed with the library key (library_key.py) is "verified"; anything else is "community, unverified".
The sha256 covers the file without its `signature:` line, so the hash names the content and a verifier can
recompute it from the file; it is what onboarding records, the audit log carries and anchoring publishes.
"""

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from app.packs import library_key
from app.packs.registry import get_detector
from app.packs.schema import Pack
from app.quarantine.signals import scan

MAX_SKILL_BYTES = 64 * 1024
FRONTMATTER = re.compile(r"\A---\n(.*?\n)---(?:\n|\Z)", re.S)
SIGNATURE_LINE = re.compile(r"^signature:[^\n]*\n", re.M)
HTML = re.compile(r"<\s*/?\s*[a-z!?][^>]*>|javascript\s*:|\bon[a-z]+\s*=", re.I)
# Keys that would mean "change who may do what". None of them is part of the format; naming them explicitly gives
# a clearer refusal than "unknown field".
RESERVED_KEYS = frozenset({
    "policy", "policies", "tier", "tiers", "cap", "caps", "max_amount_minor", "mandate", "mandates", "gateway",
    "executor", "tool", "tools", "action", "actions", "allowlist", "allow_list", "approval", "approvals",
    "permissions", "prompt", "prompts", "system_prompt", "instructions",
})
_ID_FIELDS = ("categories", "fee_categories", "refund_categories")

Badge = Literal["verified", "community"]


class PackError(ValueError):
    """A pack or skill file is missing, unparseable or invalid."""


class SkillError(PackError):
    """A skill was refused. `errors` lists every problem found, one plain sentence each."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("invalid skill: " + "; ".join(errors[:8]))


@dataclass(frozen=True)
class Skill:
    pack: Pack  # what the app runs (planner-safe labels unless verified)
    authored: Pack  # the skill's own wording, for the owner only
    body: str  # Markdown description, for the owner only
    sha256: str
    verified: bool
    notices: tuple[str, ...]  # warnings for the owner (e.g. instruction-like text in the body)
    text: str  # the normalized file, as stored

    @property
    def badge(self) -> Badge:
        return "verified" if self.verified else "community"


def normalize(data: bytes | str) -> str:
    """UTF-8 text with LF line endings and no BOM; refuses oversize or non-UTF-8 files."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > MAX_SKILL_BYTES:
        raise SkillError([f"the file is larger than {MAX_SKILL_BYTES // 1024} KB"])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SkillError(["the file is not UTF-8 text"]) from None
    return text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")


def skill_content(text: str) -> tuple[str, str, str]:
    """(content without the signature line, frontmatter, body) of a normalized skill file."""
    m = FRONTMATTER.match(text)
    if not m:
        raise SkillError(["the file must start with YAML frontmatter between two '---' lines"])
    front = m.group(1)
    content = text[:m.start(1)] + SIGNATURE_LINE.sub("", front) + text[m.end(1):]
    return content, front, text[m.end():]


def skill_sha256(text: str) -> str:
    return hashlib.sha256(skill_content(text)[0].encode("utf-8")).hexdigest()


def _load_yaml(front: str) -> Any:
    try:
        for event in yaml.parse(front, Loader=yaml.SafeLoader):
            if isinstance(event, yaml.AliasEvent):
                raise SkillError(["YAML aliases (*name) are not allowed in a skill"])
        return yaml.safe_load(front)
    except yaml.YAMLError as e:
        raise SkillError([f"the frontmatter is not valid YAML: {str(e).splitlines()[0]}"]) from None


def _walk(value: Any, path: str = "") -> Iterator[tuple[str, Any, bool]]:
    """(path, item, is_key) for every mapping key and every scalar value."""
    if isinstance(value, dict):
        for k, v in value.items():
            here = f"{path}.{k}" if path else str(k)
            yield here, k, True
            yield from _walk(v, here)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, f"{path}.{i}")
    else:
        yield path, value, False


def _screen(doc: dict) -> list[str]:
    errors = []
    for path, item, is_key in _walk(doc):
        if is_key and isinstance(item, str) and item.lower() in RESERVED_KEYS:
            errors.append(f"{path}: skills cannot set policy, tiers, caps, mandates, tools or the gateway")
        elif not isinstance(item, (str, int, float, bool)) and item is not None:
            errors.append(f"{path}: only text, numbers and true/false are allowed (got {type(item).__name__})")
        elif isinstance(item, str) and (hits := scan(item.replace("_", " ")).instruction_patterns):
            errors.append(f"{path}: reads like instructions to an AI ({', '.join(hits)}); a skill holds settings, "
                          "not instructions")
    return errors


def _format(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        where = ".".join(str(p) for p in err["loc"]) or "skill"
        msg = "unknown field: it is not part of the skill format" if err["type"] == "extra_forbidden" else err["msg"]
        out.append(f"{where}: {msg}")
    return out


def check_detectors(pack: Pack) -> list[str]:
    """Every detector is registered and its params validate against that detector's model; every category it names
    exists in the pack; every advisor answer that sets a detector param is a valid value for it."""
    errors = []
    for i, cfg in enumerate(pack.leak_detectors):
        where = f"leak_detectors.{i}"
        try:
            spec = get_detector(cfg.detector)
        except KeyError as e:
            errors.append(f"{where}: {e.args[0]}")
            continue
        try:
            params = spec.params_model.model_validate(cfg.params)
        except ValidationError as e:
            errors.extend(f"{where}.params: bad params for detector {cfg.detector}: {m}" for m in _format(e))
            continue
        for field in _ID_FIELDS:
            unknown = set(getattr(params, field, ())) - set(pack.categories)
            if unknown:
                errors.append(f"{where}: detector {cfg.detector} names unknown categories {sorted(unknown)}")
        for q in pack.advisor_questions:
            if q.effect.detector != cfg.detector:
                continue
            if q.effect.param not in spec.params_model.model_fields:
                errors.append(f"advisor_questions.{q.id}: sets unknown param {cfg.detector}.{q.effect.param}")
                continue
            for option in q.options:
                if option.value is None:
                    continue
                try:
                    spec.params_model.model_validate({**cfg.params, q.effect.param: option.value})
                except ValidationError:
                    errors.append(f"advisor_questions.{q.id}: option {option.label!r} is not a valid "
                                  f"{cfg.detector}.{q.effect.param}")
    return errors


def _words(slug: str, limit: int) -> str:
    return slug.replace("_", " ").strip().capitalize()[:limit]


def planner_safe(pack: Pack) -> Pack:
    """The pack with every label that can reach the planner rebuilt in code from IDs (invariant 2)."""
    doc = pack.model_dump(mode="json")
    doc["display_name"] = _words(pack.id, 40)
    for cid, c in doc["categories"].items():
        c["label"] = _words(cid, 80)
    for k in doc["kpis"]:
        k["label"] = _words(k["id"], 80)
    for d in doc["leak_detectors"]:
        d["label"] = _words(d["detector"], 80)
    for fit in doc["financing_fit"].values():
        fit["reason"] = "Fit set by this skill"
    for b in doc["readiness"]["bands"]:
        b["label"] = _words(b["id"], 30)
    return Pack.model_validate(doc)


def _body_notices(body: str) -> tuple[list[str], list[str]]:
    errors, notices = [], []
    if HTML.search(body):
        errors.append("body: raw HTML is not allowed; write plain Markdown")
    if hits := scan(body).instruction_patterns:
        notices.append("The description contains text that reads like instructions to an AI ("
                       + ", ".join(hits) + "). It is shown to you as data only and never reaches the planner.")
    return errors, notices


def parse_skill(data: bytes | str) -> Skill:
    """Compile a skill file. Raises SkillError listing every problem found."""
    text = normalize(data)
    content, front, body = skill_content(text)
    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    doc = _load_yaml(front)
    if not isinstance(doc, dict):
        raise SkillError(["the frontmatter must be a YAML mapping (key: value lines)"])
    signature = doc.pop("signature", None)
    body_errors, notices = _body_notices(body)
    errors = _screen(doc) + body_errors
    if errors:
        raise SkillError(errors)
    try:
        authored = Pack.model_validate(doc)
    except ValidationError as e:
        raise SkillError(_format(e)) from None
    if errors := check_detectors(authored):
        raise SkillError(errors)
    verified = library_key.verify(sha, signature if isinstance(signature, str) else None)
    return Skill(pack=authored if verified else planner_safe(authored), authored=authored, body=body.strip(),
                 sha256=sha, verified=verified, notices=tuple(notices), text=text)


@lru_cache(maxsize=64)
def parse_cached(text: str) -> Skill:
    """parse_skill for files already on disk (built-in or activated), keyed by their content."""
    return parse_skill(text)
