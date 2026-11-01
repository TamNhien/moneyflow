FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/moneyflow
COPY backend/requirements.txt /opt/moneyflow/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend /opt/moneyflow/backend
COPY frontend /opt/moneyflow/frontend
RUN useradd --create-home --uid 10001 moneyflow
USER moneyflow
EXPOSE 8000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
