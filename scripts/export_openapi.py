"""Write docs/openapi.json, the API contract the frontend's lib/types.ts mirrors. Run by `make openapi`.

Deterministic: built from code with fixed settings (no .env), including the testing routes. A test fails if the
committed file drifts from the app, so re-run this after changing any route or model.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "openapi.json"
sys.path.insert(0, str(ROOT / "backend"))


def build_schema() -> dict:
    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(_env_file=None, demo_passcode="unused", expose_test_routes=True))
    return app.openapi()


def render(schema: dict) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    OUT.write_text(render(build_schema()), encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
