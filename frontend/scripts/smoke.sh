#!/usr/bin/env bash
# Smoke-тест образа фронтенда: SPA отдаётся, /api/ и /auth/ проксируются на адреса из BACKEND_URL
# и KEYCLOAK_URL, админка Keycloak закрыта. Использование: scripts/smoke.sh <образ>
set -euo pipefail
image=$1
dir=$(cd "$(dirname "$0")" && pwd)
net=fsp-web-smoke
port=${SMOKE_PORT:-18188}

cleanup() {
  [[ ${1:-$?} == 0 ]] || docker logs fsp-web-smoke 2>&1 || true
  docker rm -f fsp-web-smoke fsp-upstream-mock >/dev/null 2>&1 || true
  docker network rm "$net" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup 0

docker network create "$net" >/dev/null
docker run -d --name fsp-upstream-mock --network "$net" \
  -v "$dir/smoke-upstream.conf:/etc/nginx/conf.d/default.conf:ro" --entrypoint nginx "$image" -g 'daemon off;' >/dev/null
# внешний бэкенд, как на хостинге: стенд с Keycloak под префиксом /auth
docker run -d --name fsp-web-smoke --network "$net" \
  -e BACKEND_URL=http://fsp-upstream-mock \
  -e KEYCLOAK_URL=http://fsp-upstream-mock/auth \
  -p "127.0.0.1:$port:80" "$image" >/dev/null

base=http://127.0.0.1:$port
for _ in $(seq 30); do curl -fs -o /dev/null "$base/" && break; sleep 1; done

fail() { echo "FAIL: $*" >&2; exit 1; }
expect() { # путь, ожидаемая подстрока ответа
  body=$(curl -fsS -H 'X-Forwarded-Proto: https' "$base$1") || fail "$1: HTTP-ошибка"
  [[ $body == *"$2"* ]] || fail "$1: ожидалось «$2», получено «$body»"
  echo "ok  $1"
}

expect / '<div id="root">'
expect /employer/searches '<div id="root">'
expect /api/auth/config 'uri=/api/auth/config proto=https'
expect '/auth/realms/fsp-jobs/protocol/openid-connect/certs' 'uri=/auth/realms/fsp-jobs/protocol/openid-connect/certs'
status=$(curl -s -o /dev/null -w '%{http_code}' "$base/auth/admin/master/console/")
[[ $status == 404 ]] || fail "/auth/admin/: ожидался 404, получен $status"
echo "ok  /auth/admin/ закрыт"
