# 3.12 rather than 3.13. The LangGraph and LangChain wheels this will need are
# not reliably built for 3.13 yet, and a deploy is a bad place to find out.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

EXPOSE 8000
# Shell form on purpose. The exec form does not expand ${PORT}, and the host
# injects it, so the container would bind the wrong port and fail its check.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
