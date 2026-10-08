"""Банк параметризованных семейств заданий. Импорт модулей регистрирует семейства в REGISTRY."""

from ..items import REGISTRY
from . import algorithms, data, ds_directions, frontend, infra, practice, python_, sql, web  # noqa: F401

__all__ = ["REGISTRY"]
