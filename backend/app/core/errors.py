from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict | list | None = None


class ErrorResponse(BaseModel):
    """Единый формат ошибок API."""

    error: ErrorBody


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | list | None = None) -> None:
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what: str = "Объект") -> AppError:
    return AppError(404, "not_found", f"{what} не найден")


def forbidden(message: str = "Недостаточно прав") -> AppError:
    return AppError(403, "forbidden", message)


def conflict(code: str, message: str, details=None) -> AppError:
    return AppError(409, code, message, details)


def bad_request(code: str, message: str, details=None) -> AppError:
    return AppError(400, code, message, details)


# Описания кодов ошибок для OpenAPI
def responses(*codes: int) -> dict:
    texts = {
        400: "Некорректный запрос",
        401: "Требуется аутентификация",
        403: "Недостаточно прав для операции",
        404: "Объект не найден",
        409: "Конфликт состояния (например, кулдаун или повтор)",
        422: "Ошибка валидации входных данных",
        429: "Превышена квота",
    }
    return {c: {"model": ErrorResponse, "description": texts.get(c, "Ошибка")} for c in codes}


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
            exc.status_code, "http_error"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": str(exc.detail), "details": None}},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Проверьте корректность полей",
                    "details": details,
                }
            },
        )
