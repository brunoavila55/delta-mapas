import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Pagination, SearchInput } from './ListControls'

describe('SearchInput', () => {
  it('envia o texto digitado e permite limpar a busca', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const { rerender } = render(<SearchInput value="" onChange={onChange} />)

    await user.type(screen.getByRole('textbox', { name: 'Buscar' }), 'talhão')
    expect(onChange).toHaveBeenCalled()

    rerender(<SearchInput value="talhão" onChange={onChange} />)
    await user.click(screen.getByRole('button', { name: 'Limpar busca' }))
    expect(onChange).toHaveBeenLastCalledWith('')
  })
})

describe('Pagination', () => {
  it('navega respeitando os limites da lista', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()
    const { rerender } = render(
      <Pagination page={1} pageSize={20} count={45} onPageChange={onPageChange} />,
    )

    expect(screen.getByRole('button', { name: /anterior/i })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /próxima/i }))
    expect(onPageChange).toHaveBeenCalledWith(2)

    rerender(
      <Pagination page={3} pageSize={20} count={45} onPageChange={onPageChange} />,
    )
    expect(screen.getByRole('button', { name: /próxima/i })).toBeDisabled()
  })
})
