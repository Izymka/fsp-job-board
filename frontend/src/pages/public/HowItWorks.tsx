import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { PageHeader, Section, Stat } from '../../components/ui'
import { api } from '../../lib/api'
import { pct, useCatalog } from '../../lib/catalog'

interface ValidationSummary {
  n_candidates: number
  families: number
  unique_of_200_median: number
  accuracy_exact: number
  accuracy_within1: number
  overgrade_rate: number
  retest_agreement: number
  retest_kappa_weighted: number
  items_per_attempt: number
  leak_50: Record<string, number>
  drift_detection: number
  drift_delay_median: number
  recalibration: { mae_b_nominal: number; mae_b_recalibrated: number }
  ndcg: Record<string, number>
  accepted: Record<string, number>
  p10: Record<string, number>
}

function Formula({ children }: { children: string }) {
  return <div className="my-3 overflow-x-auto rounded-xl bg-surface px-4 py-3 font-mono text-[13px] text-ink">{children}</div>
}

export default function HowItWorks() {
  const { data: cat } = useCatalog()
  const { data: v } = useQuery({ queryKey: ['validation'], queryFn: () => api.get<ValidationSummary>('/api/catalog/validation'), staleTime: Infinity })
  const has = v && 'ndcg' in v
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Для жюри и любопытных"
        title="Механика подбора и тестирования"
        subtitle="Категория кандидата (специализация × грейд) определяется только опросом и адаптивным тестом. Работодатель описывает потребность, получает подборку с объяснением и сам выходит на контакт с предложением и вилкой."
      />

      {has && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Качество подборки (NDCG@10)" value={v.ndcg.ours.toFixed(2)} hint={`поиск по ключевым словам — ${v.ndcg.bm25_universal.toFixed(2)}`} />
          <Stat label="Принятые приглашения в топ-10" value={`×${(v.accepted.ours / v.accepted.bm25_universal).toFixed(1)}`} hint="против поиска по резюме" />
          <Stat label="Грейд: точно / ±1 ступень" value={`${pct(v.accuracy_exact)} / ${pct(v.accuracy_within1)}`} hint={`завышение грейда — ${pct(v.overgrade_rate)}`} />
          <Stat label="Утекло 50% банка: ложные подтверждения" value={pct(v.leak_50.ours)} hint={`фиксированный тест — ${pct(v.leak_50.fixed)}`} />
        </div>
      )}

      <Section title="1. Выход на контакт — инициатива у работодателя">
        <ol className="list-decimal space-y-2 pl-5 text-sm text-ink-soft">
          <li>Работодатель описывает потребность текстом; NLP выделяет технологии (обязательные и «плюсом»), специализацию и грейд.</li>
          <li>Система показывает рекомендованные категории (целевая, соседние по грейду, смежные специализации) с размером, долей кандидатов с ФСП и медианой ожиданий.</li>
          <li>Подборка — ранжированные обезличенные карточки с объяснением: что подтверждено тестом, что лишь заявлено, чего не хватает, совпадает ли вилка.</li>
          <li>Фильтры уточняют подборку, не теряя её: каждая версия сохраняется, к ней можно вернуться; кандидатов можно закрепить в шорт-листе.</li>
          <li>Приглашение обязательно содержит вилку «от–до»; ещё до отправки индикатор показывает, укладывается ли она в ожидания (без раскрытия чисел).</li>
          <li>Статусы: отправлено → просмотрено → принято / отклонено с причиной. Контакты кандидата открываются только после принятия. Работодатель видит агрегированные причины отказов — обратную связь рынка.</li>
        </ol>
        <h3 className="mt-5 font-bold">Ранжирование</h3>
        <p className="mt-1 text-sm text-muted">Внутри категории — сила подтверждённого профиля (тест + ФСП + регулярные задания); под потребность — соответствие, сила профиля, условия и свежесть.</p>
        <Formula>profile_strength = 0.60·тест + 0.25·ФСП + 0.15·регулярные задания</Formula>
        <Formula>match = 0.40·соответствие навыкам + 0.30·profile_strength + 0.20·условия (вилка, формат, отрасль) + 0.10·свежесть</Formula>
        <p className="text-sm text-muted">
          Подтверждённая тестом технология весит 1.0, заявленная без подтверждения — 0.4…0.6. ФСП — noisy-OR по достижениям с учётом уровня, результата, релевантности дисциплины и давности (полураспад 2 года); нет истории ФСП — компонент равен нулю, без штрафа.
        </p>
      </Section>

      <Section title="2. Тест, устойчивый к утечкам">
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="text-sm text-ink-soft">
            <h3 className="font-bold text-ink">Параметризованные семейства заданий</h3>
            <p className="mt-1">
              Задание — шаблон-генератор: числа, данные, имена и код меняются для каждого кандидата, правильный ответ вычисляется (код и SQL реально исполняются при генерации).
              В банке {cat?.bank.families ?? '170+'} семейств{has ? `, из 200 генераций медианно ${v.unique_of_200_median} уникальных вариантов` : ''}. Сложность — свойство шаблона, поэтому варианты сопоставимы, в отличие от генерации нейросетью.
            </p>
            <h3 className="mt-4 font-bold text-ink">Адаптивный тест на грейд (IRT/CAT)</h3>
            <p className="mt-1">
              Модель 3PL, оценка способности EAP. Задания подбираются по максимуму информации в точке порога заявленного грейда с балансировкой навыков по blueprint специализации.
              Тест останавливается, когда решение уверенно (P ≥ 0.95) или после 25 заданий{has ? `; в среднем — ${v.items_per_attempt.toFixed(0)} заданий` : ''}.
            </p>
            <h3 className="mt-4 font-bold text-ink">Правила грейда</h3>
            <ul className="mt-1 list-disc space-y-1 pl-5">
              <li>Грейд по результату теста не понижается — можно сразу пройти тест на уровень ниже.</li>
              <li>Уверенный результат — предложение пройти тест на ступень выше.</li>
              <li>Смена грейда — не чаще раза в 90 дней, повтор после неудачи — через 14 дней.</li>
            </ul>
          </div>
          <div className="text-sm text-ink-soft">
            <h3 className="font-bold text-ink">Почему утечки не работают</h3>
            <ol className="mt-1 list-decimal space-y-1.5 pl-5">
              <li>Утёкший вариант бесполезен: у другого кандидата другие параметры и другой ответ.</li>
              <li>Адаптивность: у разных кандидатов разные наборы семейств.</li>
              <li>Контроль экспозиции: семейство не показывается слишком часто.</li>
              <li>Мониторинг: если по семейству верных ответов становится аномально много (CUSUM), оно выводится из ротации{has ? ` — в симуляции ловится в ${pct(v.drift_detection)} случаев, медианно за ${v.drift_delay_median.toFixed(0)} ответов` : ''}.</li>
              <li>Ответы и seed варианта — только на сервере; вариант восстанавливается для апелляции по HMAC(секрет, попытка, позиция).</li>
            </ol>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link to="/test-demo" className="btn-primary">
                Посмотреть генерацию теста
              </Link>
            </div>
          </div>
        </div>
      </Section>

      <Section title="3. ФСП ID и реестр достижений">
        <p className="text-sm text-ink-soft">
          Привязка — стандартный OAuth2/OIDC-вход в ФСП ID (Keycloak): платформа получает идентификатор участника и запрашивает результаты в реестре ФСП (соревнование, дисциплина, уровень, результат, роль в команде). Переход на реальный ФСП ID — смена адреса и ключей в конфигурации. Нет истории ФСП — профиль полноценный, работодатель видит нейтральное «ФСП ID не привязан».
        </p>
      </Section>

      {has && (
        <Section title="4. Валидация">
          <p className="text-sm text-muted">
            Синтетическая популяция из {v.n_candidates} кандидатов со скрытой «истиной»; ответы в тесте симулируются по модели, намеренно отличающейся от модели оценивания (смещение сложности заданий, неравные варианты, многомерные навыки, угадывание), чтобы проверка не была цикличной. Полный отчёт — docs/validation.md (make validate).
          </p>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <Stat label="Ретест: взвешенная κ" value={v.retest_kappa_weighted.toFixed(2)} hint={`совпадение грейда ${pct(v.retest_agreement)}`} />
            <Stat label="Перекалибровка сложности" value={`${v.recalibration.mae_b_nominal.toFixed(2)} → ${v.recalibration.mae_b_recalibrated.toFixed(2)}`} hint="ошибка b: экспертная → по данным" />
            <Stat label="P@10 подборки" value={pct(v.p10.ours)} hint={`BM25 по резюме — ${pct(v.p10.bm25_universal)}`} />
          </div>
        </Section>
      )}
    </div>
  )
}
