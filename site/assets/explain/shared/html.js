export const escapeHtml = text => String(text).replace(/[&<>"]/g, ch => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[ch]));

// Sheets show tip notes after a “本题” badge, while the notes themselves are written starting with “本题”.
export const problemNote = note => escapeHtml(String(note).replace(/^本题[：:，,\s]*/, ''));
