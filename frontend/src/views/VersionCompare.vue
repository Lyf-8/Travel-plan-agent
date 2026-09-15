<script setup>
// 版本对比页：选择两个版本并排展示，高亮差异
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useItineraryStore } from '../stores/itinerary'
import { getVersion } from '../api/itinerary'
import { diffItems, diffSummary } from '../utils/diff'
import { formatBudget } from '../utils/format'
import ItineraryCard from '../components/ItineraryCard.vue'
import DiffHighlight from '../components/DiffHighlight.vue'

const route = useRoute()
const router = useRouter()
const itineraryStore = useItineraryStore()

const sessionId = computed(() => route.params.sessionId)

// 选中的两个版本号
const leftVersion = ref(null)
const rightVersion = ref(null)
// 两个版本的完整数据
const leftData = ref(null)
const rightData = ref(null)
// 加载状态
const loading = ref(false)

// 版本列表
const versions = computed(() => itineraryStore.versions)
// 版本号选项
const versionOptions = computed(() =>
  versions.value.map((v) => ({ label: `v${v.version}`, value: v.version }))
)

// 差异结果（左 → 右）
const diffResult = computed(() => {
  if (!leftData.value?.items || !rightData.value?.items) return null
  return diffItems(leftData.value.items, rightData.value.items)
})

// 差异摘要
const summary = computed(() => (diffResult.value ? diffSummary(diffResult.value) : null))

// 加载某个版本的完整数据
async function loadVersionData(version) {
  if (version == null) return null
  const res = await getVersion(sessionId.value, version)
  return res
}

// 切换版本时加载
watch(leftVersion, async (v) => {
  if (v == null) {
    leftData.value = null
    return
  }
  loading.value = true
  try {
    leftData.value = await loadVersionData(v)
  } catch (err) {
    leftData.value = null
  } finally {
    loading.value = false
  }
})

watch(rightVersion, async (v) => {
  if (v == null) {
    rightData.value = null
    return
  }
  loading.value = true
  try {
    rightData.value = await loadVersionData(v)
  } catch (err) {
    rightData.value = null
  } finally {
    loading.value = false
  }
})

// 按天分组
function groupByDay(items) {
  if (!Array.isArray(items)) return {}
  const groups = {}
  items.forEach((item) => {
    const day = item.day || 1
    if (!groups[day]) groups[day] = []
    groups[day].push(item)
  })
  Object.keys(groups).forEach((day) => {
    groups[day].sort((a, b) => (a.order_in_day || 0) - (b.order_in_day || 0))
  })
  return groups
}

// 跳回详情
function goDetail() {
  router.push(`/itinerary/${sessionId.value}`)
}

// 初始化：加载版本列表，默认选最后两个版本
onMounted(async () => {
  if (!sessionId.value) return
  try {
    await itineraryStore.loadVersions(sessionId.value)
    const list = versions.value
    if (list.length >= 2) {
      // 默认对比最早与最新
      leftVersion.value = list[0].version
      rightVersion.value = list[list.length - 1].version
    } else if (list.length === 1) {
      leftVersion.value = list[0].version
    }
  } catch (err) {
    // 错误已处理
  }
})
</script>

<template>
  <div class="compare-view">
    <!-- 顶栏 -->
    <header class="top-bar">
      <div class="bar-left">
        <el-button text @click="goDetail">
          <el-icon><ArrowLeft /></el-icon>返回详情
        </el-button>
        <span class="page-title">版本对比</span>
      </div>
      <div class="bar-right">
        <span class="version-picker">
          <span class="picker-label">左版本</span>
          <el-select v-model="leftVersion" size="small" placeholder="选择版本" style="width: 120px">
            <el-option
              v-for="opt in versionOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
              :disabled="opt.value === rightVersion"
            />
          </el-select>
        </span>
        <el-icon class="swap-icon"><Sort /></el-icon>
        <span class="version-picker">
          <span class="picker-label">右版本</span>
          <el-select v-model="rightVersion" size="small" placeholder="选择版本" style="width: 120px">
            <el-option
              v-for="opt in versionOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
              :disabled="opt.value === leftVersion"
            />
          </el-select>
        </span>
      </div>
    </header>

    <div class="compare-body" v-loading="loading">
      <!-- 未选择提示 -->
      <el-empty
        v-if="!leftVersion || !rightVersion"
        description="请选择两个版本进行对比"
        :image-size="120"
      />

      <template v-else>
        <!-- 差异概览 -->
        <section v-if="summary" class="diff-overview">
          <div class="overview-title">
            <el-icon><DataAnalysis /></el-icon>
            <span>差异概览（{{ leftVersion }} → {{ rightVersion }}）</span>
          </div>
          <div class="overview-stats">
            <div class="stat added">
              <div class="stat-num">{{ summary.added }}</div>
              <div class="stat-label">新增</div>
            </div>
            <div class="stat modified">
              <div class="stat-num">{{ summary.modified }}</div>
              <div class="stat-label">修改</div>
            </div>
            <div class="stat removed">
              <div class="stat-num">{{ summary.removed }}</div>
              <div class="stat-label">删除</div>
            </div>
            <div class="stat unchanged">
              <div class="stat-num">{{ summary.unchanged }}</div>
              <div class="stat-label">未变</div>
            </div>
          </div>
        </section>

        <!-- 差异明细 -->
        <section v-if="diffResult" class="diff-detail">
          <div class="section-title">
            <el-icon><Histogram /></el-icon>
            <span>差异明细</span>
          </div>
          <DiffHighlight :diff="diffResult" :show-unchanged="false" />
        </section>

        <!-- 并排对比 -->
        <section class="side-by-side">
          <div class="side-column left">
            <div class="column-head">
              <span class="head-version">v{{ leftVersion }}</span>
              <span v-if="leftData?.total_budget" class="head-budget">
                {{ formatBudget(0, leftData.total_budget) }}
              </span>
            </div>
            <div v-if="leftData" class="column-items">
              <template v-for="(items, day) in groupByDay(leftData.items)" :key="day">
                <div class="day-group">第 {{ day }} 天</div>
                <ItineraryCard v-for="item in items" :key="`${item.day}-${item.order_in_day}`" :item="item" />
              </template>
              <el-empty v-if="!leftData.items?.length" description="该版本无行程项" :image-size="60" />
            </div>
            <el-empty v-else description="加载中" :image-size="60" />
          </div>

          <div class="side-column right">
            <div class="column-head">
              <span class="head-version">v{{ rightVersion }}</span>
              <span v-if="rightData?.total_budget" class="head-budget">
                {{ formatBudget(0, rightData.total_budget) }}
              </span>
            </div>
            <div v-if="rightData" class="column-items">
              <template v-for="(items, day) in groupByDay(rightData.items)" :key="day">
                <div class="day-group">第 {{ day }} 天</div>
                <ItineraryCard v-for="item in items" :key="`${item.day}-${item.order_in_day}`" :item="item" />
              </template>
              <el-empty v-if="!rightData.items?.length" description="该版本无行程项" :image-size="60" />
            </div>
            <el-empty v-else description="加载中" :image-size="60" />
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.compare-view {
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
  align-items: center;
  gap: 10px;
}
.version-picker {
  display: flex;
  align-items: center;
  gap: 6px;
}
.picker-label {
  font-size: 13px;
  color: #909399;
}
.swap-icon {
  color: #c0c4cc;
}
.compare-body {
  flex: 1;
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
  padding: 20px;
}
.diff-overview {
  background: #fff;
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.overview-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}
.overview-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.stat {
  text-align: center;
  padding: 12px;
  border-radius: 8px;
}
.stat.added { background: #f0f9eb; }
.stat.modified { background: #fdf6ec; }
.stat.removed { background: #fef0f0; }
.stat.unchanged { background: #f4f4f5; }
.stat-num {
  font-size: 24px;
  font-weight: 700;
}
.stat.added .stat-num { color: #67c23a; }
.stat.modified .stat-num { color: #e6a23c; }
.stat.removed .stat-num { color: #f56c6c; }
.stat.unchanged .stat-num { color: #909399; }
.stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}
.diff-detail {
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
.side-by-side {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
.side-column {
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}
.column-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 10px;
  margin-bottom: 12px;
  border-bottom: 2px solid #409eff;
}
.head-version {
  font-size: 18px;
  font-weight: 700;
  color: #409eff;
}
.head-budget {
  font-size: 13px;
  color: #e6a23c;
}
.column-items {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.day-group {
  margin-top: 8px;
  padding: 6px 10px;
  background: #f5f7fa;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #606266;
}
@media (max-width: 900px) {
  .side-by-side { grid-template-columns: 1fr; }
  .overview-stats { grid-template-columns: repeat(2, 1fr); }
  .bar-right { flex-wrap: wrap; }
}
</style>
