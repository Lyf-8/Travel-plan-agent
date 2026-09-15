// 格式化工具函数集合

// 格式化预算区间，例如 ¥1000-2000
export function formatBudget(min, max) {
  if (min == null && max == null) return '预算不限'
  if (min != null && max != null) {
    return `¥${formatNumber(min)}-${formatNumber(max)}`
  }
  if (min != null) return `¥${formatNumber(min)} 起`
  return `¥${formatNumber(max)} 以内`
}

// 数字千分位格式化
export function formatNumber(num) {
  if (num == null) return '0'
  return Number(num).toLocaleString('zh-CN')
}

// 格式化日期为中文形式，例如 2026年8月20日
export function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

// 格式化时长（分钟），例如 2小时30分钟
export function formatDuration(minutes) {
  if (minutes == null) return ''
  const mins = Math.round(minutes)
  if (mins <= 0) return '0分钟'
  const hours = Math.floor(mins / 60)
  const remain = mins % 60
  if (hours > 0 && remain > 0) return `${hours}小时${remain}分钟`
  if (hours > 0) return `${hours}小时`
  return `${remain}分钟`
}

// 格式化距离（米），大于等于 1000 米用公里
export function formatDistance(meters) {
  if (meters == null) return ''
  const m = Number(meters)
  if (m < 1000) return `${Math.round(m)}米`
  return `${(m / 1000).toFixed(1)}公里`
}

// 格式化时间，截取 HH:MM
export function formatTime(timeStr) {
  if (!timeStr) return ''
  // 兼容 HH:MM:SS 与 HH:MM
  return String(timeStr).slice(0, 5)
}

// 时间区间，例如 09:00 - 11:30
export function formatTimeRange(start, end) {
  const s = formatTime(start)
  const e = formatTime(end)
  if (s && e) return `${s} - ${e}`
  if (s) return s
  if (e) return e
  return ''
}

// 交通方式中文标签
export function getTransportLabel(mode) {
  const map = {
    walk: '步行',
    drive: '自驾',
    subway: '地铁',
    bus: '公交',
    taxi: '出租车',
  }
  return map[mode] || mode || ''
}

// 根据行程项类型返回 Element Plus 图标名称
export function getItemTypeIcon(type) {
  const map = {
    attraction: 'Location',
    food: 'Food',
    hotel: 'House',
    transport: 'Van',
    rest: 'Clock',
    shopping: 'ShoppingBag',
  }
  return map[type] || 'Tickets'
}

// 根据行程项类型返回中文标签
export function getItemTypeLabel(type) {
  const map = {
    attraction: '景点',
    food: '餐饮',
    hotel: '住宿',
    transport: '交通',
    rest: '休息',
    shopping: '购物',
  }
  return map[type] || '其他'
}

// 根据行程项类型返回主题色
export function getItemTypeColor(type) {
  const map = {
    attraction: '#409EFF', // 蓝
    food: '#E6A23C',       // 暖橙
    hotel: '#67C23A',      // 绿
    transport: '#909399',  // 灰
    rest: '#909399',       // 灰
    shopping: '#F56C6C',   // 红
  }
  return map[type] || '#409EFF'
}

// 计算单个行程项的总花费
export function getItemCost(item) {
  if (!item) return 0
  const fields = ['cost_ticket', 'cost_food', 'cost_hotel', 'cost_transport', 'cost_other']
  return fields.reduce((sum, f) => sum + (Number(item[f]) || 0), 0)
}

// 费用明细列表（用于展示单项各项费用）
export function getItemCostBreakdown(item) {
  if (!item) return []
  const list = []
  const labels = {
    cost_ticket: '门票',
    cost_food: '餐饮',
    cost_hotel: '住宿',
    cost_transport: '交通',
    cost_other: '其他',
  }
  Object.keys(labels).forEach((key) => {
    const val = Number(item[key]) || 0
    if (val > 0) {
      list.push({ label: labels[key], value: val })
    }
  })
  return list
}
