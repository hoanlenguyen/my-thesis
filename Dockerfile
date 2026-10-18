# The demo API for the "Try it" page (src/hems/demo_api.py): FastAPI with the agent systems, the MILP and the
# retrieval library. It needs only data that is in the repository: the factorial benchmark (typical REFIT cycles and
# base-load shape), the RAG case library and the price cache. Deployment: deploy/README.md.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8.19 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 LANGSMITH_TRACING=false

# Dependencies first, so code changes reuse this layer
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra demo --no-install-project

COPY src ./src
COPY tools/emhass_rest.py ./tools/emhass_rest.py
COPY data/scenarios_v2 ./data/scenarios_v2
COPY data/rag ./data/rag
COPY results/demo_cache ./results/demo_cache
RUN uv sync --frozen --no-dev --extra demo

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "hems.demo_api:app", "--host", "0.0.0.0", "--port", "8000"]
