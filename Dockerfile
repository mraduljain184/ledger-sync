FROM python:3.12-slim
WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt
COPY core ./core
COPY server ./server
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]