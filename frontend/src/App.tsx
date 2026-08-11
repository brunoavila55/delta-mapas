import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './components/AppLayout'
import { LoadingState } from './components/ui'

const LoginPage = lazy(() => import('./pages/LoginPage').then((module) => ({ default: module.LoginPage })))
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })))
const PropertiesPage = lazy(() => import('./pages/PropertiesPage').then((module) => ({ default: module.PropertiesPage })))
const JobsPage = lazy(() => import('./pages/JobsPage').then((module) => ({ default: module.JobsPage })))
const NewJobPage = lazy(() => import('./pages/NewJobPage').then((module) => ({ default: module.NewJobPage })))
const MapsPage = lazy(() => import('./pages/MapsPage').then((module) => ({ default: module.MapsPage })))
const BillingPage = lazy(() => import('./pages/BillingPage').then((module) => ({ default: module.BillingPage })))

function App() {
  return (
    <Suspense fallback={<LoadingState label="Carregando interface…" />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="properties" element={<PropertiesPage />} />
            <Route path="jobs" element={<JobsPage />} />
            <Route path="jobs/new" element={<NewJobPage />} />
            <Route path="maps" element={<MapsPage />} />
            <Route path="billing" element={<BillingPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}

export default App
