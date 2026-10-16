.PHONY: install test eval serve docker
install:
	python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
test:
	.venv/Scripts/python -m pytest
eval:
	.venv/Scripts/python -m evals.run
serve:
	.venv/Scripts/python -m uvicorn app.server:app --port 8200
docker:
	docker compose up --build
