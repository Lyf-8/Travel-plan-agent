<script setup>
// 行程明细项卡片：展示单个活动/景点/餐饮等信息
import { computed } from 'vue'
import {
  getItemTypeIcon,
  getItemTypeLabel,
  getItemTypeColor,
  formatTimeRange,
  formatDuration,
  formatDistance,
  getTransportLabel,
  getItemCost,
  getItemCostBreakdown,
} from '../utils/format'

const props = defineProps({
  // 行程项对象
  item: {
    type: Object,
    required: true,
  },
})

// 类型主题色
const typeColor = computed(() => getItemTypeColor(props.item.item_type))
// 图标名称
const iconName = computed(() => getItemTypeIcon(props.item.item_type))
// 类型中文标签
const typeLabel = computed(() => getItemTypeLabel(props.item.item_type))
// 时间区间
const timeRange = computed(() => formatTimeRange(props.item.start_time, props.item.end_time))
// 建议时长
const durationText = computed(() => formatDuration(props.item.duration_min))
// 从上一项到本项的交通信息
const transportText = computed(() => {
  const t = props.item.transport_from_prev
  if (!t) return ''
  const parts = [getTransportLabel(t)]
  if (props.item.travel_distance_m) parts.push(formatDistance(props.item.travel_distance_m))
  if (props.item.travel_time_min) parts.push(`约 ${formatDuration(props.item.travel_time_min)}`)
  return parts.join(' · ')
})
// 费用明细
const costBreakdown = computed(() => getItemCostBreakdown(props.item))
// 总费用
const totalCost = computed(() => getItemCost(props.item))
// 标签列表
const tags = computed(() => props.item.tags || [])
</script>

<template>
  <el-card class="itinerary-card" :style="{ '--type-color': typeColor }" shadow="hover">
    <!-- 左侧色条 + 图标 -->
    <div class="card-header">
      <div class="type-badge" :style="{ backgroundColor: typeColor }">
        <el-icon :size="20"><component :is="iconName" /></el-icon>
      </div>
      <div class="header-info">
        <div class="title-row">
          <span class="item-title">{{ item.title }}</span>
          <el-tag size="small" :style="{ backgroundColor: typeColor, color: '#fff', border: 'none' }">
            {{ typeLabel }}
          </el-tag>
        </div>
        <div class="meta-row">
          <span v-if="timeRange" class="meta-item">
            <el-icon><Clock /></el-icon>{{ timeRange }}
          </span>
          <span v-if="durationText" class="meta-item">
            <el-icon><Timer /></el-icon>{{ durationText }}
          </span>
          <span v-if="item.location_name" class="meta-item">
            <el-icon><LocationInformation /></el-icon>{{ item.location_name }}
          </span>
        </div>
      </div>
    </div>

    <!-- 交通衔接信息 -->
    <div v-if="transportText" class="transport-bar">
      <el-icon><Position /></el-icon>
      <span>{{ transportText }}</span>
    </div>

    <!-- 描述 -->
    <p v-if="item.description" class="description">{{ item.description }}</p>

    <!-- 地址 -->
    <div v-if="item.location_address" class="address">
      <el-icon><MapLocation /></el-icon>
      <span>{{ item.location_address }}</span>
    </div>

    <!-- 标签 -->
    <div v-if="tags.length" class="tags">
      <el-tag v-for="tag in tags" :key="tag" type="info" size="small" effect="plain" round>
        {{ tag }}
      </el-tag>
    </div>

    <!-- 费用明细 -->
    <div v-if="costBreakdown.length" class="cost-section">
      <div class="cost-title">
        <el-icon><Wallet /></el-icon>
        <span>费用明细</span>
        <span class="cost-total">合计 ¥{{ totalCost }}</span>
      </div>
      <div class="cost-list">
        <el-tag
          v-for="c in costBreakdown"
          :key="c.label"
          type="warning"
          size="small"
          effect="plain"
        >
          {{ c.label }} ¥{{ c.value }}
        </el-tag>
      </div>
    </div>
  </el-card>
</template>

<style scoped>
.itinerary-card {
  border-left: 4px solid var(--type-color, #409eff);
  border-radius: 12px;
  transition: transform 0.2s, box-shadow 0.2s;
}
.itinerary-card:hover {
  transform: translateY(-2px);
}
.card-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.type-badge {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
.header-info {
  flex: 1;
  min-width: 0;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.item-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.meta-row {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  color: #909399;
  font-size: 13px;
}
.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.transport-bar {
  margin-top: 10px;
  padding: 6px 10px;
  background: #f4f4f5;
  border-radius: 8px;
  color: #909399;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.description {
  margin-top: 10px;
  color: #606266;
  font-size: 14px;
  line-height: 1.6;
}
.address {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
  color: #909399;
  font-size: 13px;
}
.tags {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.cost-section {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #ebeef5;
}
.cost-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #606266;
  font-weight: 600;
}
.cost-total {
  margin-left: auto;
  color: #e6a23c;
  font-weight: 700;
}
.cost-list {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
