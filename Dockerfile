# syntax=docker/dockerfile:1.7
# The go2 image. The CLI, the MCP server and the worker are one program with
# different commands, so one image serves every go2 service in deploy/stack.
#
# Model weights are not in the image: they change with config.py rather than
# with the code and weigh 1.7 GB, so they live on a volume mounted at /models.
# T-042 will vendor them for a network with no internet; until then the first
# boot downloads them once.

FROM python:3.12-slim-bookworm

# uv from its own image, pinned to the version that produced uv.lock, so the
# build has no unlocked network step.
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies before source, so editing go2/ does not reinstall every wheel.
# --locked refuses a lock file that disagrees with pyproject.toml, the same
# rule CI applies. --no-dev keeps pytest, ruff and pyrefly out of an image
# that never runs them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY go2 ./go2
COPY deploy/stack ./deploy/stack
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Runs as an unprivileged user. /models exists in the image so the named
# volume mounted there inherits this ownership on first use; the virtual
# environment stays root-owned and read-only to go2, which is all it needs.
RUN useradd --system --create-home --uid 1000 go2 \
    && mkdir -p /models \
    && chown go2:go2 /models
USER go2

ENV PATH="/app/.venv/bin:$PATH" \
    GO2_MODEL_CACHE_DIR=/models \
    HF_HOME=/models/huggingface

ENTRYPOINT ["go2"]
CMD ["--help"]
