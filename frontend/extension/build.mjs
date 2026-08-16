import { createHash } from 'node:crypto'
import { cp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { dirname, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import JSZip from 'jszip'

const extensionRoot = dirname(fileURLToPath(import.meta.url))
const frontendRoot = resolve(extensionRoot, '..')
const outputDir = resolve(frontendRoot, 'extension-dist')
const downloadDir = resolve(frontendRoot, 'public', 'downloads')
const downloadFileName = 'layout-capture-extension.zip'
const downloadMetadataFileName = 'layout-capture-extension.json'
const rawAppOrigin = process.env.LAYOUT_CAPTURE_APP_ORIGIN || 'http://localhost:5173'
const productionBuild = process.env.LAYOUT_CAPTURE_BUILD_MODE === 'production'

function validateAppOrigin(rawValue) {
  let url
  try {
    url = new URL(rawValue)
  } catch {
    throw new Error('LAYOUT_CAPTURE_APP_ORIGIN must be an absolute application origin')
  }
  const isLoopback = ['localhost', '127.0.0.1'].includes(url.hostname)
  if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && isLoopback))
    || url.origin !== rawValue.replace(/\/$/, '')
    || url.username
    || url.password) {
    throw new Error('LAYOUT_CAPTURE_APP_ORIGIN must be an HTTPS origin; HTTP is allowed only for local development')
  }
  if (productionBuild && url.protocol !== 'https:') {
    throw new Error('Production extension builds require an HTTPS LAYOUT_CAPTURE_APP_ORIGIN')
  }
  return url.origin
}

const appOrigin = validateAppOrigin(rawAppOrigin)
const appOrigins = [appOrigin]
if (!productionBuild) {
  const developmentUrl = new URL(appOrigin)
  if (developmentUrl.hostname === 'localhost' || developmentUrl.hostname === '127.0.0.1') {
    developmentUrl.hostname = developmentUrl.hostname === 'localhost' ? '127.0.0.1' : 'localhost'
    appOrigins.push(developmentUrl.origin)
  }
}
const entries = ['appBridge', 'wechatCapture', 'background', 'popup']

async function collectFiles(directory) {
  const files = []
  const entries = await readdir(directory, { withFileTypes: true })
  entries.sort((left, right) => left.name.localeCompare(right.name))
  for (const entry of entries) {
    const absolutePath = resolve(directory, entry.name)
    if (entry.isDirectory()) {
      files.push(...await collectFiles(absolutePath))
    } else if (entry.isFile()) {
      files.push(absolutePath)
    }
  }
  return files
}

await rm(outputDir, { recursive: true, force: true })
await mkdir(outputDir, { recursive: true })

for (const [index, entry] of entries.entries()) {
  await build({
    configFile: false,
    root: frontendRoot,
    publicDir: false,
    define: { __LAYOUT_CAPTURE_ALLOWED_APP_ORIGINS__: JSON.stringify(appOrigins) },
    build: {
      outDir: outputDir,
      emptyOutDir: index === 0,
      minify: false,
      sourcemap: false,
      lib: {
        entry: resolve(extensionRoot, 'src', `${entry}.ts`),
        formats: ['iife'],
        name: `LayoutCapture${entry}`,
        fileName: () => `${entry.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}.js`,
      },
    },
  })
}

const packageJson = JSON.parse(await readFile(resolve(frontendRoot, 'package.json'), 'utf8'))
const extensionVersion = process.env.LAYOUT_CAPTURE_EXTENSION_VERSION
  || (packageJson.version === '0.0.0' ? '1.1.0' : packageJson.version)
const versionParts = extensionVersion.split('.')
if (versionParts.length < 1
  || versionParts.length > 4
  || versionParts.some((part) => !/^(0|[1-9]\d*)$/.test(part) || Number(part) > 65535)) {
  throw new Error('LAYOUT_CAPTURE_EXTENSION_VERSION must be a Chrome-compatible version with 1-4 numeric parts')
}
const appMatches = appOrigins.map((origin) => `${origin}/*`)
const manifest = {
  manifest_version: 3,
  name: '排版采集助手',
  description: '在用户完成微信验证后采集公众号文章、图片与排版，并回传到系统预览。',
  version: extensionVersion,
  permissions: ['storage', 'tabs', 'alarms', 'scripting'],
  host_permissions: [
    ...appMatches,
    'https://mp.weixin.qq.com/*',
    'https://*.qpic.cn/*',
    'https://*.qlogo.cn/*',
    'https://res.wx.qq.com/*',
  ],
  background: { service_worker: 'background.js' },
  action: { default_popup: 'popup.html', default_title: '排版采集助手' },
  content_scripts: [
    { matches: appMatches, js: ['app-bridge.js'], run_at: 'document_start' },
    { matches: ['https://mp.weixin.qq.com/*'], js: ['wechat-capture.js'], run_at: 'document_idle' },
  ],
  content_security_policy: { extension_pages: "script-src 'self'; object-src 'none'" },
}

await writeFile(resolve(outputDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
await cp(resolve(extensionRoot, 'popup.html'), resolve(outputDir, 'popup.html'))
await cp(resolve(extensionRoot, 'popup.css'), resolve(outputDir, 'popup.css'))

const zip = new JSZip()
for (const absolutePath of await collectFiles(outputDir)) {
  const archivePath = relative(outputDir, absolutePath).replaceAll('\\', '/')
  zip.file(archivePath, await readFile(absolutePath))
}
const zipBuffer = await zip.generateAsync({
  type: 'nodebuffer',
  compression: 'DEFLATE',
  compressionOptions: { level: 9 },
})
const checksum = createHash('sha256').update(zipBuffer).digest('hex')
const versionedDownloadFileName = `layout-capture-extension-${extensionVersion}.zip`
await mkdir(downloadDir, { recursive: true })
for (const fileName of await readdir(downloadDir)) {
  if (/^layout-capture-extension-[0-9]+(?:\.[0-9]+){0,3}\.zip(?:\.sha256)?$/.test(fileName)) {
    await rm(resolve(downloadDir, fileName), { force: true })
  }
}
await writeFile(resolve(downloadDir, downloadFileName), zipBuffer)
await writeFile(resolve(downloadDir, versionedDownloadFileName), zipBuffer)
await writeFile(
  resolve(downloadDir, `${downloadFileName}.sha256`),
  `${checksum}  ${downloadFileName}\n`,
  'ascii',
)
await writeFile(
  resolve(downloadDir, `${versionedDownloadFileName}.sha256`),
  `${checksum}  ${versionedDownloadFileName}\n`,
  'ascii',
)
await writeFile(
  resolve(downloadDir, downloadMetadataFileName),
  `${JSON.stringify({ file_name: versionedDownloadFileName, version: extensionVersion, sha256: checksum }, null, 2)}\n`,
  'utf8',
)

console.log(`Extension download: public/downloads/${versionedDownloadFileName}`)
console.log(`SHA256: ${checksum}`)
