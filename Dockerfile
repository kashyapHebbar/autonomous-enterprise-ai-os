FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp
ENV MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY docs ./docs
COPY examples ./examples
COPY scripts ./scripts

RUN python -m pip install --upgrade pip "setuptools>=83" "wheel>=0.46.2" \
    && python -m pip install --no-cache-dir -e ".[analysis,identity,observability,secrets,storage,warehouse]" \
    && groupadd --gid 10001 aeai \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin aeai \
    && mkdir -p /app/artifacts /tmp/matplotlib \
    && chown -R 10001:10001 /app/artifacts /tmp/matplotlib

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "aeai_os.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
