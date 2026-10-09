import clsx from 'clsx'
import { LogOut, Menu, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { useAuth, useMe } from '../lib/auth'

const CANDIDATE_NAV = [
  { to: '/candidate', label: 'Главная', end: true },
  { to: '/candidate/test', label: 'Тест и грейд' },
  { to: '/candidate/invitations', label: 'Приглашения' },
  { to: '/candidate/vacancies', label: 'Вакансии' },
  { to: '/candidate/tasks', label: 'Задания' },
  { to: '/candidate/profile', label: 'Профиль' },
  { to: '/candidate/settings', label: 'Настройки' },
]
const EMPLOYER_NAV = [
  { to: '/employer', label: 'Главная', end: true },
  { to: '/employer/searches', label: 'Подборки' },
  { to: '/employer/candidates', label: 'Банк кандидатов' },
  { to: '/employer/invitations', label: 'Приглашения' },
  { to: '/employer/vacancies', label: 'Вакансии' },
  { to: '/employer/tasks', label: 'Задания' },
  { to: '/employer/company', label: 'Компания' },
]

export function Logo({ dark }: { dark?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label="ФСП Job Board — на главную">
      <img src={dark ? '/brand/logo-dark.svg' : '/brand/logo-light.svg'} alt="ФСП" className="h-8 w-auto" />
      <span className={clsx('hidden border-l pl-2.5 font-mono text-sm font-medium whitespace-nowrap sm:inline', dark ? 'border-white/20 text-fog' : 'border-line text-ink-soft')}>Job Board</span>
    </Link>
  )
}

export function Header() {
  const { authenticated, login, register, logout } = useAuth()
  const { data: me } = useMe()
  const [open, setOpen] = useState(false)
  const nav = me?.role === 'candidate' ? CANDIDATE_NAV : me?.role === 'employer' ? EMPLOYER_NAV : []
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-white/90 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-6 px-4 sm:px-6">
        <Logo />
        <nav className="hidden flex-1 items-center gap-0.5 xl:flex">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => clsx('rounded-lg px-2.5 py-2 text-sm font-medium whitespace-nowrap transition-colors', isActive ? 'bg-brand-50 text-brand-600' : 'text-ink-soft hover:bg-surface hover:text-ink')}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {authenticated ? (
            <>
              <span className="hidden max-w-48 truncate text-sm text-muted 2xl:inline">{me?.email}</span>
              {me?.role && (
                <span className="hidden rounded-full bg-surface px-2.5 py-1 text-xs font-medium text-ink-soft sm:inline">{me.role === 'candidate' ? 'Кандидат' : 'Работодатель'}</span>
              )}
              <button className="btn-ghost p-2" onClick={logout} title="Выйти" aria-label="Выйти">
                <LogOut className="h-4 w-4" />
              </button>
            </>
          ) : (
            <>
              <button className="btn-ghost" onClick={() => login()}>
                Войти
              </button>
              <button className="btn-primary" onClick={register}>
                Регистрация
              </button>
            </>
          )}
          {nav.length > 0 && (
            <button className="btn-ghost p-2 xl:hidden" onClick={() => setOpen(!open)} aria-label="Меню">
              {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          )}
        </div>
      </div>
      {open && nav.length > 0 && (
        <nav className="border-t border-line bg-white px-4 py-2 xl:hidden">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              onClick={() => setOpen(false)}
              className={({ isActive }) => clsx('block rounded-lg px-3 py-2.5 text-sm font-medium', isActive ? 'bg-brand-50 text-brand-600' : 'text-ink-soft')}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
      )}
    </header>
  )
}

export function Footer() {
  return (
    <footer className="mt-16 bg-ink text-fog">
      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-10 sm:px-6 md:grid-cols-3">
        <div>
          <img src="/brand/logo-full-dark.svg" alt="Федерация спортивного программирования России" className="h-9 w-auto" />
          <p className="mt-4 max-w-sm text-sm text-steel">Платформа подбора IT-специалистов с подтверждённым профилем и достижениями в спортивном программировании.</p>
        </div>
        <div className="text-sm text-steel">
          <div className="mb-2 font-mono text-xs tracking-wider text-fog uppercase">Как это работает</div>
          <ul className="space-y-1.5">
            <li>
              <Link to="/how-it-works" className="hover:text-white">Механика подбора и тестирования</Link>
            </li>
            <li>
              <Link to="/test-demo" className="hover:text-white">Демо теста</Link>
            </li>
            <li>
              <a href="/api/docs" className="hover:text-white">API (Swagger)</a>
            </li>
          </ul>
        </div>
        <div className="text-sm text-steel">
          <div className="mb-2 font-mono text-xs tracking-wider text-fog uppercase">Данные</div>
          <p>Обработка персональных данных — по 152-ФЗ, с вашего согласия. Контакты кандидата видны работодателю только после принятия приглашения или отклика.</p>
        </div>
      </div>
    </footer>
  )
}

export function AppLayout({ children }: { children?: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6">{children ?? <Outlet />}</main>
      <Footer />
    </div>
  )
}
