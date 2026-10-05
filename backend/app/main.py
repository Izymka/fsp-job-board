"""ФСП Job Board API — модульный монолит.

Модули: users (роли, согласия 152-ФЗ), catalog (справочники), candidates (профиль, опрос, резюме,
PDF), assessment (адаптивный тест), employers (компания, подборки, банк кандидатов),
invitations (выход на контакт), vacancies (вакансии и отклики), tasks (регулярные задания),
fsp (привязка ФСП ID и реестр).
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core import errors
from .core.config import get_settings
from .modules.assessment.router import router as assessment_router
from .modules.candidates.router import router as candidates_router
from .modules.catalog.router import router as catalog_router
from .modules.employers.router import router as employers_router
from .modules.fsp.router import router as fsp_router
from .modules.fsp.router import sync_loop
from .modules.invitations.router import router as invitations_router
from .modules.tasks.router import router as tasks_router
from .modules.users.router import router as users_router
from .modules.vacancies.router import router as vacancies_router

logging.basicConfig(level=logging.INFO)

TAGS = [
    {
        "name": "Пользователь",
        "description": "Профиль пользователя, выбор роли, согласия на обработку ПДн (152-ФЗ).",
    },
    {"name": "Справочники", "description": "Специализации, грейды, навыки теста, отрасли, ФСП."},
    {
        "name": "Кандидат: профиль",
        "description": "Профиль, обязательный опрос, разбор PDF-резюме, PDF-профиль, приватность.",
    },
    {
        "name": "Тестирование",
        "description": "Адаптивный тест на заявленный грейд (IRT/CAT, параметризованные семейства заданий).",
    },
    {
        "name": "Работодатель",
        "description": "Компания, описание потребности, подборки с объяснениями, банк кандидатов.",
    },
    {
        "name": "Приглашения",
        "description": "Выход на контакт по инициативе работодателя; статусы; обратная связь рынка.",
    },
    {
        "name": "Вакансии и отклики",
        "description": "Классический сценарий: публикация вакансий и самостоятельный отклик.",
    },
    {
        "name": "Регулярные задания",
        "description": "Короткие задания от работодателей для актуальности профиля.",
    },
    {"name": "ФСП", "description": "Привязка ФСП ID (OIDC) и синхронизация достижений из реестра ФСП."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = threading.Event()
    if os.environ.get("FSP_DISABLE_BACKGROUND") != "1":
        threading.Thread(target=sync_loop, args=(stop,), daemon=True, name="fsp-sync").start()
    yield
    stop.set()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "API платформы подбора IT-специалистов с обратной механикой: кандидаты распределяются по категориям "
            "(специализация × грейд) по результатам адаптивного теста, работодатель находит категорию и сам выходит "
            "на контакт с предложением и вилкой.\n\n"
            "**Авторизация:** Bearer-токен OIDC (Keycloak, realm `fsp-jobs`). **Ошибки:** единый формат "
            '`{"error": {"code", "message", "details"}}`.'
        ),
        openapi_tags=TAGS,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    errors.install(app)
    for r in (
        users_router,
        catalog_router,
        candidates_router,
        assessment_router,
        employers_router,
        invitations_router,
        vacancies_router,
        tasks_router,
        fsp_router,
    ):
        app.include_router(r)

    @app.get("/api/health", tags=["Справочники"], summary="Проверка работоспособности")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
