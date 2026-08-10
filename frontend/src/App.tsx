import { useQuery } from '@tanstack/react-query'
import { Link, Route, Routes } from 'react-router-dom'

type Health = { status: string; schema: string }

async function getHealth(): Promise<Health> {
  const response = await fetch('/api/v1/health/')
  if (!response.ok) throw new Error('API indisponível')
  return response.json() as Promise<Health>
}

function Home() {
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 30_000 })

  return (
    <main className="min-h-screen bg-stone-100 text-stone-900">
      <section className="mx-auto flex min-h-screen max-w-6xl items-center px-6 py-16">
        <div className="grid w-full gap-12 lg:grid-cols-[1.15fr_0.85fr] lg:items-center">
          <div>
            <p className="mb-5 text-sm font-semibold uppercase tracking-[0.28em] text-emerald-700">
              Sensoriamento remoto agrícola
            </p>
            <h1 className="max-w-3xl text-5xl font-semibold leading-tight tracking-tight text-emerald-950 md:text-7xl">
              Delta Mapas
            </h1>
            <p className="mt-7 max-w-2xl text-lg leading-8 text-stone-600">
              Uma base multitenant para transformar imagens de satélite em mapas agronômicos claros,
              rastreáveis e prontos para decisão.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-4">
              <span className="rounded-full bg-emerald-950 px-5 py-3 text-sm font-medium text-white">
                Scaffold do MVP ativo
              </span>
              <a className="text-sm font-semibold text-emerald-800 hover:text-emerald-600" href="/api/docs/">
                Abrir Swagger →
              </a>
            </div>
          </div>

          <aside className="overflow-hidden rounded-3xl border border-stone-200 bg-white shadow-xl shadow-emerald-950/10">
            <div className="h-56 bg-[radial-gradient(circle_at_25%_25%,#86a789_0,transparent_30%),radial-gradient(circle_at_80%_70%,#d8a25e_0,transparent_28%),linear-gradient(135deg,#153f34,#52796f)]" />
            <div className="p-7">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-widest text-stone-500">Infraestrutura</p>
                  <p className="mt-1 font-semibold">Django + PostGIS</p>
                </div>
                <span
                  className={`h-3 w-3 rounded-full ${health.data?.status === 'ok' ? 'bg-emerald-500' : 'bg-amber-400'}`}
                  aria-label={health.data?.status === 'ok' ? 'API online' : 'Verificando API'}
                />
              </div>
              <p className="mt-5 text-sm text-stone-500">
                {health.isSuccess
                  ? `API online no schema ${health.data.schema}.`
                  : health.isError
                    ? 'API ainda não respondeu.'
                    : 'Verificando conexão com a API…'}
              </p>
            </div>
          </aside>
        </div>
      </section>
    </main>
  )
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="*" element={<Link to="/">Voltar ao início</Link>} />
    </Routes>
  )
}

export default App
