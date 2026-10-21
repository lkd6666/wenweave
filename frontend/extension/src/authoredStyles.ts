import { calculate, compare } from 'specificity'

type StyledElement = HTMLElement | SVGElement
type Specificity = ReturnType<typeof calculate>
interface MatchedStyle {
  style: CSSStyleDeclaration
  specificity: Specificity
  order: number
}

const INHERITED_PROPERTIES = new Set([
  'color', 'font', 'font-family', 'font-size', 'font-style', 'font-weight', 'line-height',
  'letter-spacing', 'text-align', 'text-indent', 'text-transform', 'white-space', 'word-break',
  'overflow-wrap', 'direction', 'writing-mode', 'list-style', 'list-style-type',
])
const DARK_RUNTIME_SELECTOR = /js_darkmode__|data_color_scheme_dark|data-darkmode-/i

function lightMediaMatches(condition: string): boolean {
  // Evaluate responsive rules at this viewport, but always select the light
  // author palette. Values remain declarations such as 32%, not pixel boxes.
  const lightCondition = condition.replace(
    /\(\s*prefers-color-scheme\s*:\s*(dark|light|no-preference)\s*\)/gi,
    (_match, scheme: string) => scheme.toLowerCase() === 'light' ? '(min-width: 0px)' : '(max-width: -1px)',
  )
  return !lightCondition || window.matchMedia(lightCondition).matches
}

function mergeDeclarations(target: CSSStyleDeclaration, matches: MatchedStyle[], inline: string): void {
  matches.sort((left, right) => compare(left.specificity, right.specificity) || left.order - right.order)
  const original = document.createElement('span').style
  original.cssText = inline
  // CSSStyleDeclaration handles shorthands. Apply the two priority levels
  // separately so stylesheet !important also wins over normal inline styles.
  for (const important of [false, true]) {
    for (const style of [...matches.map((match) => match.style), original]) {
      for (const property of Array.from(style)) {
        if ((style.getPropertyPriority(property) === 'important') !== important) continue
        target.setProperty(property, style.getPropertyValue(property), important ? 'important' : '')
      }
    }
  }
}

function pseudoText(content: string): string | null {
  const quoted = content.trim().match(/^(?:"([\s\S]*)"|'([\s\S]*)')$/)
  if (!quoted) return null
  return (quoted[1] ?? quoted[2] ?? '')
    .replace(/\\([0-9a-f]{1,6})\s?/gi, (_match, value: string) => String.fromCodePoint(Number.parseInt(value, 16)))
    .replace(/\\([\\'"()])/g, '$1')
}

/** Inline author CSS without reading any rendered/computed style. */
export function inlineAuthoredStyles(doc: Document, root: HTMLElement, sheetSource: Document = doc): void {
  const elements = Array.from(doc.querySelectorAll<StyledElement>('*')).filter((element) => Boolean(element.style))
  const originals = new Map(elements.map((element) => [element, element.getAttribute('style') || '']))
  const matched = new Map<StyledElement, MatchedStyle[]>()
  const pseudos = new Map<StyledElement, Map<string, MatchedStyle[]>>()
  let order = 0

  function collect(rules: CSSRuleList): void {
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSStyleRule) {
        const ruleOrder = order++
        if (DARK_RUNTIME_SELECTOR.test(rule.selectorText)) continue
        // Split only top-level commas; functional selectors can contain commas.
        const selectors = rule.selectorText.match(/(?:[^,(]|\((?:[^()]|\([^()]*\))*\))+/g) || []
        for (const selectorText of selectors) {
          const selector = selectorText.trim()
          const pseudo = selector.match(/::?(before|after)$/)
          const baseSelector = pseudo ? selector.slice(0, pseudo.index) : selector
          let specificity: Specificity
          let selected: StyledElement[]
          try {
            specificity = calculate(selector)
            selected = Array.from(doc.querySelectorAll<StyledElement>(baseSelector)).filter((element) => Boolean(element.style))
          } catch {
            continue
          }
          for (const element of selected) {
            const match = { style: rule.style, specificity, order: ruleOrder }
            if (pseudo) {
              const groups = pseudos.get(element) || new Map<string, MatchedStyle[]>()
              const group = groups.get(pseudo[1]!) || []
              group.push(match)
              groups.set(pseudo[1]!, group)
              pseudos.set(element, groups)
            } else {
              const group = matched.get(element) || []
              group.push(match)
              matched.set(element, group)
            }
          }
        }
      } else if (rule instanceof CSSMediaRule) {
        if (lightMediaMatches(rule.conditionText)) collect(rule.cssRules)
      } else if (rule instanceof CSSSupportsRule) {
        if (CSS.supports(rule.conditionText)) collect(rule.cssRules)
      }
    }
  }

  // Inert parsed documents do not load external stylesheets. Read their inline
  // author rules and any accessible original sheets from the article tab.
  for (const node of Array.from(doc.querySelectorAll<HTMLStyleElement | HTMLLinkElement>('style, link[rel~="stylesheet"]'))) {
    if (/js_darkmode__|darkreader/i.test(node.id) || !lightMediaMatches(node.media)) continue
    try {
      let sheet: CSSStyleSheet
      if (node.localName === 'style') {
        sheet = new CSSStyleSheet()
        sheet.replaceSync(node.textContent || '')
      } else {
        const href = new URL(node.getAttribute('href') || '', sheetSource.baseURI).href
        const originalSheet = Array.from(sheetSource.styleSheets).find((candidate) => candidate.href === href)
        if (!originalSheet || originalSheet.disabled) continue
        sheet = originalSheet
      }
      collect(sheet.cssRules)
    } catch {
      // Keep the original inline HTML when a stylesheet cannot be parsed.
    }
  }

  for (const [element, matches] of matched) {
    element.style.cssText = ''
    mergeDeclarations(element.style, matches, originals.get(element) || '')
  }
  const inherited = document.createElement('span').style
  const ancestors: StyledElement[] = []
  for (let ancestor = root.parentElement; ancestor; ancestor = ancestor.parentElement) ancestors.unshift(ancestor)
  for (const ancestor of ancestors) {
    for (const property of Array.from(ancestor.style)) {
      if (property.startsWith('--') || INHERITED_PROPERTIES.has(property)) {
        inherited.setProperty(property, ancestor.style.getPropertyValue(property))
      }
    }
  }
  // Inherited declarations have lower priority than declarations on the root.
  const rootStyle = root.style.cssText
  root.style.cssText = inherited.cssText
  const own = document.createElement('span').style
  own.cssText = rootStyle
  for (const property of Array.from(own)) root.style.setProperty(property, own.getPropertyValue(property), own.getPropertyPriority(property))

  for (const [element, groups] of pseudos) {
    if (!root.contains(element) || ['img', 'input', 'svg'].includes(element.localName)) continue
    for (const [pseudo, matches] of groups) {
      const generated = doc.createElement('span')
      mergeDeclarations(generated.style, matches, '')
      const content = pseudoText(generated.style.getPropertyValue('content'))
      if (content === null) continue
      generated.style.removeProperty('content')
      generated.textContent = content
      generated.setAttribute('data-layout-capture-generated', pseudo)
      if (pseudo === 'before') element.prepend(generated)
      else element.append(generated)
    }
  }
}
