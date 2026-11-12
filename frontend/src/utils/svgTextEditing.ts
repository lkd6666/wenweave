const SVG_NAMESPACE = 'http://www.w3.org/2000/svg'
const SVG_TEXT_ELEMENTS = new Set(['text', 'tspan', 'textPath'])
const HTML_INTEGRATION_POINTS = new Set(['foreignObject', 'desc', 'title'])

/** Normalize browser-created line breaks on a clone before serializing SVG text. */
export function normalizeSvgTextBreaks(root: Element): void {
  for (const br of root.querySelectorAll('br')) {
    for (let parent = br.parentElement; parent && root.contains(parent); parent = parent.parentElement) {
      if (parent.namespaceURI !== SVG_NAMESPACE) continue
      // HTML line breaks inside foreignObject (and other integration points)
      // are valid. A nested SVG text element is handled before reaching here.
      if (HTML_INTEGRATION_POINTS.has(parent.localName)) break
      if (SVG_TEXT_ELEMENTS.has(parent.localName)) {
        // Chromium inserts an HTML <br> when editable SVG text is cleared.
        // Preserve the user's empty text/word separation without emitting a
        // tag that makes the HTML5 parser break out of the SVG namespace.
        br.replaceWith(br.ownerDocument.createTextNode('\n'))
        break
      }
    }
  }
}
