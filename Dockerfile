FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl ca-certificates unzip \
    && curl -fsSL https://deno.land/install.sh | sh \
    && mv /root/.deno/bin/deno /usr/local/bin/deno \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8001
ENV PORT=8001
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT} --workers 1
