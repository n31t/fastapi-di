dev-backend:
	uv run uvicorn src.main:app --reload --port 3939

prod-backend:
	uv run uvicorn src.main:app --host 0.0.0.0 --port 8000