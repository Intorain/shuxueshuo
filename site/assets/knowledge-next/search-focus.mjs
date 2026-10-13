// Tab may move from the input into any result without dismissing the list.
export function bindSearchFocus(input, results, close) {
  const box = input.closest('.kx-search');
  box.addEventListener('focusout', event => {
    if (!box.contains(event.relatedTarget)) close();
  });
  box.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    if (results.contains(event.target)) input.focus();
    close();
  });
  document.addEventListener('pointerdown', event => {
    if (!box.contains(event.target)) close();
  });
}
