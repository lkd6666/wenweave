export type ViewportFitIssue =
  | 'desktop-compact-layout'
  | 'page-overflow'
  | 'editor-toolbar-wrapped'
  | null

export interface DeviceCharacteristics {
  userAgent: string
  platform: string
  maxTouchPoints: number
}

export interface ViewportFitMetrics extends DeviceCharacteristics {
  viewportWidth: number
  documentWidth: number
  editorToolbarHeight?: number
}

export const DESKTOP_COMPACT_LAYOUT_MAX_WIDTH_PX = 991
export const ROOT_OVERFLOW_TOLERANCE_PX = 2
export const EDITOR_TOOLBAR_SINGLE_ROW_HEIGHT_PX = 56
export const EDITOR_TOOLBAR_WRAP_TOLERANCE_PX = 4

export function isMobileOrTabletDevice({
  userAgent,
  platform,
  maxTouchPoints,
}: DeviceCharacteristics): boolean {
  if (/Android|iPhone|iPad|iPod|Windows Phone/i.test(userAgent)) return true

  // iPadOS 13+ can identify itself as a Mac while retaining multi-touch input.
  return platform === 'MacIntel' && maxTouchPoints > 1
}

export function evaluateViewportFit(metrics: ViewportFitMetrics): ViewportFitIssue {
  if (metrics.viewportWidth <= 0 || isMobileOrTabletDevice(metrics)) return null

  if (metrics.viewportWidth <= DESKTOP_COMPACT_LAYOUT_MAX_WIDTH_PX) {
    return 'desktop-compact-layout'
  }

  if (
    typeof metrics.editorToolbarHeight === 'number'
    && metrics.editorToolbarHeight > EDITOR_TOOLBAR_SINGLE_ROW_HEIGHT_PX + EDITOR_TOOLBAR_WRAP_TOLERANCE_PX
  ) {
    return 'editor-toolbar-wrapped'
  }

  if (metrics.documentWidth > metrics.viewportWidth + ROOT_OVERFLOW_TOLERANCE_PX) {
    return 'page-overflow'
  }

  return null
}
