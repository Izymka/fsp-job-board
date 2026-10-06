"""Минимальный клиент Yandex Cloud AI Studio через OpenAI-совместимый Chat Completions API.

Принципы:
* **Воспроизводимость.** Каждый ответ кэшируется на диске по хешу (модель, сообщения, параметры):
  повторный прогон бенчмарка не тратит деньги и даёт те же метки.
* **Бюджет.** Расход считается по `usage` из ответа и тарифу модели; при превышении
  `LLM_BUDGET_RUB` клиент останавливается до отправки следующего запроса.
* **ПДн.** Заголовок `x-data-logging-enabled: false` — Яндекс не сохраняет запросы
  (ПДн кандидатов обрабатываются только в контуре РФ, 152-ФЗ).
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]

# ₽ за 1000 токенов (вход, выход), синхронный режим, с НДС — тарифы AI Studio на 2026-10.
# Используются только для контроля бюджета; переопределяются через LLM_PRICES (JSON).
PRICES_RUB_PER_1K: dict[str, tuple[float, float]] = {
    "yandexgpt-5-lite": (0.2, 0.2),
    "yandexgpt-5-pro": (1.2, 1.2),
    "yandexgpt-5.1": (0.8, 0.8),
    "aliceai-llm": (0.5, 1.2),
    "qwen3-235b-a22b-fp8": (0.5, 0.5),
    "qwen3.6-35b-a3b": (0.2, 0.3),
    "gpt-oss-20b": (0.1, 0.1),
    "gpt-oss-120b": (0.3, 0.3),
    "deepseek-v4-flash": (0.3, 0.5),
    "deepseek-v4.1-flash": (0.3, 0.5),
}


def price_rub(prices: dict[str, tuple[float, float]], model: str, inp: int, out: int) -> float:
    pin, pout = prices.get(model, (1.2, 1.2))  # неизвестная модель — по верхнему тарифу
    return (inp * pin + out * pout) / 1000.0


# Параметры по умолчанию для моделей: отключаем платные рассуждения там, где они не нужны
# (у Qwen3.6 без этого весь лимит токенов уходит на скрытое рассуждение и ответ пустой).
MODEL_DEFAULTS: dict[str, dict] = {
    "qwen3.6-35b-a3b": {"reasoning_effort": "none"},
    "deepseek-v4.1-flash": {"reasoning_effort": "none"},
    "deepseek-v4-flash": {"reasoning_effort": "none"},
    "gpt-oss-20b": {"reasoning_effort": "low"},
    "gpt-oss-120b": {"reasoning_effort": "low"},
}


class LLMDisabled(RuntimeError):
    """LLM выключен или не настроен (нет ключа/каталога)."""


class BudgetExceeded(RuntimeError):
    pass


def load_dotenv(path: Path | None = None) -> None:
    """Подхватывает переменные из .env в корне репозитория (не перезаписывая окружение)."""
    path = path or REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass
class LLMConfig:
    enabled: bool
    folder_id: str
    api_key: str
    base_url: str = "https://ai.api.cloud.yandex.net/v1"
    data_logging: bool = False
    budget_rub: float = 3000.0
    cache_path: Path = REPO_ROOT / "ml" / "bench" / "cache" / "llm.sqlite"
    timeout: float = 120.0
    prices: dict[str, tuple[float, float]] = field(default_factory=lambda: dict(PRICES_RUB_PER_1K))

    @classmethod
    def from_env(cls) -> LLMConfig:
        load_dotenv()
        env = os.environ
        prices = dict(PRICES_RUB_PER_1K)
        if env.get("LLM_PRICES"):
            prices.update({k: tuple(v) for k, v in json.loads(env["LLM_PRICES"]).items()})
        return cls(
            enabled=env.get("LLM_ENABLED", "0") == "1",
            folder_id=env.get("YC_FOLDER_ID", ""),
            api_key=env.get("YC_API_KEY", ""),
            base_url=env.get("YC_LLM_BASE_URL", cls.base_url).rstrip("/"),
            data_logging=env.get("YC_DATA_LOGGING", "false").lower() == "true",
            budget_rub=float(env.get("LLM_BUDGET_RUB", "3000")),
            cache_path=Path(env.get("LLM_CACHE", str(cls.cache_path))),
            prices=prices,
        )

    def model_uri(self, model: str) -> str:
        return model if "://" in model else f"gpt://{self.folder_id}/{model}"


@dataclass
class Completion:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_rub: float
    cached: bool


class LLMClient:
    def __init__(self, config: LLMConfig | None = None, transport: httpx.BaseTransport | None = None) -> None:
        self.cfg = config or LLMConfig.from_env()
        self._transport = transport
        self._lock = threading.Lock()
        self.spent_rub = 0.0
        self.calls = 0
        self.cache_hits = 0
        self.cfg.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.cfg.cache_path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS completions (key TEXT PRIMARY KEY, model TEXT, response TEXT, created REAL)"
        )
        self._db.commit()

    # ------------------------------------------------------------------------------- служебное
    def check_ready(self) -> None:
        if not self.cfg.enabled:
            raise LLMDisabled("LLM выключен: установите LLM_ENABLED=1 в .env")
        if not (self.cfg.folder_id and self.cfg.api_key):
            raise LLMDisabled("Не заданы YC_FOLDER_ID / YC_API_KEY в .env")

    def price(self, model: str, inp: int, out: int) -> float:
        return price_rub(self.cfg.prices, model, inp, out)

    def _key(self, payload: dict) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _cache_get(self, key: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT response FROM completions WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _cache_put(self, key: str, model: str, response: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO completions VALUES (?, ?, ?, ?)",
                (key, model, json.dumps(response, ensure_ascii=False), time.time()),
            )
            self._db.commit()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "OpenAI-Project": self.cfg.folder_id,
            "x-folder-id": self.cfg.folder_id,
            "x-data-logging-enabled": "true" if self.cfg.data_logging else "false",
        }

    # ------------------------------------------------------------------------------------ вызов
    def chat(
        self,
        model: str,
        messages: list[dict],
        *,
        temperature: float = 0.0,
        max_tokens: int = 512,
        extra: dict | None = None,
        use_cache: bool = True,
        retries: int = 5,
    ) -> Completion:
        payload = {
            "model": self.cfg.model_uri(model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **MODEL_DEFAULTS.get(model, {}),
            **(extra or {}),
        }
        key = self._key({**payload, "model": model})  # ключ кэша не зависит от каталога
        if use_cache and (hit := self._cache_get(key)) is not None:
            with self._lock:
                self.cache_hits += 1
            return self._to_completion(model, hit, cached=True)
        self.check_ready()
        with self._lock:
            if self.spent_rub >= self.cfg.budget_rub:
                raise BudgetExceeded(f"Достигнут бюджет {self.cfg.budget_rub:.0f} ₽ (LLM_BUDGET_RUB)")
        delay = 2.0
        last_err: Exception | None = None
        with httpx.Client(timeout=self.cfg.timeout, transport=self._transport) as http:
            for _ in range(retries):
                try:
                    r = http.post(
                        f"{self.cfg.base_url}/chat/completions", json=payload, headers=self._headers()
                    )
                except httpx.HTTPError as e:
                    last_err = e
                else:
                    if r.status_code == 200:
                        data = r.json()
                        self._cache_put(key, model, data)
                        comp = self._to_completion(model, data, cached=False)
                        with self._lock:
                            self.spent_rub += comp.cost_rub
                            self.calls += 1
                        return comp
                    if r.status_code not in (408, 409, 429, 500, 502, 503, 504):
                        raise RuntimeError(f"AI Studio {r.status_code}: {r.text[:500]}")
                    last_err = RuntimeError(f"AI Studio {r.status_code}: {r.text[:200]}")
                time.sleep(delay)
                delay = min(delay * 2, 30)
        raise RuntimeError(f"AI Studio недоступен после {retries} попыток: {last_err}")

    def _to_completion(self, model: str, data: dict, cached: bool) -> Completion:
        msg = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        inp, out = int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
        return Completion(
            text=msg.get("content") or "",
            model=model,
            input_tokens=inp,
            output_tokens=out,
            cost_rub=0.0 if cached else self.price(model, inp, out),
            cached=cached,
        )


def parse_json_object(text: str) -> dict:
    """Достаёт первый JSON-объект из ответа модели (допускает ```json-обёртку и текст вокруг)."""
    s = text.strip()
    if "```" in s:
        parts = s.split("```")
        for p in parts[1::2]:
            p = p.removeprefix("json").strip()
            if p.startswith("{"):
                s = p
                break
    start = s.find("{")
    if start < 0:
        raise ValueError(f"нет JSON в ответе: {text[:200]!r}")
    depth = 0
    in_str = esc = False
    for i, ch in enumerate(s[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start : i + 1])
    raise ValueError(f"незакрытый JSON в ответе: {text[:200]!r}")
