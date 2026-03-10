FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data/factia

ENV FACTIA_DATA_DIR=/data/factia

# Timeout largo para la descarga de correos (puede tardar varios minutos)
CMD ["gunicorn", "--bind", "0.0.0.0:8002", "--timeout", "600", "--workers", "1", "app:app"]
