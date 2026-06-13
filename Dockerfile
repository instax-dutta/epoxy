FROM python:3.14-alpine AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.14-alpine

RUN adduser -D -h /home/container container

COPY --from=builder /usr/local /usr/local
COPY server.py /app/server.py
COPY .env.example /app/.env.example
COPY requirements.txt /app/requirements.txt
COPY entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    HOME=/home/container

USER container
WORKDIR /home/container

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
