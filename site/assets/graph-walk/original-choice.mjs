/** Original exam choices are matched by the verified solver, never inferred from prose in the UI. */
export function matchedOriginalChoice(completion, targetRef = completion?.target_ref || completion?.identity?.[0]) {
  const choice = completion?.original_choice;
  if (completion?.status !== 'verified' || completion.available === false ||
      choice?.status !== 'matched' || choice.kind !== 'single_choice' ||
      typeof choice.target_ref !== 'string' || choice.target_ref !== targetRef ||
      !Array.isArray(choice.options) || choice.options.length < 2 ||
      !Array.isArray(choice.correct_labels) || choice.correct_labels.length !== 1) return null;
  if (choice.options.some(option => typeof option?.label !== 'string' || !option.label ||
      typeof option.text !== 'string' || !option.text.trim())) return null;
  const labels = new Set(choice.options.map(option => option.label));
  if (labels.size !== choice.options.length || !labels.has(choice.correct_labels[0])) return null;
  return choice;
}
