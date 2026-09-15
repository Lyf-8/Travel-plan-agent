<script setup>
// 预算进度条：按类别展示预算占比与总额
import { computed } from 'vue'
import { formatNumber } from '../utils/format'

const props = defineProps({
  // 预算明细：{ transport, food, hotel, tickets, other, total }
  breakdown: {
    type: Object,
    default: () => ({}),
  },
  // 预算上限
  total: {
    type: Number,
    default: 0,
  },
})

// 各类别配置：label / color / 字段名
const categoryConfig = [
  { key: 'transport', label: '交通', color: '#409EFF', icon: 'Van' },
  { key: 'food', label: '餐饮', color: '#E6A23C', icon: 'Food' },
  { key: 'hotel', label: '住宿', color: '#67C23A', icon: 'House' },
  { key: 'tickets', label: '门票', color: '#F56C6C', icon: 'Tickets' },
  { key: 'other', label: '其他', color: '#909399', icon: 'More' },
]

// 有效类别列表（有数值才展示）
const categories = computed(() => {
  return categoryConfig
    .map((c) => {
      const value = Number(props.breakdown?.[c.key]) || 0
      const percent = props.total > 0 ? Math.min(100, Math.round((value / props.total) * 100)) : 0
      return { ...c, value, percent }
    })
    .filter((c) => c.value > 0)
})

// 实际总支出
const actualTotal = computed(() => {
  return categories.value.reduce((sum, c) => sum + c.value, 0)
})

// 是否超出预算
const isOverBudget = computed(() => props.total > 0 && actualTotal.value > props.total)

// 总占比
const totalPercent = computed(() => {
  if (props.total <= 0) return 0
  return Math.min(100, Math.round((actualTotal.value / props.total) * 100))
})

// 进度条颜色（超出预算变红）
const totalColor = computed(() => (isOverBudget.value ? '#F56C6C' : '#67C23A'))

// 总预算文案
const totalText = computed(() => {
  if (props.total > 0) {
    return `¥${formatNumber(actualTotal.value)} / ¥${formatNumber(props.total)}`
  }
  return `¥${formatNumber(actualTotal.value)}`
})
</script>

<template>
  <div class="budget-progress">
    <!-- 总览 -->
    <div class="budget-summary">
      <div class="summary-info">
        <span class="summary-label">预算总览</span>
        <span class="summary-value" :class="{ over: isOverBudget }">{{ totalText }}</span>
        <el-tag v-if="isOverBudget" type="danger" size="small" effect="dark">已超支</el-tag>
        <el-tag v-else-if="total > 0" type="success" size="small" effect="plain">预算内</el-tag>
      </div>
      <el-progress
        :percentage="totalPercent"
        :color="totalColor"
        :stroke-width="14"
        :show-text="false"
        class="total-progress"
      />
    </div>

    <!-- 分类明细 -->
    <div v-if="categories.length" class="category-list">
      <div v-for="cat in categories" :key="cat.key" class="category-item">
        <div class="category-head">
          <span class="category-label">
            <el-icon :style="{ color: cat.color }"><component :is="cat.icon" /></el-icon>
            {{ cat.label }}
          </span>
          <span class="category-value">¥{{ formatNumber(cat.value) }}</span>
        </div>
        <el-progress
          :percentage="cat.percent"
          :color="cat.color"
          :stroke-width="8"
          :show-text="false"
        />
        <span class="category-percent">{{ cat.percent }}%</span>
      </div>
    </div>
    <el-empty v-else description="暂无预算数据" :image-size="60" />
  </div>
</template>

<style scoped>
.budget-progress {
  padding: 4px;
}
.budget-summary {
  padding: 12px;
  background: linear-gradient(135deg, #f0f9ff 0%, #e8f4ff 100%);
  border-radius: 10px;
  margin-bottom: 12px;
}
.summary-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.summary-label {
  font-size: 13px;
  color: #909399;
}
.summary-value {
  font-size: 18px;
  font-weight: 700;
  color: #303133;
}
.summary-value.over {
  color: #f56c6c;
}
.total-progress {
  margin-top: 4px;
}
.category-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}
.category-item {
  padding: 10px;
  background: #fafafa;
  border-radius: 8px;
  position: relative;
}
.category-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.category-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: #606266;
}
.category-value {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.category-percent {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
  text-align: right;
}
</style>
