SHELL := /bin/bash
PY := $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
.PHONY: install data test run eval verify-all

install:
	$(PY) -m pip install -r requirements.txt

data:
	$(PY) pipeline/download.py
	$(PY) pipeline/build_db.py

test:
	$(PY) -m pytest -q

run:
	$(PY) -m uvicorn app.main:app --reload --port 8000

eval:
	$(PY) scripts/run_eval.py

verify-all:
	PY=$(PY) bash scripts/verify_all.sh
