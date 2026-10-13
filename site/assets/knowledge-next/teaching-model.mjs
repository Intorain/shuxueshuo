// The same selector semantics are used by the publisher and the preview.
// Leaves are reference arrays (associations) or {ref, resource, case?, note?} (tips).
export function branches(tree, conditions = {}) {
  if (!tree) return [];
  if (tree.field)
    return Object.entries(tree.options).flatMap(([value, child]) =>
      branches(child, { ...conditions, [tree.field]: value })
    );
  return [{ conditions, value: tree }];
}

// `options` maps a choice field to all of its option values. Branches usually exist only for
// accepted values, so listing candidates over a partly covered unanswered choice would reveal
// which options are correct; such candidates are withheld.
export function select(tree, choices = {}, options = {}) {
  const possible = branches(tree).filter((b) =>
    Object.entries(b.conditions).every(([field, value]) => choices[field] == null || choices[field] === value)
  );
  const actual = possible.filter((b) => Object.keys(b.conditions).every((field) => choices[field] != null));
  const pending = possible.filter((b) => !actual.includes(b));
  const covered = (field) =>
    (options[field] || []).every((value) => pending.some((b) => b.conditions[field] === value));
  const withheld = pending.some((b) =>
    Object.keys(b.conditions).some((field) => choices[field] == null && !covered(field))
  );
  return { actual, candidates: withheld ? [] : pending, withheld };
}

// A choice counts only after its step is passed; an unsubmitted pick must not reveal whether it matches.
export function confirmedChoices(steps = [], state) {
  const open = new Set(
    steps
      .slice(state.active)
      .filter((s) => s.interaction.type === 'choice')
      .map((s) => s.interaction.field)
  );
  return Object.fromEntries(Object.entries(state.choices || {}).filter(([field]) => !open.has(field)));
}

export function previewHref(path) {
  const url = new URL(path, 'https://preview.invalid');
  url.searchParams.set('knowledge', 'next');
  return url.pathname + url.search + url.hash;
}

export const libraryPath = (path) => path.replace(/[^/]+\/$/, '');

// Links from a problem page back to its library or to another associated problem stay in the preview.
export function previewTarget(url, { paths, library, topic }) {
  if (library !== '/' && url.pathname === library) return topic;
  if (paths.includes(url.pathname)) return previewHref(url.pathname + url.search + url.hash);
  return null;
}
