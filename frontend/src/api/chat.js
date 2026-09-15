// 对话会话相关 API 封装
import request from './request'

// 创建对话会话
export function createSession(data) {
  return request.post('/chat/sessions', data)
}

// 获取会话列表（支持 user_id 查询参数）
export function listSessions(params) {
  return request.get('/chat/sessions', { params })
}

// 获取会话详情
export function getSession(sessionId) {
  return request.get(`/chat/sessions/${sessionId}`)
}

// 发送一条用户消息，返回 AI 回复与行程
export function sendMessage(sessionId, message) {
  return request.post(`/chat/sessions/${sessionId}/messages`, { message })
}

// 获取会话的聊天历史
export function getChatHistory(sessionId) {
  return request.get(`/chat/sessions/${sessionId}/messages`)
}

// 删除会话
export function deleteSession(sessionId) {
  return request.delete(`/chat/sessions/${sessionId}`)
}

// SSE 流式发送消息（原生 fetch + ReadableStream 解析，不引入额外依赖）
// callbacks: { onOpen, onNodeStart, onNodeProgress, onClarification, onDone, onError }
export async function sendMessageStream(sessionId, message, callbacks = {}) {
  const {
    onOpen,
    onNodeStart,
    onNodeProgress,
    onClarification,
    onDone,
    onError,
  } = callbacks

  const baseURL = import.meta.env.VITE_API_BASE_URL || '/api'
  const url = `${baseURL}/chat/sessions/${sessionId}/messages/stream`

  let response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        'Accept': 'text/event-stream',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ message }),
    })
  } catch (err) {
    onError && onError(err)
    throw err
  }

  if (!response.ok) {
    let errMsg = `请求失败 (${response.status})`
    try {
      const text = await response.text()
      if (text) {
        try {
          const json = JSON.parse(text)
          errMsg = json.message || json.detail || errMsg
        } catch (_) {
          errMsg = text.slice(0, 200) || errMsg
        }
      }
    } catch (_) {}
    const err = new Error(errMsg)
    onError && onError(err)
    throw err
  }

  onOpen && onOpen(response)

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  // SSE 跨 chunk 残留缓冲区：网络分片可能把一个事件切开，必须缓存到下一轮拼接
  let buffer = ''
  let doneResult = null

  function parseAndDispatchEvent(rawEvent) {
    if (!rawEvent || !rawEvent.trim()) return
    const lines = rawEvent.split('\n')
    let eventName = 'message'
    let dataStr = ''
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed) continue
      if (trimmed.startsWith('event:')) {
        eventName = trimmed.slice(6).trim() || eventName
      } else if (trimmed.startsWith('data:')) {
        dataStr += trimmed.slice(5).trim()
      }
    }
    let data = null
    if (dataStr) {
      try {
        data = JSON.parse(dataStr)
      } catch (_) {
        data = dataStr
      }
    }
    switch (eventName) {
      case 'node_start':
        onNodeStart && onNodeStart(data)
        break
      case 'node_progress':
        onNodeProgress && onNodeProgress(data)
        break
      case 'clarification':
        onClarification && onClarification(data)
        break
      case 'done':
        doneResult = data
        onDone && onDone(data)
        break
      case 'error':
        {
          const err = new Error(data?.message || '流式错误')
          onError && onError(err)
          throw err
        }
      default:
        break
    }
  }

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // 仅消费缓冲区中已完整（以 \n\n 结尾）的事件，残片留到下一轮
      let sepIndex
      while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
        const rawEvent = buffer.slice(0, sepIndex)
        buffer = buffer.slice(sepIndex + 2)
        parseAndDispatchEvent(rawEvent)
      }
    }
    // 流结束后处理缓冲区最后的残留事件
    if (buffer.trim()) {
      parseAndDispatchEvent(buffer)
    }
  } catch (err) {
    if (!doneResult) {
      onError && onError(err)
      throw err
    }
  } finally {
    try { reader.releaseLock() } catch (_) {}
  }

  return doneResult
}
