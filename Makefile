.PHONY: install run test lint

install:
	python -m pip install -e '.[dev]'

run:
	uvicorn gateway.main:app --reload --port 8080

test:
	pytest -q

lint:
	ruff check .

