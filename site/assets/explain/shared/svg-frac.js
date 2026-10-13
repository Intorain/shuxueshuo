/* SVG labels mixing text runs and stacked fractions. parts: strings and [numerator, denominator] pairs, e.g. ['h = ', ['1', 'u']].
   SVG cannot measure text before layout, so widths are estimated from the label's font size; keep labels short. */
const width = (text, size) => [...text.replace(/&[a-z]+;/g, '<')].reduce((sum, c) => sum + (c === ' ' ? 0.3 : 0.6), 0) * size;

export function fracLabel(x, y, anchor, parts, {size = 13, cls = ''} = {}) {
  const small = Math.round(size * 8.5) / 10;
  const items = parts.map(p => typeof p === 'string'
    ? {text: p, w: width(p, size)}
    : {frac: p, w: Math.max(width(p[0], small), width(p[1], small)) + 3});
  const total = items.reduce((sum, item) => sum + item.w, 0);
  let left = anchor === 'end' ? x - total : anchor === 'middle' ? x - total / 2 : x;
  const bar = y - size * 0.32;
  const body = items.map(item => {
    const at = left;
    left += item.w;
    if (item.text) {
      const lead = item.text.length - item.text.trimStart().length;
      return item.text.trim() ? `<text x="${(at + width(' ', size) * lead).toFixed(1)}" y="${y}">${item.text.trim()}</text>` : '';
    }
    const mid = (at + item.w / 2).toFixed(1);
    return `<text x="${mid}" y="${(bar - 2).toFixed(1)}" text-anchor="middle" style="font-size:${small}px">${item.frac[0]}</text>`
      + `<rect x="${(at + 1).toFixed(1)}" y="${(bar - 0.55).toFixed(1)}" width="${(item.w - 2).toFixed(1)}" height="1.1"/>`
      + `<text x="${mid}" y="${(bar + small * 0.85).toFixed(1)}" text-anchor="middle" style="font-size:${small}px">${item.frac[1]}</text>`;
  }).join('');
  return `<g class="${cls}">${body}</g>`;
}
