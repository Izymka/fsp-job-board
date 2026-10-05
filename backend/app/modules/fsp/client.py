"""Клиент реестра ФСП (в демо — сервис fsp-registry-mock с предложенной командой схемой).

Схема ответа `GET /api/v1/participants/{fsp_id}`:
{
  "fsp_id": "FSP-000123", "full_name": "...", "region": "...", "sport_rank": "КМС" | null,
  "achievements": [
    {"id": "...", "event": "Всероссийские соревнования ...", "discipline": "product",
     "level": "national", "result": "prize", "place": 2, "date": "2025-11-20",
     "role": "backend", "team": "..."}
  ]
}
404 — участника нет в реестре (история ФСП отсутствует — это нормальный случай).
"""

from __future__ import annotations

import httpx

from ...core.config import get_settings


class RegistryUnavailable(Exception):
    pass


def fetch_participant(fsp_id: str) -> dict | None:
    s = get_settings()
    try:
        r = httpx.get(
            f"{s.fsp_registry_url}/api/v1/participants/{fsp_id}",
            headers={"X-API-Key": s.fsp_registry_api_key},
            timeout=5,
        )
    except httpx.HTTPError as e:
        raise RegistryUnavailable(str(e)) from e
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise RegistryUnavailable(f"HTTP {r.status_code}")
    return r.json()


def normalize_achievements(data: dict | None) -> list[dict]:
    if not data:
        return []
    out = []
    for a in data.get("achievements", []):
        out.append(
            {
                "id": a.get("id"),
                "title": a.get("event", ""),
                "discipline": a.get("discipline"),
                "level": a.get("level"),
                "result": a.get("result"),
                "place": a.get("place"),
                "date": a.get("date"),
                "role": a.get("role"),
                "team": a.get("team"),
            }
        )
    return out
