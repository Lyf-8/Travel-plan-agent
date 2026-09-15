// 对话会话 Pinia store
import { defineStore } from 'pinia'
import {
  createSession as apiCreateSession,
  listSessions as apiListSessions,
  getSession as apiGetSession,
  sendMessage as apiSendMessage,
  getChatHistory as apiGetChatHistory,
  deleteSession as apiDeleteSession,
} from '../api/chat'

export const useChatStore = defineStore('chat', {
  // 状态
  state: () => ({
    // 所有会话列表
    sessions: [],
    // 当前选中的会话
    currentSession: null,
    // 当前会话的消息列表
    messages: [],
    // 列表/会话加载中
    loading: false,
    // 发送消息中
    sending: false,
  }),

  // 计算属性
  getters: {
    // 是否有当前会话
    hasCurrentSession: (state) => !!state.currentSession,
    // 当前会话 ID
    currentSessionId: (state) => state.currentSession?.session_id || null,
    // 消息数量
    messageCount: (state) => state.messages.length,
  },

  // 动作
  actions: {
    // 创建新会话
    async createSession(data) {
      this.loading = true
      try {
        const res = await apiCreateSession(data)
        if (res) {
          this.currentSession = res
          // 加入会话列表头部
          if (Array.isArray(this.sessions)) {
            this.sessions.unshift(res)
          }
          // 新会话默认清空消息
          this.messages = []
        }
        return res
      } finally {
        this.loading = false
      }
    },

    // 加载会话列表
    async loadSessions(userId) {
      this.loading = true
      try {
        const params = userId ? { user_id: userId } : {}
        const res = await apiListSessions(params)
        this.sessions = Array.isArray(res) ? res : res?.items || []
        return this.sessions
      } finally {
        this.loading = false
      }
    },

    // 选中某个会话并加载其详情与历史
    async selectSession(sessionId) {
      if (!sessionId) return
      this.loading = true
      try {
        const session = await apiGetSession(sessionId)
        this.currentSession = session
        // 选中会话后加载历史消息
        await this.loadHistory(sessionId)
        return session
      } finally {
        this.loading = false
      }
    },

    // 发送一条消息
    async sendMessage(sessionId, message) {
      if (!sessionId || !message) return null
      this.sending = true
      // 先把用户消息加入列表，提升响应感
      this.messages.push({ role: 'user', content: message, created_at: new Date().toISOString() })
      try {
        const res = await apiSendMessage(sessionId, message)
        // 后端返回 { reply, itinerary, version }
        if (res) {
          this.messages.push({
            role: 'assistant',
            content: res.reply || '',
            created_at: new Date().toISOString(),
            extra: { itinerary: res.itinerary, version: res.version },
          })
        }
        return res
      } catch (err) {
        // 发送失败时移除已乐观加入的用户消息
        this.messages.pop()
        throw err
      } finally {
        this.sending = false
      }
    },

    // 加载聊天历史
    async loadHistory(sessionId) {
      if (!sessionId) return
      try {
        const res = await apiGetChatHistory(sessionId)
        this.messages = Array.isArray(res) ? res : res?.items || []
        return this.messages
      } catch (err) {
        this.messages = []
        throw err
      }
    },

    // 删除会话
    async deleteSession(sessionId) {
      await apiDeleteSession(sessionId)
      // 从列表中移除
      const idx = this.sessions.findIndex((s) => s.session_id === sessionId)
      if (idx > -1) this.sessions.splice(idx, 1)
      // 若删除的是当前会话，清空当前
      if (this.currentSession?.session_id === sessionId) {
        this.currentSession = null
        this.messages = []
      }
    },

    // 重置 store
    reset() {
      this.sessions = []
      this.currentSession = null
      this.messages = []
      this.loading = false
      this.sending = false
    },
  },
})
