"""Регистрация всех моделей (для Alembic и create_all в тестах)."""

from .core.db import Base
from .modules.assessment.models import Attempt, AttemptItem, FamilyStats
from .modules.candidates.models import CandidateProfile
from .modules.employers.models import Company, Search, SearchVersion, ShortlistItem
from .modules.invitations.models import Invitation
from .modules.tasks.models import RegularTask, TaskAssignment
from .modules.users.models import AuditLog, Consent, User
from .modules.vacancies.models import Application, Vacancy

__all__ = [
    "Base",
    "User",
    "Consent",
    "AuditLog",
    "CandidateProfile",
    "Attempt",
    "AttemptItem",
    "FamilyStats",
    "Company",
    "Search",
    "SearchVersion",
    "ShortlistItem",
    "Invitation",
    "Vacancy",
    "Application",
    "RegularTask",
    "TaskAssignment",
]
