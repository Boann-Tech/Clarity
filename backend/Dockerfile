FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && addgroup --system clarity \
    && adduser --system --ingroup clarity clarity

COPY --chown=clarity:clarity app ./app

USER clarity

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
