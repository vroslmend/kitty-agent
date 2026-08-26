# Pinned to 3.12 rather than 3.13: the LangGraph and LangChain wheels landing in
# later phases are the reason, and a predictable deploy is worth more than being
# current here.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependency manifest first, so the install layer is cached until the deps
# themselves change rather than on every source edit.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

# Container hosts inject PORT and expect the process to bind it. Shell form so
# the variable is expanded at runtime, with 8000 as the local default.
EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
