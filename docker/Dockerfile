FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get -y install --no-install-recommends cron curl && rm -rf /var/lib/apt/lists/*

# Set local timezone (for cron)
RUN ln -sf /usr/share/zoneinfo/Europe/Oslo /etc/localtime

# Create cron log file
RUN touch /var/log/demorss.log

WORKDIR /app

RUN curl -sSL https://install.python-poetry.org | python3 - -y --version 1.8.3

RUN /root/.local/bin/poetry config virtualenvs.create false

COPY pyproject.toml README.md ./

COPY demorss demorss

RUN /root/.local/bin/poetry lock && /root/.local/bin/poetry install --only main

COPY docker/episode_not_available.mp3 .
COPY docker/entrypoint.sh .
RUN chmod +x ./entrypoint.sh
ENTRYPOINT ["./entrypoint.sh"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
