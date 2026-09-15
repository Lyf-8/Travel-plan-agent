<script setup>
// 行程分享落地页：只读展示行程快照
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getShareSnapshot } from '../api/itinerary'
import BudgetProgress from '../components/BudgetProgress.vue'
import ItineraryCard from '../components/ItineraryCard.vue'
import { formatNumber } from '../utils/format'

const route = useRoute()
const router = useRouter()

const code = computed(() => route.params.code)
const loading = ref(false)
const snapshot = ref(null)
const viewCount = ref(0)
const expireAt = ref(null)

// 当前选中天数
const activeDay = ref('1')

// 快照数据计算属性
const destination = computed(() => snapshot.value?.destination || '未知目的地')
const travelDays = computed(() => snapshot.value?.travel_days || 0)
const sessionTitle = computed(() => snapshot.value?.session_title || '行程分享')
const totalDistance = computed(() => snapshot.value?.total_distance_km || 0)

// 按天分组
const itemsByDay = computed(() => {
  const items = snapshot.value?.items || []
  const map = {}
  items.forEach((it) => {
    const d = String(it.day || 1)
    if (!map[d]) map[d] = []
    map[d].push(it)
  })
  return map
})

// 天数 tab 列表
const dayTabs = computed(() => {
  const days = Object.keys(itemsByDay.value).map(Number).sort((a, b) => a - b)
  return days.length ? days : [1]
})

// 预算明细（兼容后端返回的 budget_breakdown 结构）
const budgetBreakdown = computed(() => {
  const snap = snapshot.value
  if (!snap?.budget_breakdown) return { transport: 0, food: 0, hotel: 0, tickets: 0, other: 0, total: 0 }
  const raw = snap.budget_breakdown
  const cats = raw.categories || {}
  const total = (raw.total != null) ? raw.total : (cats.transport + cats.food + cats.hotel + cats.tickets + cats.other || 0)
  return {
    transport: Number(cats.transport) || 0,
    food: Number(cats.food) || 0,
    hotel: Number(cats.hotel) || 0,
    tickets: Number(cats.tickets) || 0,
    other: Number(cats.other) || 0,
    total: Number(total) || 0,
  }
})

// 返回首页
function goHome() {
  router.push('/')
}

// 加载快照
async function loadSnapshot() {
  if (!code.value) {
    ElMessage.error('分享链接无效')
    return
  }
  loading.value = true
  try {
    const res = await getShareSnapshot(code.value)
    const data = res?.data
    if (!data) throw new Error('无数据')
    snapshot.value = data.share_snapshot
    viewCount.value = data.view_count || 0
    expireAt.value = data.expire_at
  } catch (err) {
    const msg = err?.response?.data?.detail || err?.message || '分享链接不存在或已过期'
    ElMessage.error(msg)
    snapshot.value = null
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadSnapshot()
})
</script>

<template>
  <div class="share-view">
    <!-- 顶栏 -->
    <header class="top-bar">
      <div class="bar-left">
        <el-button text @click="goHome">
          <el-icon><House /></el-icon>返回首页
        </el-button>
        <span class="page-title">
          <el-icon><Share /></el-icon>
          {{ sessionTitle }}
        </span>
      </div>
      <div class="bar-right">
        <el-tag type="info" size="small" v-if="destination">
          <el-icon><LocationInformation /></el-icon>{{ destination }}
        </el-tag>
        <el-tag type="success" size="small" v-if="travelDays">
          <el-icon><Calendar /></el-icon>{{ travelDays }} 天
        </el-tag>
        <el-tag type="warning" size="small" v-if="totalDistance">
          <el-icon><Van /></el-icon>约 {{ formatNumber(totalDistance) }} km
        </el-tag>
      </div>
    </header>

    <div class="share-body" v-loading="loading">
      <!-- 分享失效占位 -->
      <div v-if="!snapshot && !loading" class="expired-box">
        <el-result icon="warning" title="分享链接已失效" sub-title="该行程分享链接不存在或已过期，请重新生成分享链接。">
          <template #extra>
            <el-button type="primary" @click="goHome">返回首页</el-button>
          </template>
        </el-result>
      </div>

      <template v-else-if="snapshot">
        <!-- 预算区域 -->
        <section class="budget-section">
          <div class="section-title">
            <el-icon><Wallet /></el-icon>
            <span>预算分布</span>
            <el-tag v-if="budgetBreakdown.total" type="primary" effect="plain" size="small">
              总预算 ¥{{ formatNumber(budgetBreakdown.total) }}
            </el-tag>
          </div>
          <BudgetProgress :breakdown="budgetBreakdown" :total="budgetBreakdown.total" />
        </section>

        <!-- 逐日行程 -->
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
                  v-for="(item, idx) in (itemsByDay[day] || [])"
                  :key="`${day}-${idx}-${item.title}`"
                  :item="item"
                />
                <el-empty v-if="!(itemsByDay[day] || []).length" description="当天暂无活动安排" :image-size="60" />
              </div>
            </el-tab-pane>
          </el-tabs>
        </section>

        <!-- 天气摘要（如有） -->
        <section v-if="snapshot.weather_summary && Object.keys(snapshot.weather_summary).length" class="weather-section">
          <div class="section-title">
            <el-icon><Sunny /></el-icon>
            <span>天气摘要</span>
          </div>
          <div class="weather-content">
            <template v-if="Array.isArray(snapshot.weather_summary)">
              <div v-for="(w, i) in snapshot.weather_summary" :key="i" class="weather-item">
                <el-tag type="info" effect="plain" size="small">{{ w.day || w.date || `第${i + 1}天` }}</el-tag>
                <span>{{ w.weather || w.text || w.desc || '' }}</span>
                <span class="temp" v-if="w.temp || w.temperature">{{ w.temp || w.temperature }}</span>
              </div>
            </template>
            <template v-else-if="typeof snapshot.weather_summary === 'object'">
              <div v-for="(val, key) in snapshot.weather_summary" :key="key" class="weather-item">
                <el-tag type="info" effect="plain" size="small">{{ key }}</el-tag>
                <span>{{ typeof val === 'object' ? JSON.stringify(val) : val }}</span>
              </div>
            </template>
          </div>
        </section>
      </template>
    </div>

    <!-- 右下角浏览次数 -->
    <div v-if="snapshot" class="view-count-badge">
      <el-icon><View /></el-icon>
      已被浏览 <b>{{ viewCount }}</b> 次
    </div>
  </div>
</template>

<style scoped>
.share-view {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: linear-gradient(135deg, #f5f7fa 0%, #e8f4ff 100%);
  position: relative;
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
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  border-bottom: 1px solid #ebeef5;
}
.bar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.page-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.bar-right {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.share-body {
  flex: 1;
  max-width: 960px;
  width: 100%;
  margin: 0 auto;
  padding: 24px 20px 80px;
}
.expired-box {
  margin-top: 60px;
  background: #fff;
  border-radius: 12px;
  padding: 40px 20px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}
.budget-section,
.items-section,
.weather-section {
  background: #fff;
  border-radius: 12px;
  padding: 18px 22px;
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
  margin-bottom: 14px;
}
.day-items {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 8px;
}
.weather-content {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
}
.weather-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: #f0f9ff;
  border-radius: 10px;
  font-size: 14px;
  color: #606266;
}
.weather-item .temp {
  color: #e6a23c;
  font-weight: 600;
}
.view-count-badge {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 20;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  background: rgba(64, 158, 255, 0.9);
  color: #fff;
  border-radius: 999px;
  font-size: 13px;
  box-shadow: 0 4px 16px rgba(64, 158, 255, 0.35);
  backdrop-filter: blur(4px);
}
.view-count-badge b {
  font-size: 15px;
  margin: 0 2px;
}
@media (max-width: 768px) {
  .share-body { padding: 16px 12px 80px; }
  .budget-section, .items-section, .weather-section { padding: 14px 14px; }
  .bar-right { display: none; }
}
</style>
