import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ToastProvider, useToast } from './ToastProvider'

function TriggerToast() {
  const { notify } = useToast()
  return (
    <button
      type="button"
      onClick={() => notify({ title: 'Mapa pronto', message: 'Download liberado.', kind: 'success' })}
    >
      Notificar
    </button>
  )
}

describe('ToastProvider', () => {
  it('exibe e fecha uma notificação disparada por uma ação', async () => {
    const user = userEvent.setup()
    render(
      <ToastProvider>
        <TriggerToast />
      </ToastProvider>,
    )

    await user.click(screen.getByRole('button', { name: 'Notificar' }))
    expect(screen.getByRole('status')).toHaveTextContent('Mapa pronto')
    expect(screen.getByRole('status')).toHaveTextContent('Download liberado.')

    await user.click(screen.getByRole('button', { name: 'Fechar notificação' }))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('transforma falhas globais da API em alerta acessível', () => {
    render(<ToastProvider><span>Aplicação</span></ToastProvider>)
    act(() => {
      window.dispatchEvent(
        new CustomEvent('delta-api-error', { detail: { message: 'Servidor fora do ar.' } }),
      )
    })

    expect(screen.getByRole('alert')).toHaveTextContent('Serviço indisponível')
    expect(screen.getByRole('alert')).toHaveTextContent('Servidor fora do ar.')
  })
})
