FROM node:25 AS build
WORKDIR /app
COPY . .
RUN npm install && npm run build

FROM node:20
# version mismatch: minimal node-slim has never published a 20.x tag

FROM redis:8
COPY --from=build /app/dist /dist

FROM redis:7
# version mismatch: minimal redis-slim is on 8.x

FROM nginx:1.29
COPY --from=build /app/dist /usr/share/nginx/html

FROM nginx:1.27
# version mismatch: minimal nginx is on 1.29.x

FROM python:3.14-slim AS pytools
RUN pip install -r requirements.txt

FROM ghcr.io/rtvkiz/minimal-postgres-slim:latest
# already migrated, must not change
