# Pinned to match the runtime the plan locks in, and the version CI installs.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies install against an empty stand-in package, so this layer is
# keyed to pyproject.toml alone and survives every source edit. Copying app/
# first would rebuild the whole dependency tree on a one-line change, which
# matters once LangGraph and LangChain are in it.
COPY pyproject.toml README.md ./
RUN mkdir -p app \
    && : > app/__init__.py \
    && pip install --no-cache-dir . \
    && rm -rf app

# --no-deps: the tree is already installed above. This only replaces the
# stand-in with the real package, and must not be dropped, or the stub shadows
# the real one in site-packages.
COPY app ./app
RUN pip install --no-cache-dir --no-deps --force-reinstall .

EXPOSE 8000
# Shell form on purpose. The exec form does not expand ${PORT}, and the host
# injects it, so the container would bind the wrong port and fail its check.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
