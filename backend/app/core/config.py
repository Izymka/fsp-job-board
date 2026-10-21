from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация из переменных окружения (см. .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_name: str = "ФСП Job Board API"
    environment: str = "dev"
    database_url: str = "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_jobs"
    frontend_url: str = "http://localhost:5173"
    public_api_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost"

    # Авторизация: Keycloak (OIDC). Токены проверяются по JWKS; issuer — публичный адрес.
    auth_mode: str = "keycloak"  # keycloak | dev (dev — только для локальной отладки и тестов!)
    keycloak_public_url: str = "http://localhost:8080"
    keycloak_internal_url: str = "http://localhost:8080"
    keycloak_realm: str = "fsp-jobs"
    keycloak_client_id: str = "fsp-jobs-web"
    keycloak_audience: str = "fsp-jobs-api"
    dev_jwt_secret: str = "dev-only-secret-change-me-0123456789abcdef"

    # ФСП ID (realm fsp-id в Keycloak как имитация) и реестр ФСП
    fsp_id_realm: str = "fsp-id"
    fsp_id_client_id: str = "fsp-jobs-link"
    fsp_id_client_secret: str = "fsp-jobs-link-secret"
    fsp_registry_url: str = "http://localhost:8090"
    fsp_registry_api_key: str = "fsp-registry-demo-key"
    fsp_sync_interval_hours: float = 6.0
    # Учётные записи федерации (роль fsp_admin: агрегированная воронка трудоустройства участников ФСП)
    fsp_admin_emails: str = "federation@demo.fsp"

    # Тестирование: секрет для seed экземпляров заданий (HMAC). Сменить в production!
    assessment_secret: str = "assessment-secret-change-me-0123456789abcdef"
    # Вебхуки ATS: ключ подписи компании = HMAC(webhook_secret, id компании). Сменить в production!
    webhook_secret: str = "webhook-secret-change-me-0123456789abcdef"
    # Разрешить вебхуки на адреса локальной сети (ATS рядом со стендом). По умолчанию — только публичные.
    webhook_allow_private: bool = False

    # Цифровой проктор: сверка лица 1:1. local_demo — эталон в нашей БД (AES-GCM, только демо);
    # ebs — Единая биометрическая система (production, 572-ФЗ). Ключ сменить в production!
    biometric_provider: str = "local_demo"
    biometric_key: str = "biometric-demo-key-change-me-0123456789abcdef"
    biometric_threshold: float = 0.5  # сходство Human ≥ порога — то же лицо
    biometric_mismatch_threshold: float = 0.35  # ниже — уверенно другое лицо; между порогами — серая зона
    snapshot_retention_days: int = 180

    # Механика подбора: v7 — формула v6 + весомый ФСП и ФСП как опыт работы (по умолчанию);
    # v6 — v5 + «ворота» основного стека; v5 — специфичность требований + «ворота»; hybrid — v5 +
    # кросс-энкодер (нужен WITH_EMBEDDINGS=1, без пакета/весов работает как v5); v1 — исходная
    # формула; v4 — прежний гибрид на v1. См. docs/matching.md и docs/bench.md.
    fsp_ranker: str = "v7"

    # Разбор резюме: если правила не нашли периодов работы — извлечь опыт через LLM
    # (Yandex AI Studio; работает, только если LLM_ENABLED=1 и заданы ключи)
    resume_llm_fallback: bool = True

    # Почта (в демо — Mailpit)
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "ФСП Job Board <noreply@fsp-jobs.local>"
    email_enabled: bool = True

    # Политики
    invite_quota_per_week: int = 30
    consent_version: str = "2026-10-01"
    task_interval_days: int = 14

    def insecure_defaults(self) -> list[str]:
        """Что нельзя оставлять в production: dev-авторизация и секреты из примера конфигурации."""
        bad = ["AUTH_MODE=dev"] if self.auth_mode == "dev" else []
        for name in ("assessment_secret", "webhook_secret", "biometric_key"):
            if "change-me" in getattr(self, name):
                bad.append(name.upper())
        return bad

    @property
    def keycloak_issuer(self) -> str:
        return f"{self.keycloak_public_url}/realms/{self.keycloak_realm}"

    @property
    def keycloak_jwks_url(self) -> str:
        return f"{self.keycloak_internal_url}/realms/{self.keycloak_realm}/protocol/openid-connect/certs"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
