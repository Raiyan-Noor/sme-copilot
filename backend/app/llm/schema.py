"""Turn a Pydantic model into a JSON Schema accepted by OpenAI Structured Outputs in strict mode.

Strict mode needs every object to list all its properties as required and set `additionalProperties: false`, and
does not accept `default`. Optional fields stay expressible as `anyOf [..., null]`. The adapter still validates the
returned JSON against the Pydantic model, so the schema only steers the model; validation is what is trusted.
"""

from typing import Any

from pydantic import BaseModel

_DROP = {"default", "title"}


def _strict(node: Any) -> Any:
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in ("properties", "$defs"):  # maps of names to schemas: keep every name
                out[k] = {name: _strict(sub) for name, sub in v.items()}
            elif k not in _DROP:
                out[k] = _strict(v)
        if out.get("type") == "object" or "properties" in out:
            props = out.get("properties", {})
            out["properties"] = props
            out["required"] = list(props)
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [_strict(v) for v in node]
    return node


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    return _strict(model.model_json_schema())
