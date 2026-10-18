"""Load and validate Skill Packs from `packs/*.yaml`.

Validation happens once, at load: the Pydantic schema, then every referenced detector must be registered and its
params must validate against that detector's params model, and every category a detector names must exist in
the pack. A bad pack fails loudly here instead of producing wrong numbers later.
"""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.packs.registry import get_detector
from app.packs.schema import Pack

PACKS_DIR = Path(__file__).resolve().parent
_ID_FIELDS = ("categories", "fee_categories", "refund_categories")


class PackError(ValueError):
    """A pack file is missing, unparseable or invalid."""


def _check_detectors(pack: Pack) -> None:
    for cfg in pack.leak_detectors:
        try:
            spec = get_detector(cfg.detector)
        except KeyError as e:
            raise PackError(f"pack {pack.id}: {e.args[0]}") from None
        try:
            params = spec.params_model.model_validate(cfg.params)
        except ValidationError as e:
            raise PackError(f"pack {pack.id}: bad params for detector {cfg.detector}: {e}") from None
        for field in _ID_FIELDS:
            unknown = set(getattr(params, field, ())) - set(pack.categories)
            if unknown:
                raise PackError(f"pack {pack.id}: detector {cfg.detector} names unknown categories {sorted(unknown)}")


def load_pack_file(path: Path) -> Pack:
    """Parse and fully validate one pack file. The file stem must equal the pack ID."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise PackError(f"cannot read pack {path.name}: {e}") from None
    try:
        pack = Pack.model_validate(doc)
    except ValidationError as e:
        raise PackError(f"invalid pack {path.name}: {e}") from None
    if pack.id != path.stem:
        raise PackError(f"pack file {path.name} declares id {pack.id!r}; it must match the file name")
    _check_detectors(pack)
    return pack


def list_pack_ids() -> list[str]:
    return sorted(p.stem for p in PACKS_DIR.glob("*.yaml"))


@lru_cache
def load_pack(pack_id: str) -> Pack:
    """Load a bundled pack by ID. Only IDs of files shipped in this directory resolve (no path input)."""
    if pack_id not in list_pack_ids():
        raise PackError(f"unknown pack {pack_id!r}; available: {list_pack_ids()}")
    return load_pack_file(PACKS_DIR / f"{pack_id}.yaml")
