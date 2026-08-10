FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        binutils \
        curl \
        gdal-bin \
        libgdal-dev \
        libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements ./requirements
RUN pip install --upgrade pip \
    && pip install -r requirements/dev.txt

RUN groupadd --system app && useradd --system --gid app app

COPY --chown=app:app . .

USER app

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate_schemas --shared --noinput && python manage.py runserver 0.0.0.0:8000"]
