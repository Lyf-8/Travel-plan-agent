// 版本差异工具：跨版本匹配行程项并计算差异
import { getItemTypeLabel } from './format'

// 计算行程项的唯一标识，用于跨版本匹配
// 优先使用 amap_poi_id，其次使用 地点名+类型+day 组合，最后回退到标题
export function computeItemKey(item) {
  if (!item) return ''
  // 1. 高德 POI ID 最稳定
  if (item.amap_poi_id) return `poi:${item.amap_poi_id}`
  // 2. 地点名 + 类型 + 天数
  if (item.location_name && item.item_type) {
    return `${item.item_type}:${item.location_name}:${item.day || 0}`
  }
  // 3. 标题 + 类型（标题可能被微调，仅作兜底）
  return `${item.item_type || 'item'}:${item.title || ''}`
}

// 比较两个行程项是否有实质差异
function isItemModified(a, b) {
  if (!a || !b) return true
  const fields = [
    'title',
    'description',
    'start_time',
    'end_time',
    'duration_min',
    'location_name',
    'location_address',
    'longitude',
    'latitude',
    'cost_ticket',
    'cost_food',
    'cost_hotel',
    'cost_transport',
    'cost_other',
    'travel_time_min',
    'travel_distance_m',
    'transport_from_prev',
  ]
  return fields.some((f) => {
    const va = a[f] ?? null
    const vb = b[f] ?? null
    return String(va) !== String(vb)
  })
}

// 计算两个版本行程项数组的差异
// 返回 { added, removed, modified, unchanged }
export function diffItems(oldItems, newItems) {
  const result = { added: [], removed: [], modified: [], unchanged: [] }
  if (!Array.isArray(oldItems)) oldItems = []
  if (!Array.isArray(newItems)) newItems = []

  const oldMap = new Map()
  oldItems.forEach((item) => {
    oldMap.set(computeItemKey(item), item)
  })
  const newMap = new Map()
  newItems.forEach((item) => {
    newMap.set(computeItemKey(item), item)
  })

  // 新增 / 修改 / 不变
  newItems.forEach((item) => {
    const key = computeItemKey(item)
    if (!oldMap.has(key)) {
      result.added.push(item)
    } else if (isItemModified(oldMap.get(key), item)) {
      result.modified.push(item)
    } else {
      result.unchanged.push(item)
    }
  })

  // 删除
  oldItems.forEach((item) => {
    const key = computeItemKey(item)
    if (!newMap.has(key)) {
      result.removed.push(item)
    }
  })

  return result
}

// 将差异结果格式化为人类可读的文本摘要
export function formatDiff(diffResult) {
  if (!diffResult) return '无差异信息'
  const { added, removed, modified, unchanged } = diffResult
  const lines = []
  if (added?.length) {
    lines.push(`🟢 新增 ${added.length} 项：`)
    added.forEach((it) =>
      lines.push(`  + [${getItemTypeLabel(it.item_type)}] 第${it.day}天 ${it.title}`)
    )
  }
  if (removed?.length) {
    lines.push(`🔴 删除 ${removed.length} 项：`)
    removed.forEach((it) =>
      lines.push(`  - [${getItemTypeLabel(it.item_type)}] 第${it.day}天 ${it.title}`)
    )
  }
  if (modified?.length) {
    lines.push(`🟡 修改 ${modified.length} 项：`)
    modified.forEach((it) =>
      lines.push(`  * [${getItemTypeLabel(it.item_type)}] 第${it.day}天 ${it.title}`)
    )
  }
  if (unchanged?.length) {
    lines.push(`⚪ 保持不变 ${unchanged.length} 项`)
  }
  if (lines.length === 0) return '两个版本完全一致'
  return lines.join('\n')
}

// 差异统计摘要（用于头部展示）
export function diffSummary(diffResult) {
  if (!diffResult) return { added: 0, removed: 0, modified: 0, unchanged: 0 }
  return {
    added: diffResult.added?.length || 0,
    removed: diffResult.removed?.length || 0,
    modified: diffResult.modified?.length || 0,
    unchanged: diffResult.unchanged?.length || 0,
  }
}
