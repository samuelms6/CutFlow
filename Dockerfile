FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/cutflow/.cache/huggingface

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl libglib2.0-0 libgl1 \
    && groupadd --gid 10001 cutflow \
    && useradd --uid 10001 --gid cutflow --create-home --shell /usr/sbin/nologin cutflow \
    && mkdir -p /app/data /home/cutflow/.cache/huggingface \
    && chown -R cutflow:cutflow /app /home/cutflow \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=cutflow:cutflow . .

USER cutflow

EXPOSE 8000

CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]
