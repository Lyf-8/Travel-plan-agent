// 行程相关 API 封装
import request from './request'

// 获取当前会话的最新行程
export function getCurrentItinerary(sessionId) {
  return request.get(`/itinerary/${sessionId}`)
}

// 获取行程版本列表
export function listVersions(sessionId) {
  return request.get(`/itinerary/${sessionId}/versions`)
}

// 获取指定版本的行程
export function getVersion(sessionId, version) {
  return request.get(`/itinerary/${sessionId}/versions/${version}`)
}

// 提交反馈（评分、评语、修改指令）
export function submitFeedback(sessionId, data) {
  return request.post(`/itinerary/${sessionId}/feedback`, data)
}

// 基于反馈或修改指令重新生成行程
export function regenerateItinerary(sessionId, data) {
  return request.post(`/itinerary/${sessionId}/regenerate`, data)
}

// 创建行程分享短链接
export function createShareLink(data) {
  return request.post('/share', data)
}

// 根据短码获取分享快照
export function getShareSnapshot(code) {
  return request.get(`/share/${code}`)
}
