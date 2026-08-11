export function formatDate(value: string | null | undefined, withTime = false) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    ...(withTime ? { timeStyle: 'short' } : {}),
  }).format(new Date(value))
}

export function formatArea(value: string | number) {
  return `${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 }).format(Number(value))} ha`
}

export function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Ocorreu um erro inesperado.'
}
