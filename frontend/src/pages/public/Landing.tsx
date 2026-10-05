import { ArrowRight, BadgeCheck, Building2, ClipboardCheck, Send, ShieldCheck, Sparkles, Trophy, UserRound } from 'lucide-react'
import { Link, Navigate } from 'react-router-dom'
import { Badge, NodeLine } from '../../components/ui'
import { useAuth, useMe } from '../../lib/auth'
import { useCatalog } from '../../lib/catalog'

function HeroMock() {
  return (
    <div className="relative">
      <NodeLine className="absolute -top-8 -left-10 hidden h-28 w-96 lg:block" />
      <div className="card relative rotate-1 p-5 shadow-[0_20px_60px_-20px_rgba(64,47,255,0.35)]">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-xs text-muted">Приглашение · Финтех-платформа «Рубль+»</div>
            <div className="mt-1 font-mono text-lg font-bold">Python-разработчик</div>
          </div>
          <Badge tone="bg-ok-50 text-ok-600">Новое</Badge>
        </div>
        <div className="mt-4 font-mono text-2xl font-bold text-brand-500">250–330 тыс. ₽</div>
        <div className="mt-1 text-xs text-muted">Вилка указана сразу — до начала общения</div>
        <div className="mt-4 flex flex-wrap gap-1.5">
          <Badge tone="bg-brand-50 text-brand-700">Backend · Middle ✓</Badge>
          <Badge tone="bg-ok-50 text-ok-600">Python ✓</Badge>
          <Badge tone="bg-ok-50 text-ok-600">SQL ✓</Badge>
          <Badge tone="bg-accent-50 text-accent-600">ФСП: призёр 2025</Badge>
        </div>
        <div className="mt-5 grid grid-cols-2 gap-2">
          <button className="btn-primary pointer-events-none">Принять</button>
          <button className="btn-secondary pointer-events-none">Отклонить</button>
        </div>
      </div>
      <div className="card absolute -bottom-10 -left-6 hidden w-64 -rotate-2 p-4 shadow-lg sm:block">
        <div className="text-xs text-muted">Почему в подборке</div>
        <ul className="mt-2 space-y-1.5 text-xs">
          <li className="flex gap-1.5">
            <span className="text-ok-600">●</span> Подтверждено тестом: Python, PostgreSQL
          </li>
          <li className="flex gap-1.5">
            <span className="text-ok-600">●</span> Тест: 82-й перцентиль категории
          </li>
          <li className="flex gap-1.5">
            <span className="text-ok-600">●</span> Ожидания в вашей вилке
          </li>
        </ul>
      </div>
    </div>
  )
}

const STEPS_CANDIDATE = [
  { icon: UserRound, title: 'Опрос', text: 'Специализация, стек, отрасль, формат и ожидания по зарплате. Резюме из PDF заполнит профиль за вас.' },
  { icon: ClipboardCheck, title: 'Тест на свой грейд', text: '20–30 минут, адаптивный: задания подстраиваются под ответы. Результат — категория, видимая работодателям.' },
  { icon: Trophy, title: 'Достижения ФСП', text: 'Привяжите ФСП ID — результаты соревнований усилят профиль. Нет истории — профиль всё равно полноценный.' },
  { icon: Send, title: 'Приглашения', text: 'Работодатели сами приходят с предложением и вилкой. Принимаете — только тогда они видят ваши контакты.' },
]
const STEPS_EMPLOYER = [
  { icon: Building2, title: 'Опишите потребность', text: 'Обычным текстом: кто нужен и чем занимается команда. Система выделит стек, специализацию и грейд.' },
  { icon: Sparkles, title: 'Получите подборку', text: 'Кандидаты из подходящих категорий с объяснением: что подтверждено тестом, что заявлено, чего не хватает.' },
  { icon: ShieldCheck, title: 'Уточните без потери', text: 'Фильтры по стеку, ФСП, формату и вилке — версия подборки сохраняется, можно откатиться.' },
  { icon: Send, title: 'Пригласите', text: 'Предложение с вилкой до отправки сверяется с ожиданиями кандидата — без раскрытия чисел.' },
]

export default function Landing() {
  const { authenticated, register, login } = useAuth()
  const { data: me } = useMe()
  const { data: cat } = useCatalog()
  if (authenticated && me?.role) return <Navigate to="/app" replace />
  const intent = (role: 'candidate' | 'employer') => {
    try {
      localStorage.setItem('fsp_intent', role)
    } catch {
      /* приватный режим браузера */
    }
    if (authenticated) window.location.href = '/onboarding'
    else register()
  }
  return (
    <div className="-mt-8">
      <section className="relative overflow-hidden pt-12 pb-20">
        <div className="grid items-center gap-14 lg:grid-cols-[1.15fr_1fr]">
          <div>
            <Badge tone="bg-brand-50 text-brand-700" className="mb-5 font-mono">
              Федерация спортивного программирования
            </Badge>
            <h1 className="text-4xl leading-[1.08] font-bold sm:text-5xl lg:text-6xl">
              Работодатель
              <br />
              находит <span className="text-brand-500">вас</span> сам
            </h1>
            <p className="mt-6 max-w-xl text-lg text-ink-soft">
              Пройдите тест на свой грейд — работодатели увидят подтверждённый профиль и ваши достижения в соревнованиях ФСП. Без откликов вслепую: в каждом приглашении сразу указана зарплата.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <button className="btn-primary px-6 py-3 text-base" onClick={() => intent('candidate')}>
                Я ищу работу <ArrowRight className="h-4 w-4" />
              </button>
              <button className="btn-secondary px-6 py-3 text-base" onClick={() => intent('employer')}>
                Я ищу специалистов
              </button>
            </div>
            {!authenticated && (
              <p className="mt-4 text-sm text-muted">
                Уже есть аккаунт?{' '}
                <button className="link" onClick={() => login()}>
                  Войти
                </button>
              </p>
            )}
          </div>
          <div className="px-4 pb-10 sm:px-10">
            <HeroMock />
          </div>
        </div>
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        {[
          { v: cat ? `${cat.bank.families}` : '170+', l: 'семейств заданий', h: 'каждое генерирует сотни уникальных вариантов — утечка ответов бесполезна' },
          { v: '7 × 5', l: 'категорий', h: 'специализация × грейд: от Intern до Lead в Backend, Frontend, Mobile, DS, QA, DevOps, аналитике' },
          { v: '0', l: 'контактов до согласия', h: 'работодатель видит контакты, только когда вы приняли приглашение или откликнулись сами' },
        ].map((s) => (
          <div key={s.l} className="card p-6">
            <div className="font-mono text-4xl font-bold text-brand-500">{s.v}</div>
            <div className="mt-1 font-medium">{s.l}</div>
            <div className="mt-2 text-sm text-muted">{s.h}</div>
          </div>
        ))}
      </section>

      <section className="mt-20">
        <h2 className="text-3xl font-bold">Как это работает</h2>
        <div className="mt-8 grid gap-10 lg:grid-cols-2">
          {[
            { title: 'Кандидату', steps: STEPS_CANDIDATE },
            { title: 'Работодателю', steps: STEPS_EMPLOYER },
          ].map((col) => (
            <div key={col.title}>
              <div className="mb-4 font-mono text-sm tracking-wider text-brand-500 uppercase">{col.title}</div>
              <ol className="space-y-3">
                {col.steps.map((s, i) => (
                  <li key={s.title} className="card flex gap-4 p-4">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-500">
                      <s.icon className="h-5 w-5" />
                    </div>
                    <div>
                      <div className="font-semibold">
                        <span className="mr-2 font-mono text-muted">0{i + 1}</span>
                        {s.title}
                      </div>
                      <p className="mt-1 text-sm text-muted">{s.text}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-20 overflow-hidden rounded-3xl bg-ink p-8 text-fog sm:p-12">
        <div className="grid gap-10 lg:grid-cols-2">
          <div>
            <h2 className="text-3xl font-bold text-white">Тесту можно доверять</h2>
            <p className="mt-4 text-steel">
              Задание — это не текст, а шаблон-генератор: числа, данные и код меняются для каждого кандидата, а правильный ответ вычисляется. Сложность одинакова у всех вариантов, поэтому результаты сопоставимы — в отличие от генерации заданий нейросетью.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link to="/test-demo" className="btn bg-white text-ink hover:bg-fog">
                Посмотреть, как тест строится из вакансии
              </Link>
              <Link to="/how-it-works" className="btn border border-white/20 text-white hover:bg-white/10">
                Механика и валидация
              </Link>
            </div>
          </div>
          <ul className="space-y-4">
            {[
              ['Адаптивность', 'Следующее задание подбирается по вашим ответам — у каждого свой набор, тест короче и точнее.'],
              ['Грейд не понижается', 'Не подтвердили заявленный уровень — сразу пройдите тест ниже. Уверенный результат — предложим повысить.'],
              ['Защита от утечек', 'Утёкший вариант бесполезен; аномальный рост верных ответов по заданию выводит его из ротации.'],
            ].map(([t, d]) => (
              <li key={t} className="flex gap-3">
                <BadgeCheck className="mt-0.5 h-5 w-5 shrink-0 text-brand-300" />
                <div>
                  <div className="font-semibold text-white">{t}</div>
                  <div className="text-sm text-steel">{d}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  )
}
