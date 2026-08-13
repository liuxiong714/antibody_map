import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  optimizeDeps: {
    include: ['pdfjs-dist/build/pdf'],
  },
  build: {
    // 代码分割：将大体积第三方库拆分为独立 chunk，利用浏览器缓存
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom', 'dayjs', 'zustand', 'i18next', 'react-i18next'],
          antd: ['antd', '@ant-design/icons'],
          echarts: ['echarts', 'echarts-for-react'],
          pdf: ['pdfjs-dist'],
          markdown: ['react-markdown', 'remark-gfm', 'rehype-raw'],
        },
      },
    },
  },
})
