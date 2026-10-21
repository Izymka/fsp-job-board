"""Вебхуки ATS: подписанные события платформы на адрес, указанный работодателем.

Тело подписано: X-FSP-Signature: sha256=HMAC-SHA256(ключ компании, тело). Ключ производный от секрета
платформы (`signing_key`) и виден работодателю в профиле компании.

Адрес задаёт работодатель, поэтому запросы во внутреннюю сеть стека (БД, Keycloak, метаданные облака)
запрещены: все адреса хоста должны быть публичными, а соединение идёт на уже проверенный IP — повторный
DNS-запрос мог бы вернуть внутренний адрес (DNS rebinding). Редиректы не выполняются по той же причине.
WEBHOOK_ALLOW_PRIVATE=1 — для стенда, где ATS стоит в той же локальной сети.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from urllib.parse import SplitResult, urlsplit

import httpx

from ...core.config import get_settings

log = logging.getLogger("webhooks")


def signing_key(company_id) -> str:
    return hmac.new(
        get_settings().webhook_secret.encode(), str(company_id).encode(), hashlib.sha256
    ).hexdigest()


def _default_port(parts: SplitResult) -> int:
    return parts.port or (443 if parts.scheme == "https" else 80)


def public_ip(parts: SplitResult) -> str | None:
    """Публичный IP хоста вебхука или None, если хотя бы один из его адресов внутренний."""
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    try:
        infos = socket.getaddrinfo(parts.hostname, _default_port(parts), proto=socket.IPPROTO_TCP)
    except (OSError, ValueError):
        return None
    ips = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
    if not ips or not all(ip.is_global for ip in ips):
        return None
    return str(ips[0])


def _pinned(parts: SplitResult, ip: str) -> tuple[str, dict[str, str], dict]:
    """URL с IP вместо имени хоста; Host и SNI (проверка сертификата) — по исходному имени."""
    host = f"[{ip}]" if ":" in ip else ip
    url = parts._replace(netloc=f"{host}:{_default_port(parts)}").geturl()
    host_header = parts.hostname + (f":{parts.port}" if parts.port else "")
    extensions = {"sni_hostname": parts.hostname} if parts.scheme == "https" else {}
    return url, {"Host": host_header}, extensions


def send(url: str, payload: dict, key: str) -> None:
    """Отправить событие (best effort: сбой доставки не ломает бизнес-операцию)."""
    parts = urlsplit(url)
    if get_settings().webhook_allow_private:
        target, headers, extensions = url, {}, {}
    else:
        ip = public_ip(parts)
        if ip is None:
            log.warning("webhook skipped: %s is not a public http(s) address", url)
            return
        target, headers, extensions = _pinned(parts, ip)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    sig = hmac.new(key.encode(), body, hashlib.sha256).hexdigest()
    try:
        with httpx.Client(timeout=5, follow_redirects=False) as client:
            client.post(
                target,
                content=body,
                headers={
                    **headers,
                    "Content-Type": "application/json",
                    "X-FSP-Event": payload["event"],
                    "X-FSP-Signature": f"sha256={sig}",
                },
                extensions=extensions,
            )
    except httpx.HTTPError as e:
        log.warning("webhook %s to %s failed: %s", payload["event"], parts.hostname, e)
