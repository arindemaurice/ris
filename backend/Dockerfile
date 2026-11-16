FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY backend/app.py backend/setup.py backend/worker.py backend/.env.example /app/backend/
COPY backend/radius /app/backend/radius
COPY index.html /app/index.html
COPY frontend /app/frontend
WORKDIR /app/backend
ENV RIS_ENV=production HOST=0.0.0.0 PORT=8000 RIS_DB_PATH=/data/ris.db
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
