/* Model-authored derivations can contain raw LaTeX or text with delimited math. */
(() => {
  'use strict';
  window.ExplanationMath = {
    renderLine(element, source) {
      const text = String(source ?? '').trim();
      // Auto-render removes delimiters and handles prose around each formula.
      // Both renderers keep model content as text and disable trusted TeX/HTML.
      if (/(?:^|[^\\])\$|\\[([]/.test(text)) {
        window.PracticeMath.render(element, text);
      } else {
        try {
          window.katex.render(text, element, {
            displayMode: true, throwOnError: true, strict: 'ignore', trust: false
          });
        } catch {
          // Preserve a malformed model line as readable text, not a red KaTeX error.
          element.textContent = text;
          element.title = '此行公式暂未排版';
        }
      }
      return element;
    }
  };
})();
