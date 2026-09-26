FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PAPERFLOW_DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY paperflow_service ./paperflow_service
RUN mkdir -p /data
EXPOSE 8000
CMD ["/bin/sh","-c","exec uvicorn paperflow_service.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
