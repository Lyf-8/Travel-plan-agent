<script setup>
// 高德地图容器：动态加载高德 JS API，渲染 POI 标记与路线
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'

const props = defineProps({
  // 兴趣点数组：[{ lng, lat, name }]
  pois: {
    type: Array,
    default: () => [],
  },
  // 路线数据：[[{lng,lat}, {lng,lat}, ...], ...]
  routeData: {
    type: Array,
    default: () => [],
  },
  // 地图中心点
  center: {
    type: Object,
    default: null,
  },
  // 缩放级别
  zoom: {
    type: Number,
    default: 12,
  },
})

const emit = defineEmits(['ready', 'error'])

const mapContainer = ref(null)
// 地图实例
const mapInstance = ref(null)
// 标记集合
let markers = []
let polylines = []
// 加载状态
const loading = ref(true)
const loadError = ref('')

// 高德地图 JS API 是否已加载
let scriptLoaded = false
let scriptLoading = false
const loadPromiseResolvers = []

// 动态注入高德地图脚本
function loadAmapScript(key) {
  // 已加载完成直接返回
  if (scriptLoaded && window.AMap) {
    return Promise.resolve(window.AMap)
  }
  // 正在加载则挂载到Promise
  if (scriptLoading) {
    return new Promise((resolve, reject) => {
      loadPromiseResolvers.push({ resolve, reject })
    })
  }
  scriptLoading = true
  const amapKey = key || import.meta.env.VITE_AMAP_KEY || ''
  const securityCode = import.meta.env.VITE_AMAP_SECURITY_CODE || ''

  // 设置安全密钥（高德 JS API 2.0 需要）
  if (securityCode) {
    window._AMapSecurityConfig = {
      securityJsCode: securityCode,
    }
  }

  return new Promise((resolve, reject) => {
    const callbackName = `__amap_init_cb_${Date.now()}`
    window[callbackName] = () => {
      scriptLoaded = true
      scriptLoading = false
      loadPromiseResolvers.forEach((r) => r.resolve(window.AMap))
      loadPromiseResolvers.length = 0
      delete window[callbackName]
      resolve(window.AMap)
    }

    const script = document.createElement('script')
    script.type = 'text/javascript'
    script.async = true
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${amapKey}&callback=${callbackName}&plugin=AMap.Geocoder`
    script.onerror = (e) => {
      scriptLoading = false
      loadError.value = '高德地图脚本加载失败，请检查网络或 Key 配置'
      reject(new Error(loadError.value))
    }
    document.head.appendChild(script)
  })
}

// 初始化地图
async function initMap() {
  loading.value = true
  try {
    const AMap = await loadAmapScript()
    await nextTick()
    if (!mapContainer.value) return

    // 检查是否有合法的 Key
    const amapKey = import.meta.env.VITE_AMAP_KEY || ''
    if (!amapKey) {
      loading.value = false
      loadError.value = '未配置高德地图 Key (VITE_AMAP_KEY)'
      emit('error', new Error(loadError.value))
      return
    }

    const center = props.center
      ? [props.center.lng, props.center.lat]
      : props.pois.length
        ? [props.pois[0].lng, props.pois[0].lat]
        : [116.397428, 39.90923] // 默认北京

    mapInstance.value = new AMap.Map(mapContainer.value, {
      zoom: props.zoom,
      center,
      viewMode: '2D',
    })

    // 监听地图错误
    mapInstance.value.on('error', (e) => {
      console.error('[AMap Error]', e)
    })

    renderPois()
    renderRoutes()
    loading.value = false
    emit('ready', mapInstance.value)
  } catch (err) {
    loading.value = false
    console.error('[AmapContainer] initMap failed:', err)
    loadError.value = err?.message || '地图初始化失败'
    emit('error', err)
  }
}

// 渲染 POI 标记
function renderPois() {
  if (!mapInstance.value || !window.AMap) return
  const AMap = window.AMap
  // 清除旧标记
  markers.forEach((m) => mapInstance.value.remove(m))
  markers = []

  props.pois.forEach((poi, index) => {
    if (poi.lng == null || poi.lat == null) return
    const marker = new AMap.Marker({
      position: [poi.lng, poi.lat],
      title: poi.name || `兴趣点 ${index + 1}`,
      label: poi.name
        ? {
            content: `<div class="amap-marker-label-custom">${poi.name}</div>`,
            direction: 'top',
          }
        : undefined,
    })
    mapInstance.value.add(marker)
    markers.push(marker)
  })

  // 自动适应视野
  if (markers.length) {
    mapInstance.value.setFitView(markers, false, [60, 60, 60, 60])
  }
}

// 渲染路线
function renderRoutes() {
  if (!mapInstance.value || !window.AMap) return
  const AMap = window.AMap
  // 清除旧折线
  polylines.forEach((p) => mapInstance.value.remove(p))
  polylines = []

  const routes = props.routeData || []
  routes.forEach((route) => {
    if (!Array.isArray(route) || route.length < 2) return
    const path = route
      .map((p) => [p.lng, p.lat])
      .filter((p) => p[0] != null && p[1] != null)
    if (path.length < 2) return
    const polyline = new AMap.Polyline({
      path,
      isOutline: true,
      outlineColor: '#ffeeff',
      borderWeight: 1,
      strokeColor: '#409EFF',
      strokeOpacity: 0.9,
      strokeWeight: 4,
      strokeStyle: 'solid',
      lineJoin: 'round',
    })
    mapInstance.value.add(polyline)
    polylines.push(polyline)
  })
}

// 监听数据变化重绘
watch(
  () => props.pois,
  () => {
    if (mapInstance.value) renderPois()
  },
  { deep: true }
)
watch(
  () => props.routeData,
  () => {
    if (mapInstance.value) renderRoutes()
  },
  { deep: true }
)

onMounted(() => {
  initMap()
})

onBeforeUnmount(() => {
  if (mapInstance.value) {
    mapInstance.value.destroy()
    mapInstance.value = null
  }
  markers = []
  polylines = []
})

// 暴露方法供父组件调用
defineExpose({
  getMap: () => mapInstance.value,
  resize: () => mapInstance.value?.setSize(),
  loadAmapScript,
})
</script>

<template>
  <div class="amap-wrapper">
    <div ref="mapContainer" class="amap-container"></div>
    <div v-if="loading" class="amap-loading">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>地图加载中...</span>
    </div>
    <div v-if="loadError" class="amap-error">
      <el-icon><WarningFilled /></el-icon>
      <span>{{ loadError }}</span>
    </div>
    <div v-if="!loading && !pois.length && !loadError" class="amap-empty">
      <span>暂无地图数据</span>
    </div>
  </div>
</template>

<style scoped>
.amap-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 320px;
  border-radius: 12px;
  overflow: hidden;
  background: #e8e8e8;
}
.amap-container {
  width: 100%;
  height: 100%;
}
.amap-loading,
.amap-error,
.amap-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #909399;
  font-size: 14px;
  background: rgba(255, 255, 255, 0.8);
  z-index: 100;
}
.amap-error {
  color: #f56c6c;
}
</style>

<!-- 全局样式：标记点标签（不受 scoped 限制） -->
<style>
.amap-marker-label-custom {
  background: #fff;
  border: 1px solid #409eff;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  color: #303133;
  white-space: nowrap;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
}
/* 高德地图 logo 和版权信息 */
.amap-logo,
.amap-copyright {
  opacity: 0.7 !important;
}
</style>
