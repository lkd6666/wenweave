import {
  MAX_CAPTURE_ASSETS,
  type CaptureAssetDescriptor,
  type CaptureDraftRead,
  type FinalizedCaptureDraft,
  type CapturePurpose,
  isAllowedWechatAssetUrl,
} from './shared'

interface AssetRecord extends CaptureAssetDescriptor {
  imageElements: Set<Element>
  backgroundElements: Set<HTMLElement>
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
    return isAllowedWechatAssetUrl(resolved) ? resolved : null
  } catch {
    return null
  }
}

function imageSource(element: Element): string {
  for (const attribute of IMAGE_SOURCE_ATTRIBUTES) {
    const value = element.getAttribute(attribute)?.trim()
    if (value && !value.startsWith('data:image/svg')) return value
  }
  return ''
}

function removeImageSourceAttributes(element: Element): void {
  for (const attribute of IMAGE_SOURCE_ATTRIBUTES) element.removeAttribute(attribute)
  element.removeAttribute('srcset')
  element.removeAttribute('data-srcset')
}

function removeAssets(state: CaptureDraftState, initiallyFailed: Set<string>): Set<string> {
  const failed = new Set(initiallyFailed)
  let expanded = true
  while (expanded) {
    expanded = false
    for (const record of state.assets) {
      if (!failed.has(record.assetId)) continue
      for (const element of record.backgroundElements) {
        for (const related of state.assets) {
          if (related.backgroundElements.has(element) && !failed.has(related.assetId)) {
            failed.add(related.assetId)
            expanded = true
          }
        }
      }
    }
  }

  for (const record of state.assets) {
    if (!failed.has(record.assetId)) continue
    for (const element of record.imageElements) element.remove()
  }
  const failedBackgrounds = new Set<HTMLElement>()
  for (const record of state.assets) {
    if (!failed.has(record.assetId)) continue
    for (const element of record.backgroundElements) failedBackgrounds.add(element)
  }
  for (const element of failedBackgrounds) element.style.removeProperty('background-image')
  return failed
}

function isRecordStillReferenced(record: AssetRecord): boolean {
  for (const element of record.imageElements) {
    if (element.parentNode) return true
  }
  for (const element of record.backgroundElements) {
    if (element.style.backgroundImage.includes(`layout-capture://${record.assetId}`)) return true
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
): CaptureDraftRead {
  const sourceRoot = doc.querySelector<HTMLElement>('#js_content')
  if (!sourceRoot) throw new Error('当前页面尚未显示微信文章正文，请先完成验证并等待文章加载')
  const root = sourceRoot.cloneNode(true) as HTMLElement
  const sourceToAsset = new Map<string, AssetRecord>()
  const assets: AssetRecord[] = []
  const unsupportedSources = new Set<string>()
  const sourceElements = [sourceRoot, ...Array.from(sourceRoot.querySelectorAll<HTMLElement>('*'))]
  const clonedElements = [root, ...Array.from(root.querySelectorAll<HTMLElement>('*'))]

  const register = (url: string): AssetRecord => {
    const existing = sourceToAsset.get(url)
    if (existing) return existing
    const record: AssetRecord = {
      assetId: captureId(),
      url,
      imageElements: new Set(),
      backgroundElements: new Set(),
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

  const sourceImages = Array.from(sourceRoot.querySelectorAll('img'))
  const clonedImages = Array.from(root.querySelectorAll('img'))
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
    clonedImage.setAttribute('src', `layout-capture://${asset.assetId}`)
  })

  sourceElements.forEach((sourceElement, index) => {
    const clonedElement = clonedElements[index]
    if (!clonedElement) return
    const backgroundImage = sourceElement.style.backgroundImage
    if (!backgroundImage || !backgroundImage.toLowerCase().includes('url(')) return
    const matches = Array.from(backgroundImage.matchAll(CSS_URL_PATTERN))
    const resolved = matches.map((match) => resolveAssetUrl(match[2] || '', currentUrl))
    if (!matches.length || resolved.some((url) => !url)) {
      for (const [matchIndex, match] of matches.entries()) {
        if (!resolved[matchIndex]) unsupportedSources.add(match[2] || `invalid-background-${index}-${matchIndex}`)
      }
      clonedElement.style.removeProperty('background-image')
      return
    }
    let assetIndex = 0
    clonedElement.style.backgroundImage = backgroundImage.replace(CSS_URL_PATTERN, () => {
      const asset = register(resolved[assetIndex++] as string)
      asset.backgroundElements.add(clonedElement)
      return `url("layout-capture://${asset.assetId}")`
    })
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
    return Boolean(asset && (asset.imageElements.size > 0 || asset.backgroundElements.size > 0))
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
