FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.30-alpine
# Адреса бэкенда и Keycloak подставляются в конфиг при старте контейнера (см. nginx.conf.template)
ENV BACKEND_URL=http://backend:8000 \
    KEYCLOAK_URL=http://keycloak:8080 \
    NGINX_ENVSUBST_FILTER='^(BACKEND_URL|KEYCLOAK_URL)$'
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
