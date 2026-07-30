import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 开发环境下把 /api 请求转发给本机 FastAPI 后端，避免手动配置 CORS 域名。
      '/api': {
        // 默认指向本项目启动的 MySQL 后端；需要覆盖时设置 VITE_API_PROXY_TARGET。
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8002',
        changeOrigin: true,
      },
    },
  },
  build: {
    // 生产构建输出到 frontend/dist，由后端 FastAPI 的 StaticFiles 挂载托管，实现单体部署。
    outDir: 'dist',
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined

          if (id.includes('/react/') || id.includes('/react-dom/') || id.includes('/scheduler/')) {
            return 'react-vendor'
          }
          if (
            id.includes('/antd/')
            || id.includes('/@ant-design/')
            || id.includes('/@rc-component/')
            || id.includes('/rc-')
          ) {
            return 'antd-vendor'
          }
          if (
            id.includes('/@uiw/')
            || id.includes('/@codemirror/')
            || id.includes('/@lezer/')
            || id.includes('/codemirror/')
          ) {
            return 'codemirror-vendor'
          }
          if (
            id.includes('/react-syntax-highlighter/')
            || id.includes('/refractor/')
            || id.includes('/prismjs/')
          ) {
            return 'syntax-highlighter-vendor'
          }
          if (
            id.includes('/react-markdown/')
            || id.includes('/remark-')
            || id.includes('/rehype-')
            || id.includes('/unified/')
            || id.includes('/micromark')
            || id.includes('/mdast-')
            || id.includes('/hast-')
            || id.includes('/vfile')
          ) {
            return 'markdown-vendor'
          }
          if (id.includes('/katex/')) return 'katex-vendor'

          return 'vendor'
        },
      },
    },
  },
})
