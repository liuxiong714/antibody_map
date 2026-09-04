import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      // 守护「自主业务逻辑」关键文件集（token 注入/解包、缓存层、核心工具、
      // 以及被复用的展示组件）。限定文件集后门槛才有实际约束力，
      // 避免被未测试的巨型页面组件整体拉低而失去意义。
      include: [
        'src/lib/apiCache.ts',
        'src/services/api.ts',
        'src/utils/constants.ts',
        'src/utils/format.ts',
        'src/components/EChart.tsx',
        'src/components/ConfidenceBadge.tsx',
        'src/components/QualityBadge.tsx',
        'src/components/StatusBadge.tsx',
        'src/components/DiseaseSelector.tsx',
      ],
      thresholds: {
        // 基于实测（statements 62.43 / functions 62.79 / branches 63.63）设定，
        // 保留余量避免 CI 抖动误报，同时能在覆盖率明显回退时拦截。
        statements: 55,
        functions: 55,
        branches: 50,
        lines: 50,
      },
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        proxyTimeout: 120000,
        timeout: 120000,
      },
    },
  },
  optimizeDeps: {
    include: ['pdfjs-dist'],
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
