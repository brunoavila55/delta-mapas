(() => {
  const body = document.body
  document.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-menu-toggle]')
    if (toggle) body.classList.toggle('menu-open')
    const close = event.target.closest('.flash button')
    if (close) close.parentElement.remove()
  })

  document.addEventListener('htmx:afterSwap', () => {
    body.classList.remove('menu-open')
  })

  window.setTimeout(() => {
    document.querySelectorAll('.flash').forEach((element) => element.remove())
  }, 7000)
})()
