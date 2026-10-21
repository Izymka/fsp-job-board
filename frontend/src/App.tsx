import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppLayout } from './components/Layout'
import { EmptyState, PageLoader } from './components/ui'
import { MeLoadError, useAuth, useMe } from './lib/auth'
import type { Role } from './lib/types'
import CandidateApplications from './pages/candidate/Applications'
import CandidateHome from './pages/candidate/Home'
import CandidateInvitations from './pages/candidate/Invitations'
import CandidateProfile from './pages/candidate/Profile'
import CandidateSettings from './pages/candidate/Settings'
import CandidateSurvey from './pages/candidate/Survey'
import CandidateTasks from './pages/candidate/Tasks'
import TestHub from './pages/candidate/TestHub'
import TestRunner from './pages/candidate/TestRunner'
import CandidateVacancies from './pages/candidate/Vacancies'
import EmployerBank from './pages/employer/Bank'
import CandidateView from './pages/employer/CandidateView'
import EmployerCompany from './pages/employer/Company'
import EmployerHome from './pages/employer/Home'
import EmployerInvitations from './pages/employer/Invitations'
import SearchNew from './pages/employer/SearchNew'
import SearchView from './pages/employer/SearchView'
import Searches from './pages/employer/Searches'
import EmployerTasks from './pages/employer/Tasks'
import EmployerVacancies from './pages/employer/Vacancies'
import FspFunnel from './pages/fsp/Funnel'
import DevLogin from './pages/public/DevLogin'
import HowItWorks from './pages/public/HowItWorks'
import Landing from './pages/public/Landing'
import Onboarding from './pages/public/Onboarding'
import TestDemo from './pages/public/TestDemo'

function Gate({ role, children }: { role?: Role; children: ReactNode }) {
  const { ready, authenticated, login } = useAuth()
  const meQ = useMe()
  const me = meQ.data
  const loc = useLocation()
  if (!ready || (authenticated && meQ.isPending)) return <PageLoader />
  if (!authenticated)
    return (
      <EmptyState
        title="Нужно войти"
        text="Войдите или зарегистрируйтесь, чтобы продолжить."
        action={
          <button className="btn-primary" onClick={() => login(loc.pathname)}>
            Войти
          </button>
        }
      />
    )
  if (meQ.isError) return <MeLoadError me={meQ} redirectTo={loc.pathname} />
  if (!me?.role) return <Navigate to="/onboarding" replace />
  if (role && me.role !== role) return <Navigate to="/app" replace />
  return <>{children}</>
}

function AppRedirect() {
  const { data: me } = useMe()
  if (!me) return <PageLoader />
  if (!me.role) return <Navigate to="/onboarding" replace />
  if (me.role === 'employer') return <Navigate to={me.has_company ? '/employer' : '/employer/company'} replace />
  if (me.role === 'fsp_admin') return <Navigate to="/fsp" replace />
  if (me.onboarding_step === 'survey') return <Navigate to="/candidate/survey" replace />
  return <Navigate to="/candidate" replace />
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<Landing />} />
        <Route path="/how-it-works" element={<HowItWorks />} />
        <Route path="/test-demo" element={<TestDemo />} />
        <Route path="/login" element={<DevLogin />} />
        <Route
          path="/app"
          element={
            <Gate>
              <AppRedirect />
            </Gate>
          }
        />
        <Route path="/onboarding" element={<Onboarding />} />

        <Route path="/candidate" element={<Gate role="candidate"><CandidateHome /></Gate>} />
        <Route path="/candidate/survey" element={<Gate role="candidate"><CandidateSurvey /></Gate>} />
        <Route path="/candidate/profile" element={<Gate role="candidate"><CandidateProfile /></Gate>} />
        <Route path="/candidate/test" element={<Gate role="candidate"><TestHub /></Gate>} />
        <Route path="/candidate/test/:attemptId" element={<Gate role="candidate"><TestRunner /></Gate>} />
        <Route path="/candidate/invitations" element={<Gate role="candidate"><CandidateInvitations /></Gate>} />
        <Route path="/candidate/vacancies" element={<Gate role="candidate"><CandidateVacancies /></Gate>} />
        <Route path="/candidate/applications" element={<Gate role="candidate"><CandidateApplications /></Gate>} />
        <Route path="/candidate/tasks" element={<Gate role="candidate"><CandidateTasks /></Gate>} />
        <Route path="/candidate/settings" element={<Gate role="candidate"><CandidateSettings /></Gate>} />

        <Route path="/employer" element={<Gate role="employer"><EmployerHome /></Gate>} />
        <Route path="/employer/company" element={<Gate role="employer"><EmployerCompany /></Gate>} />
        <Route path="/employer/searches" element={<Gate role="employer"><Searches /></Gate>} />
        <Route path="/employer/searches/new" element={<Gate role="employer"><SearchNew /></Gate>} />
        <Route path="/employer/searches/:id" element={<Gate role="employer"><SearchView /></Gate>} />
        <Route path="/employer/candidates" element={<Gate role="employer"><EmployerBank /></Gate>} />
        <Route path="/employer/candidates/:id" element={<Gate role="employer"><CandidateView /></Gate>} />
        <Route path="/employer/invitations" element={<Gate role="employer"><EmployerInvitations /></Gate>} />
        <Route path="/employer/vacancies" element={<Gate role="employer"><EmployerVacancies /></Gate>} />
        <Route path="/employer/tasks" element={<Gate role="employer"><EmployerTasks /></Gate>} />

        <Route path="/fsp" element={<Gate role="fsp_admin"><FspFunnel /></Gate>} />

        <Route path="*" element={<EmptyState title="Страница не найдена" text="Проверьте адрес или вернитесь на главную." action={<a className="btn-primary" href="/">На главную</a>} />} />
      </Route>
    </Routes>
  )
}
