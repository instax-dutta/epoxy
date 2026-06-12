FROM python:3.14-alpine AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.14-alpine

RUN adduser -D -h /home/container container

COPY --from=builder /usr/local /usr/local
COPY server.py /home/container/
COPY .env.example /home/container/.env.example
COPY entrypoint.sh /home/container/

RUN chown -R container:container /home/container && \
    chmod +x /home/container/entrypoint.sh

ENV PYTHONUNBUFFERED=1 \
    HOME=/home/container

USER container
WORKDIR /home/container

# Pterodactyl maps SERVER_PORT to the container;
# entrypoint.sh resolves SERVER_PORT → PORT → 8080
EXPOSE 8080

ENTRYPOINT ["/home/container/entrypoint.sh"]
