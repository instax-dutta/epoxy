FROM python:3.14-alpine AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.14-alpine

RUN adduser -D -h /home/container container

COPY --from=builder /root/.local /home/container/.local
COPY server.py /home/container/
COPY .env.example /home/container/.env.example
COPY entrypoint.sh /home/container/

RUN chown -R container:container /home/container && \
    chmod +x /home/container/entrypoint.sh

ENV PATH=/home/container/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HOME=/home/container

USER container
WORKDIR /home/container

EXPOSE 8080

ENTRYPOINT ["/home/container/entrypoint.sh"]
