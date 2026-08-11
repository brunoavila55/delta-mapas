import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../components/ToastProvider'
import type { MapJob, Paginated } from '../lib/types'
import { JobsPage } from './JobsPage'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('../lib/api', () => ({ api: apiMock }))
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({
    session: {
      user: { id: 'user-1', username: 'admin' },
      tenant: { id: 'tenant-1', name: 'Demo', schema_name: 'demo', role: 'OWNER' },
    },
  }),
}))

const baseJob: MapJob = {
  id: '11111111-1111-4111-8111-111111111111',
  status: 'PROCESSING',
  progress: 50,
  current_step: 'Calculando NDVI',
  index_type: 'NDVI',
  geometry_snapshot: { type: 'MultiPolygon', coordinates: [] },
  property_id: '22222222-2222-4222-8222-222222222222',
  property_name: 'Fazenda Demo',
  requested_scene_date: null,
  date_from: '2026-07-01',
  date_to: '2026-07-31',
  max_cloud_cover: '20.00',
  stac_item_id: '',
  error_code: '',
  error_message: '',
  credit_cost: 1,
  created_by: 'user-1',
  created_at: '2026-08-11T00:00:00Z',
  heartbeat_at: '2026-08-11T00:10:00Z',
  started_at: '2026-08-11T00:01:00Z',
  finished_at: null,
  cancelled_at: null,
  cancelled_by: null,
  reprocessed_from_id: null,
  generated_map_id: null,
}

function renderPage(job: MapJob) {
  const response: Paginated<MapJob> = {
    count: 1,
    next: null,
    previous: null,
    results: [job],
  }
  apiMock.get.mockResolvedValue(response)
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <ToastProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/jobs']}>
          <JobsPage />
        </MemoryRouter>
      </QueryClientProvider>
    </ToastProvider>,
  )
}

describe('JobsPage', () => {
  beforeEach(() => {
    apiMock.get.mockReset()
    apiMock.post.mockReset()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('cancela um job ativo e confirma a devolução do crédito', async () => {
    const user = userEvent.setup()
    apiMock.post.mockResolvedValue({ ...baseJob, status: 'CANCELLED' })
    renderPage(baseJob)

    await user.click(await screen.findByRole('button', { name: 'Cancelar' }))

    await waitFor(() => {
      expect(apiMock.post).toHaveBeenCalledWith(`/map-jobs/${baseJob.id}/cancel/`)
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Processamento cancelado')
  })

  it('reprocessa um job terminal com chave de idempotência', async () => {
    const user = userEvent.setup()
    const failedJob: MapJob = {
      ...baseJob,
      status: 'FAILED',
      error_code: 'JOB_STALLED',
      error_message: 'Processamento expirado.',
      finished_at: '2026-08-11T02:00:00Z',
    }
    apiMock.post.mockResolvedValue({ ...baseJob, id: '33333333-3333-4333-8333-333333333333' })
    renderPage(failedJob)

    await user.click(await screen.findByRole('button', { name: 'Reprocessar' }))

    await waitFor(() => {
      expect(apiMock.post).toHaveBeenCalledWith(
        `/map-jobs/${failedJob.id}/reprocess/`,
        undefined,
        { 'Idempotency-Key': expect.any(String) },
      )
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Reprocessamento enfileirado')
  })
})
