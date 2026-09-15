<script setup>
// 行程详情全屏页：地图 + 天数明细 + 预算 + 反馈 + 版本历史
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useChatStore } from '../stores/chat'
import { useItineraryStore } from '../stores/itinerary'
import { createShareLink } from '../api/itinerary'
import AmapContainer from '../components/AmapContainer.vue'
import BudgetProgress from '../components/BudgetProgress.vue'
import FeedbackEditor from '../components/FeedbackEditor.vue'
import ItineraryCard from '../components/ItineraryCard.vue'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const itineraryStore = useItineraryStore()

const sessionId = computed(() => route.params.sessionId)

// 当前选中天数
const activeDay = ref('1')
// 反馈对话框
const feedbackVisible = ref(false)

// 当前会话
const session = computed(() => chatStore.currentSession)
// 当前行程
const itinerary = computed(() => itineraryStore.currentItinerary)
// 按天分组
const itemsByDay = computed(() => itineraryStore.itemsByDay)
// 版本列表
const versions = computed(() => itineraryStore.versions)
// 天数 tab 列表
const dayTabs = computed(() => {
  const days = Object.keys(itemsByDay.value).map(Number).sort((a, b) => a - b)
  return days.length ? days : [1]
})

// 地图 POI 数据：直接使用后端 map_data.markers
const mapPois = computed(() => {
  const md = itineraryStore.mapData
  if (md?.markers?.length) return md.markers
  // 退化：从 items 尝试取经纬度
  const items = itineraryStore.currentItems
  return items
    .filter((it) => it.longitude != null && it.latitude != null)
    .map((it) => ({ lng: it.longitude, lat: it.latitude, name: it.location_name || it.title }))
})

// 地图路线：转换后端 map_data.polylines 为 AmapContainer 格式
const mapRoutes = computed(() => {
  const md = itineraryStore.mapData
  if (md?.polylines?.length) {
    // 后端格式: [{day, points: [[lng, lat], ...]}, ...]
    // AmapContainer 格式: [[{lng, lat}, ...], ...]
    return md.polylines
      .map((pl) => {
        const pts = pl.points || pl
        if (!Array.isArray(pts)) return null
        if (pts.length > 0 && Array.isArray(pts[0])) {
          // [[lng, lat], ...] → [{lng, lat}, ...]
          return pts.map((p) => ({ lng: p[0], lat: p[1] }))
        }
        return pts.filter((p) => p.lng != null && p.lat != null)
      })
      .filter((r) => r && r.length >= 2)
  }
  // 退化：从 items 按天连接
  const days = Object.keys(itemsByDay.value).map(Number).sort((a, b) => a - b)
  return days
    .map((day) => {
      return (itemsByDay.value[day] || [])
        .filter((it) => it.longitude != null && it.latitude != null)
        .map((it) => ({ lng: it.longitude, lat: it.latitude }))
    })
    .filter((r) => r.length >= 2)
})

// 预算明细：优先使用后端 budget_breakdown
const budgetBreakdown = computed(() => {
  const bb = itineraryStore.budgetBreakdown
  if (bb && Object.values(bb).some((v) => Number(v) > 0)) return bb
  // 退化：从 items 聚合
  const items = itineraryStore.currentItems
  const breakdown = { transport: 0, food: 0, hotel: 0, tickets: 0, other: 0 }
  items.forEach((it) => {
    breakdown.tickets += Number(it.cost_ticket) || 0
    breakdown.food += Number(it.cost_food) || 0
    breakdown.hotel += Number(it.cost_hotel) || 0
    breakdown.transport += Number(it.cost_transport) || 0
    breakdown.other += Number(it.cost_other) || 0
  })
  breakdown.total =
    breakdown.tickets + breakdown.food + breakdown.hotel + breakdown.transport + breakdown.other
  return breakdown
})

// 预算上限
const budgetLimit = computed(() => {
  const sessionBudget = session.value?.budget_max
  const totalBudget = itinerary.value?.total_budget
  return sessionBudget || totalBudget || budgetBreakdown.value?.total || 0
})

// 当前版本 ID（用于反馈）
const currentVersionId = computed(() => itinerary.value?.id)

// 切换版本
async function handleSwitchVersion(version) {
  try {
    await itineraryStore.switchVersion(sessionId.value, version)
    ElMessage.success(`已切换到 v${version}`)
  } catch (err) {
    // 错误已处理
  }
}

// 打开反馈
function openFeedback() {
  feedbackVisible.value = true
}

// 反馈提交后
async function handleFeedbackSubmit(res) {
  // 如果返回了 feedback_id 且带修改指令，可直接触发重生成
  if (res?.feedback_id) {
    ElMessage.success('可点击"重新生成"基于反馈生成新版本')
  }
}

// 重新生成
async function handleRegenerate() {
  try {
    await itineraryStore.regenerate(sessionId.value, {})
    ElMessage.success('已生成新版本')
  } catch (err) {
    // 错误已处理
  }
}

// 跳转对比
function goCompare() {
  router.push(`/compare/${sessionId.value}`)
}

// 跳回对话
function goChat() {
  router.push(`/chat/${sessionId.value}`)
}

// 生成分享链接
const shareLoading = ref(false)
async function handleCreateShare() {
  if (!sessionId.value) {
    ElMessage.warning('暂无会话信息')
    return
  }
  if (!itinerary.value) {
    ElMessage.warning('暂无行程可分享')
    return
  }
  shareLoading.value = true
  try {
    const res = await createShareLink({
      session_id: sessionId.value,
      version_id: itinerary.value?.id,
      expire_days: 30,
    })
    const data = res?.data
    if (!data) throw new Error('生成失败')
    // 构造完整链接（去掉 hash 路由的 #/，拼接当前 origin）
    const sharePath = data.share_url || `/#/share/${data.short_code}`
    const fullUrl = window.location.origin + sharePath
    // 复制到剪贴板
    try {
      await navigator.clipboard.writeText(fullUrl)
      ElMessage.success(`分享链接已复制：${fullUrl}`)
    } catch (_e) {
      // 兼容老浏览器
      const textarea = document.createElement('textarea')
      textarea.value = fullUrl
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      try {
        document.execCommand('copy')
        ElMessage.success(`分享链接已复制：${fullUrl}`)
      } catch (_e2) {
        ElMessage({
          type: 'success',
          message: `分享链接：${fullUrl}`,
          duration: 5000,
          showClose: true,
        })
      } finally {
        document.body.removeChild(textarea)
      }
    }
  } catch (err) {
    const msg = err?.response?.data?.detail || err?.message || '生成分享链接失败'
    ElMessage.error(msg)
  } finally {
    shareLoading.value = false
  }
}

// 加载数据
onMounted(async () => {
  if (!sessionId.value) return
  try {
    await Promise.all([
      chatStore.selectSession(sessionId.value),
      itineraryStore.loadItinerary(sessionId.value),
      itineraryStore.loadVersions(sessionId.value),
    ])
  } catch (err) {
    // 错误已处理
  }
})
</script>

<template>
  <div class="detail-view">
    <!-- 顶栏 -->
    <header class="top-bar">
      <div class="bar-left">
        <el-button text @click="goChat">
          <el-icon><ArrowLeft /></el-icon>返回对话
        </el-button>
        <span class="page-title">{{ session?.title || '行程详情' }}</span>
        <el-tag v-if="itinerary" type="primary" size="small">v{{ itinerary.version }}</el-tag>
      </div>
      <div class="bar-right">
        <el-button size="small" type="primary" plain :loading="shareLoading" @click="handleCreateShare">
          <el-icon><Share /></el-icon>生成分享链接
        </el-button>
        <el-button size="small" @click="goCompare">
          <el-icon><CopyDocument /></el-icon>版本对比
        </el-button>
        <el-button size="small" type="warning" plain @click="openFeedback">
          <el-icon><EditPen /></el-icon>反馈
        </el-button>
        <el-button size="small" type="success" :loading="itineraryStore.regenerating" @click="handleRegenerate">
          <el-icon><RefreshRight /></el-icon>重新生成
        </el-button>
      </div>
    </header>

    <div class="detail-body" v-loading="itineraryStore.loading">
      <!-- 地图区域 -->
      <section class="map-section">
        <AmapContainer :pois="mapPois" :route-data="mapRoutes" :zoom="12" class="map-box" />
      </section>

      <!-- 预算区域 -->
      <section class="budget-section">
        <div class="section-title">
          <el-icon><Wallet /></el-icon>
          <span>预算分布</span>
        </div>
        <BudgetProgress :breakdown="budgetBreakdown" :total="budgetLimit" />
      </section>

      <!-- 主体：左侧行程明细 + 右侧版本历史 -->
      <div class="content-layout">
        <!-- 行程明细 -->
        <section class="items-section">
          <div class="section-title">
            <el-icon><Calendar /></el-icon>
            <span>行程安排</span>
          </div>
          <el-tabs v-model="activeDay" class="day-tabs">
            <el-tab-pane
              v-for="day in dayTabs"
              :key="day"
              :label="`第 ${day} 天`"
              :name="String(day)"
            >
              <div class="day-items">
                <ItineraryCard
                  v-for="item in (itemsByDay[day] || [])"
                  :key="`${item.day}-${item.order_in_day}`"
                  :item="item"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
        </section>

        <!-- 版本历史侧边栏 -->
        <aside class="version-sidebar">
          <div class="section-title">
            <el-icon><Clock /></el-icon>
            <span>版本历史</span>
          </div>
          <el-timeline v-if="versions.length">
            <el-timeline-item
              v-for="ver in versions"
              :key="ver.version"
              :timestamp="ver.created_at || ''"
              :type="ver.version === itinerary?.version ? 'primary' : 'info'"
              :hollow="ver.version !== itinerary?.version"
            >
              <div class="version-card" :class="{ active: ver.version === itinerary?.version }">
                <div class="version-head">
                  <span class="version-num">v{{ ver.version }}</span>
                  <el-tag v-if="ver.is_current" type="success" size="small">当前</el-tag>
                </div>
                <div class="version-meta">
                  <span v-if="ver.trigger">{{ ver.trigger === 'initial' ? '初始生成' : ver.trigger === 'feedback' ? '反馈重生成' : '手动' }}</span>
                  <span v-if="ver.total_budget"> · ¥{{ ver.total_budget }}</span>
                </div>
                <el-button
                  v-if="ver.version !== itinerary?.version"
                  size="small"
                  text
                  type="primary"
                  @click="handleSwitchVersion(ver.version)"
                >
                  切换到此版本
                </el-button>
              </div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无版本记录" :image-size="60" />
        </aside>
      </div>
    </div>

    <!-- 反馈编辑器 -->
    <FeedbackEditor
      :session-id="sessionId"
      :version-id="currentVersionId"
      v-model:visible="feedbackVisible"
      @submit="handleFeedbackSubmit"
    />
  </div>
</template>

<style scoped>
.detail-view {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: #f0f2f5;
}
.top-bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}
.bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.page-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.bar-right {
  display: flex;
  gap: 8px;
}
.detail-body {
  flex: 1;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  padding: 20px;
}
.map-section {
  margin-bottom: 20px;
}
.map-box {
  height: 360px;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}
.budget-section {
  background: #fff;
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}
.content-layout {
  display: flex;
  gap: 20px;
}
.items-section {
  flex: 1;
  background: #fff;
  border-radius: 12px;
  padding: 16px 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.version-sidebar {
  width: 280px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  max-height: 600px;
  overflow-y: auto;
}
.day-items {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.version-card {
  padding: 8px 10px;
  border-radius: 8px;
  background: #f5f7fa;
}
.version-card.active {
  background: #ecf5ff;
  border: 1px solid #409eff;
}
.version-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.version-num {
  font-weight: 700;
  color: #409eff;
}
.version-meta {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
@media (max-width: 768px) {
  .content-layout { flex-direction: column; }
  .version-sidebar { width: 100%; max-height: none; }
  .map-box { height: 240px; }
}
</style>
