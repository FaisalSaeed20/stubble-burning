FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Placeholder env vars just so manage.py can import settings at build time;
# real values are injected by Cloud Run at runtime and override these.
ENV DJANGO_SECRET_KEY=build-time-placeholder \
    DJANGO_DEBUG=False
RUN python manage.py collectstatic --noinput

EXPOSE 8080

CMD exec gunicorn core.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 0
