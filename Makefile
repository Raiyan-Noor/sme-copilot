# sme-copilot. Works with GNU make on Linux/macOS and on Windows (e.g. `mingw32-make`, or `make` from
# choco/winget). Recipes call Python scripts so they don't depend on the shell.

ifeq ($(OS),Windows_NT)
  BOOT_PY ?= python
  VENV_PY := $(CURDIR)/backend/.venv/Scripts/python.exe
else
  BOOT_PY ?= python3
  VENV_PY := $(CURDIR)/backend/.venv/bin/python
endif

.PHONY: setup seed dev test openapi redteam evidence anchor

setup:  ## venv + pip install, npm install
	$(BOOT_PY) scripts/setup.py

seed:  ## regenerate both businesses and the mailbox (deterministic) -> backend/data/generated/
	"$(VENV_PY)" backend/data/seed/generate.py

dev:  ## FastAPI :8000 + Next :3000
	"$(VENV_PY)" scripts/dev.py

test: export LLM_REPLAY = replay
test:  ## all pytest suites in replay mode + the branding check + frontend types in sync with the API
	"$(VENV_PY)" -m pytest -c backend/pyproject.toml --rootdir backend backend/tests
	"$(VENV_PY)" scripts/check_branding.py
	"$(VENV_PY)" scripts/gen_frontend_types.py --check

openapi:  ## export docs/openapi.json and regenerate frontend/lib/types.ts from it
	"$(VENV_PY)" scripts/export_openapi.py
	"$(VENV_PY)" scripts/gen_frontend_types.py

redteam:  ## attack + benign suites; writes docs/results/redteam.json
	@echo "make redteam: not implemented yet (build prompt 15). No results are written until the suite exists."
	@exit 1

evidence:  ## export audit log JSONL + verify chain + anchors (tx hashes) -> docs/results/
	@echo "make evidence: not implemented yet (build prompts 6, 17, 19)."
	@exit 1

anchor:  ## anchor now against the live testnet (manual only; needs ANCHOR_* in .env)
	@echo "make anchor: not implemented yet (build prompt 17)."
	@exit 1
