import {
  MAX_CAPTURE_ASSETS,
  type CaptureAssetDescriptor,
  type CaptureDraftRead,
  type FinalizedCaptureDraft,
  type CapturePurpose,
  isAllowedCaptureAssetUrl,
} from './shared'
import { originalArticleDocument } from './articleSource'
import { inlineAuthoredStyles } from './authoredStyles'

interface AssetRecord extends CaptureAssetDescriptor {
  imageElements: Set<Element>
  styleElements: Map<HTMLElement | SVGElement, Set<string>>
  isCover: boolean
}

interface CaptureDraftState {
  root: HTMLElement
  title: string
  assets: AssetRecord[]
  omittedAssetCount: number
  coverAssetId: string | null
}

const drafts = new Map<string, CaptureDraftState>()
const CSS_URL_PATTERN = /url\(\s*(['"]?)(.*?)\1\s*\)/gi
const IMAGE_SOURCE_ATTRIBUTES = ['data-src', 'data-original', 'data-actualsrc', 'src'] as const
function captureId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
}

function resolveAssetUrl(rawUrl: string, currentUrl: string): string | null {
  try {
    const resolved = new URL(rawUrl.trim(), currentUrl).toString()
    return isAllowedCaptureAssetUrl(resolved) ? resolved : null
  } catch {
    return null
  }
}

function imageSource(element: Element): string {
  for (const attribute of [...IMAGE_SOURCE_ATTRIBUTES, 'href', 'xlink:href']) {
    const value = element.getAttribute(attribute)?.trim()
    if (value && !value.startsWith('data:image/svg')) return value
  }
  return ''
}

function removeImageSourceAttributes(element: Element): void {
  for (const attribute of [...IMAGE_SOURCE_ATTRIBUTES, 'href', 'xlink:href']) element.removeAttribute(attribute)
  element.removeAttribute('srcset')
  element.removeAttribute('data-srcset')
}

function removeAssets(state: CaptureDraftState, initiallyFailed: Set<string>): Set<string> {
  const failed = new Set(initiallyFailed)
  for (const record of state.assets) {
    if (!failed.has(record.assetId)) continue
    for (const element of record.imageElements) element.remove()
    for (const [element, properties] of record.styleElements) {
      for (const property of properties) element.style.removeProperty(property)
    }
  }
  // A failed URL invalidates its CSS declaration, but other uses of the same
  // image elsewhere in the article remain intact.
  for (const record of state.assets) {
    if (!record.isCover && !isRecordStillReferenced(record)) failed.add(record.assetId)
  }
  return failed
}

function isRecordStillReferenced(record: AssetRecord): boolean {
  for (const element of record.imageElements) {
    if (element.parentNode) return true
  }
  for (const [element, properties] of record.styleElements) {
    for (const property of properties) {
      if (element.style.getPropertyValue(property).includes(`layout-capture://${record.assetId}`)) return true
    }
  }
  return false
}

function readTitle(doc: Document): string {
  const candidates = [
    doc.querySelector('#activity-name')?.textContent,
    doc.querySelector('h1.rich_media_title')?.textContent,
    doc.querySelector('h1')?.textContent,
    doc.title,
  ]
  return candidates.map((value) => value?.replace(/\s+/g, ' ').trim()).find(Boolean)?.slice(0, 200) || '未命名参考文章'
}

function coverSource(doc: Document, currentUrl: string): string | null {
  const candidates = [
    doc.querySelector('#js_cover img'),
    doc.querySelector('img#js_cover'),
    doc.querySelector('#js_cover_image'),
  ]
  for (const candidate of candidates) {
    const rawSource = candidate ? imageSource(candidate) : ''
    const resolved = rawSource ? resolveAssetUrl(rawSource, currentUrl) : null
    if (resolved) return resolved
  }
  for (const selector of ["meta[property='og:image']", "meta[name='twitter:image']", "link[rel='image_src']"]) {
    const candidate = doc.querySelector(selector)
    const rawSource = candidate?.getAttribute(candidate.tagName === 'LINK' ? 'href' : 'content') || ''
    const resolved = rawSource ? resolveAssetUrl(rawSource, currentUrl) : null
    if (resolved) return resolved
  }
  for (const script of Array.from(doc.scripts)) {
    const match = script.textContent?.match(/\bmsg_cdn_url\s*=\s*(['"])(.*?)\1/s)
    const rawSource = match?.[2]?.replaceAll('\\/', '/') || ''
    const resolved = rawSource ? resolveAssetUrl(rawSource, currentUrl) : null
    if (resolved) return resolved
  }
  return null
}

export function createCaptureDraft(
  doc: Document,
  currentUrl: string,
  purpose: CapturePurpose = 'layout_reference',
  sheetSource: Document = doc,
): CaptureDraftRead {
  doc = originalArticleDocument(doc)
  const sourceRoot = doc.querySelector<HTMLElement>('#js_content')
  if (!sourceRoot) throw new Error('当前页面尚未显示微信文章正文，请先完成验证并等待文章加载')
  inlineAuthoredStyles(doc, sourceRoot, sheetSource)
  // The platform initially hides the article until its scripts finish loading.
  // This loading gate is not an author style.
  if (['hidden', 'collapse'].includes(sourceRoot.style.visibility)) sourceRoot.style.removeProperty('visibility')
  if (sourceRoot.style.opacity && Number(sourceRoot.style.opacity) === 0) sourceRoot.style.removeProperty('opacity')
  if (sourceRoot.style.display === 'none') sourceRoot.style.removeProperty('display')
  const root = sourceRoot.cloneNode(true) as HTMLElement
  const sourceToAsset = new Map<string, AssetRecord>()
  const assets: AssetRecord[] = []
  const unsupportedSources = new Set<string>()
  const register = (url: string): AssetRecord => {
    const existing = sourceToAsset.get(url)
    if (existing) return existing
    const record: AssetRecord = {
      assetId: captureId(),
      url,
      imageElements: new Set(),
      styleElements: new Map(),
      isCover: false,
    }
    sourceToAsset.set(url, record)
    assets.push(record)
    return record
  }

  let coverAssetId: string | null = null
  if (purpose === 'web_article_import') {
    const source = coverSource(doc, currentUrl)
    if (source) {
      const coverAsset = register(source)
      coverAsset.isCover = true
      coverAssetId = coverAsset.assetId
    }
  }

  const sourceImages = Array.from(sourceRoot.querySelectorAll('img, svg image'))
  const clonedImages = Array.from(root.querySelectorAll('img, svg image'))
  sourceImages.forEach((sourceImage, index) => {
    const clonedImage = clonedImages[index]
    if (!clonedImage) return
    const rawSource = imageSource(sourceImage)
    const resolved = rawSource ? resolveAssetUrl(rawSource, currentUrl) : null
    if (!resolved) {
      unsupportedSources.add(rawSource || `missing-image-${index}`)
      clonedImage.remove()
      return
    }
    const asset = register(resolved)
    asset.imageElements.add(clonedImage)
    removeImageSourceAttributes(clonedImage)
    clonedImage.setAttribute(clonedImage.localName === 'image' ? 'href' : 'src', `layout-capture://${asset.assetId}`)
  })

  const styledElements = [root, ...Array.from(root.querySelectorAll<HTMLElement | SVGElement>('*'))]
  styledElements.forEach((element, index) => {
    if (!element.style) return
    for (const property of Array.from(element.style)) {
      const value = element.style.getPropertyValue(property)
      const matches = Array.from(value.matchAll(CSS_URL_PATTERN))
      if (!matches.length) continue
      const urls = matches.map((match) => {
        const raw = match[2]?.trim() || ''
        return raw.startsWith('#') ? raw : resolveAssetUrl(raw, currentUrl)
      })
      if (urls.some((url) => !url)) {
        matches.forEach((match, urlIndex) => {
          if (!urls[urlIndex]) unsupportedSources.add(match[2] || `invalid-style-${index}-${property}-${urlIndex}`)
        })
        element.style.removeProperty(property)
        continue
      }
      let urlIndex = 0
      const rewritten = value.replace(CSS_URL_PATTERN, (match) => {
        const url = urls[urlIndex++]!
        if (url.startsWith('#')) return match
        const asset = register(url)
        const properties = asset.styleElements.get(element) || new Set<string>()
        properties.add(property)
        asset.styleElements.set(element, properties)
        return `url("layout-capture://${asset.assetId}")`
      })
      element.style.setProperty(property, rewritten, element.style.getPropertyPriority(property))
    }
  })

  const state: CaptureDraftState = {
    root,
    title: readTitle(doc),
    assets,
    omittedAssetCount: unsupportedSources.size,
    coverAssetId,
  }
  const overLimit = new Set(assets.slice(MAX_CAPTURE_ASSETS).map((asset) => asset.assetId))
  const removed = removeAssets(state, overLimit)
  state.omittedAssetCount += removed.size
  const activeAssets = assets.filter((asset) => (
    !removed.has(asset.assetId) && (asset.isCover || isRecordStillReferenced(asset))
  ))
  state.assets = activeAssets
  if (coverAssetId && !activeAssets.some((asset) => asset.assetId === coverAssetId)) state.coverAssetId = null

  const draftId = captureId()
  drafts.set(draftId, state)
  return {
    draftId,
    title: state.title,
    assets: activeAssets.map(({ assetId, url }) => ({ assetId, url })),
    omittedAssetCount: state.omittedAssetCount,
    coverAssetId: state.coverAssetId,
  }
}

export function finalizeCaptureDraft(draftId: string, failedAssetIds: string[]): FinalizedCaptureDraft {
  const state = drafts.get(draftId)
  if (!state) throw new Error('微信文章采集上下文已失效，请重新点击扩展采集')
  const knownIds = new Set(state.assets.map((asset) => asset.assetId))
  const requestedFailures = new Set(failedAssetIds.filter((assetId) => knownIds.has(assetId)))
  const removed = removeAssets(state, requestedFailures)
  const activeAssets = state.assets.filter((asset) => (
    !removed.has(asset.assetId) && (asset.isCover || isRecordStillReferenced(asset))
  ))
  const omittedBodyAssets = Array.from(removed).filter((assetId) => {
    const asset = state.assets.find((candidate) => candidate.assetId === assetId)
    return Boolean(asset && (asset.imageElements.size > 0 || asset.styleElements.size > 0))
  }).length
  drafts.delete(draftId)
  return {
    sourceHtml: state.root.outerHTML,
    title: state.title,
    activeAssetIds: activeAssets.map((asset) => asset.assetId),
    omittedAssetCount: state.omittedAssetCount + omittedBodyAssets,
    coverAssetId: state.coverAssetId && !removed.has(state.coverAssetId) ? state.coverAssetId : null,
  }
}

export function discardCaptureDraft(draftId: string): void {
  drafts.delete(draftId)
}
