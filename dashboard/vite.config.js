import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import devAuthMock from './mock/dev-auth.js'
import devHistoryMock from './mock/dev-history.js'
import devReportsMock from './mock/dev-reports.js'

// 假后端总开关：默认开启。真后端起来后设 MOCK_API=0 再启动，请求就走下面的代理。
// 三个 mock 插件必须同时开或同时关，否则会出现“能登录但搜不了”的半吊子状态。
const mockApi = process.env.MOCK_API !== '0' && process.env.MOCK_AUTH !== '0'

// https://vite.dev/config/
export default defineConfig({
  // 生产环境页面挂在 FastAPI 的 /ui 下，dev 也用同样的路径，避免两套地址
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
      // 开发时把 /api 转给本地后端，前端代码里直接写 /api/v1/...
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
