FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home gateway
COPY gateway gateway
COPY migrations migrations
COPY alembic.ini .
USER gateway
EXPOSE 8002
CMD ["uvicorn", "gateway.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8002", "--no-access-log"]
