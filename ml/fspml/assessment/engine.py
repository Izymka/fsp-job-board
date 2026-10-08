"""Фасад движка тестирования для бэкенда: план попытки → выдача заданий → проверка → решение."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace

from ..catalog import Catalog, get_catalog
from .bank import REGISTRY
from .blueprint import TestBlueprint, personal_blueprint
from .cat import DEFAULT_CONFIG, CatConfig, CatPlan, CatResult, Response, decide, select_next, should_stop
from .irt import ItemParams
from .items import Family, ItemInstance, instance_seed


@dataclass(frozen=True)
class IssuedItem:
    position: int
    family: Family
    instance: ItemInstance
    seed: int


class AssessmentEngine:
    def __init__(
        self,
        secret: bytes,
        *,
        catalog: Catalog | None = None,
        config: CatConfig = DEFAULT_CONFIG,
        params: dict[str, ItemParams] | None = None,
        disabled: set[str] | None = None,
    ) -> None:
        self.secret = secret
        self.catalog = catalog or get_catalog()
        self.config = config
        params = params or {}
        disabled = disabled or set()
        # Банк с учётом перекалиброванных параметров и выведенных из ротации (утечка) семейств.
        self.bank: dict[str, Family] = {}
        for fid, fam in REGISTRY.items():
            if fid in disabled:
                continue
            if fid in params:
                p = params[fid]
                fam = replace(fam, a=p.a, b=p.b)
            self.bank[fid] = fam

    # --- планы ---
    def measurable_skills(self) -> set[str]:
        """Навыки, по которым в активном банке хватает семейств для подоценки."""
        counts = Counter(f.skill for f in self.bank.values())
        return {s for s, n in counts.items() if n >= self.config.skill_min_items}

    def blueprint_for(
        self, spec_id: str, stack: Sequence[str] | None = None, directions: Sequence[str] = ()
    ) -> TestBlueprint:
        """Состав теста кандидата: ядро специализации + модули по направлению и стеку (с объяснением)."""
        return personal_blueprint(
            spec_id,
            stack or (),
            directions=directions,
            available=self.measurable_skills(),
            catalog=self.catalog,
        )

    def plan_for_specialization(
        self,
        spec_id: str,
        grade: str,
        stack: Sequence[str] | None = None,
        kind: str = "initial",
        directions: Sequence[str] = (),
    ) -> CatPlan:
        """stack — технологии из профиля кандидата (канонические имена или id навыков теста)."""
        return CatPlan(
            blueprint=self.blueprint_for(spec_id, stack, directions).weights,
            claimed_grade=grade,
            config=self.config,
            kind=kind,
        )

    def plan_for_blueprint(self, blueprint: dict[str, float], grade: str) -> CatPlan:
        bp = {k: v for k, v in blueprint.items() if v > 0 and any(f.skill == k for f in self.bank.values())}
        total = sum(bp.values()) or 1.0
        return CatPlan(
            blueprint={k: v / total for k, v in bp.items()}, claimed_grade=grade, config=self.config
        )

    # --- ход попытки ---
    def response(self, family_id: str, correct: bool) -> Response:
        fam = self.bank.get(family_id) or REGISTRY[family_id]
        return Response(family_id, fam.skill, fam.params, bool(correct))

    def next_item(
        self,
        attempt_id: str,
        plan: CatPlan,
        responses: Sequence[Response],
        *,
        exposure: dict[str, float] | None = None,
    ) -> IssuedItem | None:
        if should_stop(responses, plan, catalog=self.catalog, bank=list(self.bank.values())):
            return None
        position = len(responses)
        seed = instance_seed(self.secret, attempt_id, position)
        rng = random.Random(seed ^ 0x5BD1E995)
        fam = select_next(
            responses, list(self.bank.values()), plan, rng, exposure=exposure, catalog=self.catalog
        )
        if fam is None:
            return None
        return IssuedItem(position, fam, fam.generate(seed), seed)

    def regenerate(self, attempt_id: str, position: int, family_id: str) -> ItemInstance:
        """Восстановить выданный экземпляр (для проверки ответа и апелляций) без хранения текста."""
        fam = self.bank.get(family_id) or REGISTRY[family_id]
        return fam.generate(instance_seed(self.secret, attempt_id, position))

    def finish(self, plan: CatPlan, responses: Sequence[Response], extra_loglik=None) -> CatResult:
        return decide(responses, plan, catalog=self.catalog, extra_loglik=extra_loglik)
