// Axios 请求实例封装
// 统一处理 baseURL、拦截器、loading 与错误提示
import axios from 'axios'
import { ElMessage, ElLoading } from 'element-plus'

// 创建 axios 实例，baseURL 优先取环境变量，默认走 /api 代理
const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 全局 loading 计数器，支持并发请求叠加
let loadingCount = 0
let loadingInstance = null

// 开启 loading
function startLoading() {
  if (loadingCount === 0) {
    loadingInstance = ElLoading.service({
      lock: true,
      text: '加载中...',
      background: 'rgba(255, 255, 255, 0.6)',
    })
  }
  loadingCount++
}

// 关闭 loading
function endLoading() {
  if (loadingCount > 0) {
    loadingCount--
  }
  if (loadingCount === 0 && loadingInstance) {
    loadingInstance.close()
    loadingInstance = null
  }
}

// 请求拦截器：附加 loading
request.interceptors.request.use(
  (config) => {
    // GET 请求默认展示 loading（可通过 config.silent = true 关闭）
    if (config.silent !== true) {
      startLoading()
    }
    return config
  },
  (error) => {
    endLoading()
    return Promise.reject(error)
  }
)

// 响应拦截器：统一解包 { code, message, data } 结构
request.interceptors.response.use(
  (response) => {
    endLoading()
    const res = response.data
    // 非标准结构（如直接返回文件流）直接放行
    if (res === null || res === undefined || typeof res !== 'object' || res.code === undefined) {
      return res
    }
    // code === 0 表示成功，解包返回 data
    if (res.code === 0) {
      return res.data
    }
    // 业务错误：弹出提示并拒绝
    ElMessage.error(res.message || '请求失败')
    return Promise.reject(new Error(res.message || '请求失败'))
  },
  (error) => {
    endLoading()
    const { response, message } = error
    // 网络错误（无响应）
    if (!response) {
      ElMessage.error(message || '网络异常，请检查网络连接')
      return Promise.reject(error)
    }
    // 根据状态码给出友好提示
    const status = response.status
    let tip = '请求失败'
    switch (status) {
      case 400:
        tip = '请求参数有误'
        break
      case 401:
        tip = '未授权，请重新登录'
        break
      case 403:
        tip = '拒绝访问'
        break
      case 404:
        tip = '请求的资源不存在'
        break
      case 500:
        tip = '服务器内部错误'
        break
      case 502:
        tip = '网关错误'
        break
      case 503:
        tip = '服务暂不可用'
        break
      case 504:
        tip = '网关超时'
        break
      default:
        tip = `请求出错 (${status})`
    }
    // 优先使用后端返回的 message
    const serverMsg = response.data?.message
    ElMessage.error(serverMsg || tip)
    return Promise.reject(error)
  }
)

export default request
