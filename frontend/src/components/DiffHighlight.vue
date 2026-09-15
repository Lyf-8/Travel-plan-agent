<script setup>
// 差异高亮展示：按颜色区分新增/删除/修改/未变项
import { computed } from 'vue'
import {
  getItemTypeIcon,
  getItemTypeLabel,
  getItemTypeColor,
  formatTimeRange,
} from '../utils/format'

const props = defineProps({
  // 差异数据：{ added, removed, modified, unchanged }
  diff: {
    type: Object,
    default: () => ({ added: [], removed: [], modified: [], unchanged: [] }),
  },
  // 是否显示未变项
  showUnchanged: {
    type: Boolean,
    default: false,
  },
})

// 统计摘要
const summary = computed(() => ({
  added: props.diff?.added?.length || 0,
  removed: props.diff?.removed?.length || 0,
  modified: props.diff?.modified?.length || 0,
  unchanged: props.diff?.unchanged?.length || 0,
}))

// 是否有差异
const hasDiff = computed(
  () => summary.value.added || summary.value.removed || summary.value.modified
)

// 各分组配置：标题 / 颜色 / 图标
const groups = computed(() => [
  { key: 'added', label: '新增', color: '#67C23A', icon: 'CirclePlus', items: props.diff?.added || [] },
  { key: 'modified', label: '修改', color: '#E6A23C', icon: 'EditPen', items: props.diff?.modified || [] },
  { key: 'removed', label: '删除', color: '#F56C6C', icon: 'Remove', items: props.diff?.removed || [] },
  { key: 'unchanged', label: '未变', color: '#909399', icon: 'Minus', items: props.diff?.unchanged || [] },
])
</script>

<template>
  <div class="diff-highlight">
    <!-- 摘要 -->
    <div class="diff-summary">
      <span class="summary-item added">
        <el-icon><CirclePlus /></el-icon>新增 {{ summary.added }}
      </span>
      <span class="summary-item modified">
        <el-icon><EditPen /></el-icon>修改 {{ summary.modified }}
      </span>
      <span class="summary-item removed">
        <el-icon><Remove /></el-icon>删除 {{ summary.removed }}
      </span>
      <span class="summary-item unchanged">
        <el-icon><Minus /></el-icon>未变 {{ summary.unchanged }}
      </span>
    </div>

    <!-- 无差异提示 -->
    <el-empty v-if="!hasDiff" description="两个版本无差异" :image-size="80" />

    <!-- 差异分组列表 -->
    <div v-else class="diff-groups">
      <template v-for="group in groups" :key="group.key">
        <div
          v-if="group.items.length && (group.key !== 'unchanged' || showUnchanged)"
          class="diff-group"
        >
          <div class="group-title" :style="{ color: group.color }">
            <el-icon><component :is="group.icon" /></el-icon>
            <span>{{ group.label }}（{{ group.items.length }}）</span>
          </div>
          <div class="group-list">
            <div
              v-for="(item, idx) in group.items"
              :key="`${group.key}-${idx}`"
              class="diff-item"
              :class="`is-${group.key}`"
            >
              <div class="item-left">
                <div class="item-type-icon" :style="{ backgroundColor: getItemTypeColor(item.item_type) }">
                  <el-icon :size="14"><component :is="getItemTypeIcon(item.item_type)" /></el-icon>
                </div>
                <span class="item-type-tag">{{ getItemTypeLabel(item.item_type) }}</span>
              </div>
              <div class="item-main">
                <div class="item-title">
                  <span v-if="group.key === 'added'" class="sign">+</span>
                  <span v-else-if="group.key === 'removed'" class="sign">-</span>
                  <span v-else-if="group.key === 'modified'" class="sign">*</span>
                  <span v-else class="sign">=</span>
                  第{{ item.day }}天 · {{ item.title }}
                </div>
                <div class="item-meta">
                  <span v-if="item.start_time || item.end_time">{{ formatTimeRange(item.start_time, item.end_time) }}</span>
                  <span v-if="item.location_name"> · {{ item.location_name }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.diff-highlight {
  font-size: 14px;
}
.diff-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding: 10px 12px;
  background: #f5f7fa;
  border-radius: 8px;
  margin-bottom: 12px;
}
.summary-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 600;
}
.summary-item.added { color: #67c23a; }
.summary-item.modified { color: #e6a23c; }
.summary-item.removed { color: #f56c6c; }
.summary-item.unchanged { color: #909399; }

.diff-groups {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.diff-group {
  border-radius: 8px;
  overflow: hidden;
}
.group-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 6px;
}
.group-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.diff-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  border-left: 3px solid transparent;
  background: #fafafa;
}
.diff-item.is-added {
  border-left-color: #67c23a;
  background: #f0f9eb;
}
.diff-item.is-removed {
  border-left-color: #f56c6c;
  background: #fef0f0;
}
.diff-item.is-modified {
  border-left-color: #e6a23c;
  background: #fdf6ec;
}
.diff-item.is-unchanged {
  border-left-color: #909399;
  background: #f4f4f5;
}
.item-left {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.item-type-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
.item-type-tag {
  font-size: 12px;
  color: #909399;
}
.item-main {
  flex: 1;
  min-width: 0;
}
.item-title {
  font-size: 14px;
  color: #303133;
  word-break: break-all;
}
.sign {
  display: inline-block;
  width: 16px;
  font-weight: 700;
}
.is-added .sign { color: #67c23a; }
.is-removed .sign { color: #f56c6c; }
.is-modified .sign { color: #e6a23c; }
.is-unchanged .sign { color: #909399; }
.item-meta {
  margin-top: 2px;
  font-size: 12px;
  color: #909399;
}
</style>
