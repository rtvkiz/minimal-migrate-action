FROM node:20 AS build
WORKDIR /app
COPY . .
RUN npm install && npm run build

FROM redis:7
COPY --from=build /app/dist /dist

FROM python:3.12-slim AS pytools
RUN pip install -r requirements.txt

FROM nginx:1.27
COPY --from=build /app/dist /usr/share/nginx/html

FROM ghcr.io/rtvkiz/minimal-postgres-slim:latest
# already migrated, must not change
