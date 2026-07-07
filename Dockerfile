# shion-ai 本番イメージ(docs/02 §3 デプロイ)
# フロントエンドをビルドしてから、バックエンドと一緒に1コンテナで配信する

FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /srv/shion
COPY backend/ backend/
RUN pip install --no-cache-dir ./backend
COPY assets/ assets/
COPY --from=frontend /build/dist frontend/dist

# config / plugins / data は docker-compose.yml でホストからマウントする
ENV SHION_ROOT=/srv/shion
EXPOSE 8000
CMD ["uvicorn", "shion.main:app", "--host", "0.0.0.0", "--port", "8000"]
