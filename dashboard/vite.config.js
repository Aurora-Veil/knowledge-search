import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import devAuthMock from './mock/dev-auth.js'
import devHistoryMock from './mock/dev-history.js'
import devReportsMock from './mock/dev-reports.js'

const mockApi = process.env.MOCK_API !== '0' && process.env.MOCK_AUTH !== '0'

export default defineConfig({
  base: '/ui/',
  plugins: [
    react(),
    mockApi ? devAuthMock() : null,
    mockApi ? devReportsMock() : null,
    mockApi ? devHistoryMock() : null,
  ].filter(Boolean),
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
