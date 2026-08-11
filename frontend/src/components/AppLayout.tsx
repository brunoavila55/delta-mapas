import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Logo } from './ui'

const navigation = [
  { to: '/', label: 'Visão geral', icon: '⌂' },
  { to: '/properties', label: 'Propriedades', icon: '◇' },
  { to: '/jobs', label: 'Processamentos', icon: '◷' },
  { to: '/maps', label: 'Mapas gerados', icon: '▧' },
  { to: '/billing', label: 'Créditos', icon: '◉' },
]

export function AppLayout() {
  const { session, logout } = useAuth()
  return (
    <div className="min-h-screen bg-[#f5f7f4] text-slate-900 lg:grid lg:grid-cols-[250px_1fr]">
      <aside className="hidden border-r border-slate-200 bg-white lg:flex lg:min-h-screen lg:flex-col lg:px-5 lg:py-6">
        <div className="px-2"><Logo /></div>
        <nav className="mt-10 space-y-1.5">
          {navigation.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3.5 py-3 text-sm font-semibold transition ${isActive ? 'bg-emerald-950 text-white shadow-md shadow-emerald-950/15' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'}`
              }
            >
              <span className="text-lg">{item.icon}</span>{item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto rounded-2xl bg-emerald-50 p-4">
          <p className="truncate text-sm font-bold text-emerald-950">{session?.tenant.name}</p>
          <p className="mt-1 text-xs uppercase tracking-wider text-emerald-700">{session?.tenant.role}</p>
          <button onClick={() => void logout()} className="mt-4 text-xs font-bold text-slate-600 hover:text-rose-700">Sair da conta</button>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-slate-200 bg-white/95 px-4 backdrop-blur lg:px-8">
          <div className="lg:hidden"><Logo compact /></div>
          <nav className="flex gap-1 overflow-x-auto lg:hidden">
            {navigation.map((item) => (
              <NavLink key={item.to} to={item.to} end={item.to === '/'} className={({ isActive }) => `rounded-lg px-2.5 py-2 text-xs font-bold ${isActive ? 'bg-emerald-950 text-white' : 'text-slate-600'}`}>
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto hidden items-center gap-3 lg:flex">
            <div className="text-right">
              <p className="text-sm font-semibold">{session?.user.first_name || session?.user.username}</p>
              <p className="text-xs text-slate-500">{session?.user.email || 'Conta Delta Mapas'}</p>
            </div>
            <span className="grid h-9 w-9 place-items-center rounded-full bg-emerald-100 text-sm font-black text-emerald-800">
              {(session?.user.first_name || session?.user.username || 'D').slice(0, 1).toUpperCase()}
            </span>
          </div>
        </header>
        <main className="mx-auto max-w-[1500px] p-4 sm:p-6 lg:p-8"><Outlet /></main>
      </div>
    </div>
  )
}
