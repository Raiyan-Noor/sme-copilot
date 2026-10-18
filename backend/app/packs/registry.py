"""Leak detector registry. Packs reference detectors by name; only code registered here can run.

A pack file chooses and parameterizes detectors but cannot introduce code: an unknown name or invalid params fail
pack validation at load time, never at run time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd
from pydantic import BaseModel, ConfigDict

from app.firewall.fact import Fact
from app.packs.schema import Pack


class DetectorParams(BaseModel):
    """Base for each detector's params model. Unknown keys in a pack are rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass(frozen=True)
class DetectorContext:
    pack: Pack
    today: date
    currency: str


# fn(categorized frame from ledger_view.frame, validated params, context) -> leak Facts
DetectorFn = Callable[[pd.DataFrame, DetectorParams, DetectorContext], list[Fact]]


@dataclass(frozen=True)
class RegisteredDetector:
    name: str
    params_model: type[DetectorParams]
    fn: DetectorFn


_REGISTRY: dict[str, RegisteredDetector] = {}


def detector(name: str, params_model: type[DetectorParams]) -> Callable[[DetectorFn], DetectorFn]:
    """Register `fn` under `name` with the model its pack params must validate against."""

    def wrap(fn: DetectorFn) -> DetectorFn:
        if name in _REGISTRY:
            raise ValueError(f"detector {name!r} is already registered")
        _REGISTRY[name] = RegisteredDetector(name, params_model, fn)
        return fn

    return wrap


def get_detector(name: str) -> RegisteredDetector:
    _load_builtins()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown detector {name!r}; registered: {sorted(_REGISTRY)}") from None


def registered_names() -> list[str]:
    _load_builtins()
    return sorted(_REGISTRY)


def _load_builtins() -> None:
    import app.packs.detectors  # noqa: F401  (importing registers the built-in detectors)
