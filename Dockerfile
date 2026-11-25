FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/
COPY data/catalogue.parquet data/catalogue.parquet
# METHODE=regle (par défaut, sans LLM), baseline, ou METHODE=ollama avec OLLAMA_URL=http://host.docker.internal:11434
ENV METHODE=regle PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "rapprochement.api:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
