import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  return {
    plugins: [vue()],

    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },

    server: {
      host: '0.0.0.0',
      port: 5173,
      open: true,
      proxy: {
        '/api': {
          // 代理目标：始终指向后端服务实际地址，不要用相对路径
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
          ws: true,
          configure: (proxy) => {
            proxy.on('proxyRes', (proxyRes, req, res) => {
              try {
                const headers = proxyRes && proxyRes.headers ? proxyRes.headers : {}
                const ct = headers['content-type'] || ''
                if (typeof ct === 'string' && ct.includes('text/event-stream')) {
                  headers['cache-control'] = 'no-cache'
                  headers['x-accel-buffering'] = 'no'
                  headers['connection'] = 'keep-alive'
                  res.flushHeaders && res.flushHeaders()
                }
              } catch (_) {
                // ignore header modification errors to avoid breaking page
              }
            })
          },
        },
      },
    },

    build: {
      target: 'es2015',
      outDir: 'dist',
      assetsDir: 'assets',
      sourcemap: mode !== 'production',
      chunkSizeWarningLimit: 1500,
      rollupOptions: {
        output: {
          manualChunks: {
            'vue-vendor': ['vue', 'vue-router', 'pinia'],
            'element-plus': ['element-plus', '@element-plus/icons-vue'],
            'amap': ['@amap/amap-jsapi-loader'],
          },
        },
      },
    },
  }
})
