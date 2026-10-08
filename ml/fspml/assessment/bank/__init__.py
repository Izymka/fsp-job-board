"""Банк параметризованных семейств заданий. Импорт модулей регистрирует семейства в REGISTRY."""

from ..items import REGISTRY
from . import (  # noqa: F401
    algorithms,
    csharp,
    data,
    ds_directions,
    frontend,
    go_,
    infra,
    java,
    php,
    practice,
    python_,
    sql,
    vue,
    web,
)

__all__ = ["REGISTRY"]
