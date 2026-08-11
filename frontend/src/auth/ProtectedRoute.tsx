import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { LoadingState } from '../components/ui'
import { useAuth } from './AuthContext'

export function ProtectedRoute() {
  const { session, isLoading } = useAuth()
  const location = useLocation()
  if (isLoading) return <LoadingState label="Restaurando sessão…" />
  if (!session) return <Navigate to="/login" state={{ from: location.pathname }} replace />
  return <Outlet />
}
