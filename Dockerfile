FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY tsu_bot ./tsu_bot

# Сервис ничего не пишет на диск: состояние лежит в Postgres
RUN useradd --system --no-create-home app
USER app

CMD ["python", "-m", "tsu_bot"]
