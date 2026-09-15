// 行程 Pinia store
import { defineStore } from 'pinia'
import {
  getCurrentItinerary as apiGetCurrentItinerary,
  listVersions as apiListVersions,
  getVersion as apiGetVersion,
  submitFeedback as apiSubmitFeedback,
  regenerateItinerary as apiRegenerateItinerary,
} from '../api/itinerary'

export const useItineraryStore = defineStore('itinerary', {
  // 状态
  state: () => ({
    // 当前行程版本
    currentItinerary: null,
    // 版本列表
    versions: [],
    // 加载中
    loading: false,
    // 重新生成中
    regenerating: false,
  }),

  // 计算属性
  getters: {
    // 当前版本号
    currentVersion: (state) => state.currentItinerary?.version || null,
    // 当前行程的明细项
    currentItems: (state) => state.currentItinerary?.items || [],
    // 地图数据
    mapData: (state) => state.currentItinerary?.map_data || null,
    // 总预算
    totalBudget: (state) => state.currentItinerary?.total_budget ?? null,
    // 预算明细
    budgetBreakdown: (state) => state.currentItinerary?.budget_breakdown || null,
    // 天气信息
    weatherInfo: (state) => state.currentItinerary?.weather_info || null,
    // 按天分组的明细项
    itemsByDay(state) {
      const groups = {}
      const items = state.currentItinerary?.items || []
      items.forEach((item) => {
        const day = item.day || 1
        if (!groups[day]) groups[day] = []
        groups[day].push(item)
      })
      // 每天内按 order_in_day 排序
      Object.keys(groups).forEach((day) => {
        groups[day].sort((a, b) => (a.order_in_day || 0) - (b.order_in_day || 0))
      })
      return groups
    },
    // 总天数
    dayCount(state) {
      const items = state.currentItinerary?.items || []
      if (!items.length) return 0
      return Math.max(...items.map((it) => it.day || 1))
    },
  },

  // 动作
  actions: {
    // 加载当前会话的最新行程
    async loadItinerary(sessionId) {
      if (!sessionId) return
      this.loading = true
      try {
        const res = await apiGetCurrentItinerary(sessionId)
        this.currentItinerary = res
        return res
      } finally {
        this.loading = false
      }
    },

    // 加载版本列表
    async loadVersions(sessionId) {
      if (!sessionId) return
      try {
        const res = await apiListVersions(sessionId)
        this.versions = Array.isArray(res) ? res : res?.items || []
        return this.versions
      } catch (err) {
        this.versions = []
        throw err
      }
    },

    // 切换到指定版本
    async switchVersion(sessionId, version) {
      if (!sessionId || version == null) return
      this.loading = true
      try {
        const res = await apiGetVersion(sessionId, version)
        this.currentItinerary = res
        return res
      } finally {
        this.loading = false
      }
    },

    // 提交反馈
    async submitFeedback(sessionId, data) {
      if (!sessionId) return
      const res = await apiSubmitFeedback(sessionId, data)
      return res
    },

    // 基于反馈或修改指令重新生成行程
    async regenerate(sessionId, data) {
      if (!sessionId) return
      this.regenerating = true
      try {
        const res = await apiRegenerateItinerary(sessionId, data)
        // 后端返回 { new_version, items }
        if (res) {
          // 更新当前行程
          this.currentItinerary = {
            ...(this.currentItinerary || {}),
            version: res.new_version ?? this.currentItinerary?.version,
            items: res.items || [],
          }
          // 刷新版本列表
          await this.loadVersions(sessionId)
        }
        return res
      } finally {
        this.regenerating = false
      }
    },

    // 重置 store
    reset() {
      this.currentItinerary = null
      this.versions = []
      this.loading = false
      this.regenerating = false
    },
  },
})
