FROM python:3.12-slim
ARG APP_REVISION=development
LABEL org.chessstudio.account-security="1"
LABEL org.opencontainers.image.revision=$APP_REVISION
RUN apt-get update && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements.lock ./
COPY compose.yaml .env.example ./
RUN pip install --no-cache-dir -r requirements.lock
COPY *.py ./
COPY studio ./studio
COPY web ./web
COPY tests ./tests
COPY scripts ./scripts
COPY deploy ./deploy
COPY database ./database
RUN python scripts/prepare_public_data.py
ENV STOCKFISH_PATH=/usr/games/stockfish \
    STUDIO_RELEASE_SHA=$APP_REVISION \
    STUDIO_DB=/studio-data/studio.sqlite3 \
    CHESS_KNOWLEDGE_DB=/studio-data/knowledge.sqlite3 \
    DATABASE_PATH=/data/chess_coach.sqlite3 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000 8001
CMD ["uvicorn", "studio.app:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
