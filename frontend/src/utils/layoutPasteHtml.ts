export const MAX_LAYOUT_PASTE_BYTES = 5 * 1024 * 1024

const ALLOWED_TAGS = new Set(('article section div p span h1 h2 h3 h4 h5 h6 strong b em i u s strike '
  + 'blockquote ul ol li table thead tbody tfoot tr td th colgroup col br hr pre code figure figcaption small sup sub a img '
  + 'svg g path circle ellipse line polyline polygon rect text tspan title desc defs clippath mask lineargradient '
  + 'radialgradient stop use image filter feflood feblend fegaussianblur feoffset fecolormatrix fecomponenttransfer '
  + 'fefuncr fefuncg fefuncb fefunca fecomposite femerge femergenode fedropshadow').split(' '))
const DROP_TAGS = new Set(('script style link meta base iframe object embed template noscript canvas '
  + 'form button input textarea select option audio video source track foreignobject animate animatetransform animatemotion set').split(' '))
const ALLOWED_ATTRIBUTES = new Set(('style class id align width height colspan rowspan valign alt role title '
  + 'src href xlink:href xmlns viewbox x y x1 x2 y1 y2 cx cy r rx ry d points fill fill-opacity fill-rule '
  + 'stroke stroke-width stroke-opacity stroke-linecap stroke-linejoin stroke-miterlimit stroke-dasharray stroke-dashoffset '
  + 'transform transform-origin opacity preserveaspectratio text-anchor dominant-baseline font-size font-family font-weight '
  + 'offset stop-color stop-opacity gradientunits gradienttransform spreadmethod clip-path clip-rule mask maskunits '
  + 'maskcontentunits filter filterunits primitiveunits color-interpolation-filters in in2 result stddeviation dx dy '
  + 'operator k1 k2 k3 k4 mode type values slope intercept tablevalues flood-color flood-opacity').split(' '))

function safeImageOrLink(value: string): boolean {
  // eslint-disable-next-line no-control-regex -- Reject protocols obscured by whitespace or control characters.
  const compact = value.replace(/[\u0000-\u0020\u007f-\u009f]/g, '')
  if (/^data:/i.test(compact)) return /^data:image\/(png|jpe?g|gif|webp|avif|bmp);base64,/i.test(compact)
  return !/^[a-z][a-z0-9+.-]*:/i.test(compact) || /^https?:/i.test(compact)
}

/** Sanitize inside an inert template, before any content enters the editor frame. */
export function sanitizeLayoutPasteHtml(source: string): string {
  const template = document.createElement('template')
  template.innerHTML = source
  for (const element of Array.from(template.content.querySelectorAll('*'))) {
    const tag = element.tagName.toLowerCase()
    if (DROP_TAGS.has(tag)) {
      element.remove()
      continue
    }
    if (!ALLOWED_TAGS.has(tag)) {
      element.replaceWith(...element.childNodes)
      continue
    }
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase()
      if (!ALLOWED_ATTRIBUTES.has(name) && !name.startsWith('data-') && !name.startsWith('aria-')) {
        element.removeAttribute(attribute.name)
      } else if (['src', 'href', 'xlink:href', 'data-src', 'data-original', 'data-actualsrc'].includes(name)
          && !safeImageOrLink(attribute.value)) {
        element.removeAttribute(attribute.name)
      } else if (name === 'style' && /expression\s*\(|@import|behavior\s*:|-moz-binding/i.test(attribute.value)) {
        element.removeAttribute(attribute.name)
      }
    }
  }
  return template.innerHTML
}

export function plainTextLayoutHtml(text: string): string {
  return text.replace(/\r\n?/g, '\n').split('\n').map(line => {
    const paragraph = document.createElement('p')
    paragraph.textContent = line
    return line ? paragraph.outerHTML : '<p><br></p>'
  }).join('')
}
