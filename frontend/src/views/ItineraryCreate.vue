<script setup>
// 对话 + 行程生成页：左侧对话、右侧行程展示
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useChatStore } from '../stores/chat'
import { useItineraryStore } from '../stores/itinerary'
import ItineraryCard from '../components/ItineraryCard.vue'
import { sendMessageStream } from '../api/chat'

const route = useRoute()
const router = useRouter()
const chatStore = useChatStore()
const itineraryStore = useItineraryStore()

// 当前会话 ID
const sessionId = computed(() => route.params.sessionId)

// 输入框内容
const inputText = ref('')
// 消息列表引用，用于自动滚动
const messageListRef = ref(null)
// 当前选中天数 tab
const activeDay = ref('1')

// 当前会话信息
const session = computed(() => chatStore.currentSession)
// 消息列表
const messages = computed(() => chatStore.messages)
// 发送中
const sending = computed(() => chatStore.sending)
// 是否存在流式气泡（存在时隐藏底部独立的"正在输入"指示器）
const hasStreamingMessage = computed(() =>
  chatStore.messages.some((m) => m.streaming)
)
// 当前行程
const itinerary = computed(() => itineraryStore.currentItinerary)
// 按天分组
const itemsByDay = computed(() => itineraryStore.itemsByDay)
// 天数列表
const dayTabs = computed(() => {
  const days = Object.keys(itemsByDay.value).map(Number).sort((a, b) => a - b)
  return days.length ? days : [1]
})
// 当前版本
const currentVersion = computed(() => itinerary.value?.version)

// ===== 流式进度相关状态 =====
// 是否流式模式（默认流式）
const useStreamMode = ref(true)
// 进度条总百分比
const streamProgress = ref(0)
// 当前执行节点名（展示用中文）
const NODE_LABELS = {
  intent_understanding: '意图理解',
  itinerary_framework: '行程框架设计',
  poi_retrieval: 'POI 检索',
  travel_context: '出行环境整合',
  resource_budget: '资源预算规划',
  content_beautify: '文案美化生成',
  map_and_share: '地图与分享数据',
  final_output: '最终结果输出',
}
// 当前节点
const currentNode = ref('')
// 当前节点索引
const currentNodeIndex = ref(-1)
// 总节点数
const totalNodes = ref(8)
// 当前累计 token
const currentTokens = ref(0)

// ===== 流式气泡（节点级实时文本流）=====
// 当前流式 AI 消息对象引用（直接修改其 content 触发视图更新）
const streamMsg = ref(null)
// 各节点步骤行：[{ icon, text }]，随 node_start/node_progress 实时更新
const streamSteps = ref([])

// 根据步骤数组重建流式气泡文本
function rebuildStreamContent() {
  if (!streamMsg.value) return
  streamMsg.value.content = streamSteps.value
    .map((s) => `${s.icon} ${s.text}`)
    .join('\n')
}

// upsert 某一步：同 index 的"运行中"行会被"已完成"行替换
function upsertStreamStep(index, icon, text) {
  const i = Math.max(0, index ?? streamSteps.value.length)
  streamSteps.value[i] = { icon, text }
  rebuildStreamContent()
}

// 移除流式气泡（出错时调用）
function removeStreamMessage() {
  if (!streamMsg.value) return
  const idx = chatStore.messages.indexOf(streamMsg.value)
  if (idx > -1) chatStore.messages.splice(idx, 1)
  streamMsg.value = null
  streamSteps.value = []
}

// 自动滚动到底部
async function scrollToBottom() {
  await nextTick()
  if (messageListRef.value) {
    messageListRef.value.scrollTop = messageListRef.value.scrollHeight
  }
}

// 重置流式进度状态
function resetStreamState() {
  streamProgress.value = 0
  currentNode.value = ''
  currentNodeIndex.value = -1
  currentTokens.value = 0
  streamSteps.value = []
  streamMsg.value = null
}

// 流式发送消息
async function handleSendStream(text) {
  resetStreamState()
  chatStore.sending = true
  // 先乐观加入用户消息
  chatStore.messages.push({ role: 'user', content: text, created_at: new Date().toISOString() })
  // 立即插入一条 AI 流式气泡（节点事件实时往里写内容）
  chatStore.messages.push({
    role: 'assistant',
    content: '',
    streaming: true,
    created_at: new Date().toISOString(),
  })
  // 取 store 中的响应式引用
  streamMsg.value = chatStore.messages[chatStore.messages.length - 1]
  await scrollToBottom()

  let resData = null
  try {
    resData = await sendMessageStream(sessionId.value, text, {
      onOpen: () => {},
      onNodeStart: (data) => {
        if (data) {
          currentNode.value = data.node || ''
          currentNodeIndex.value = data.index ?? -1
          totalNodes.value = data.total ?? 8
          upsertStreamStep(
            data.index,
            '🔄',
            data.detail || `正在${NODE_LABELS[data.node] || '处理'}…`
          )
          scrollToBottom()
        }
      },
      onNodeProgress: (data) => {
        if (data) {
          streamProgress.value = data.progress ?? 0
          currentNode.value = data.node || currentNode.value
          currentNodeIndex.value = data.index ?? currentNodeIndex.value
          totalNodes.value = data.total ?? 8
          currentTokens.value = data.total_tokens ?? currentTokens.value
          upsertStreamStep(
            data.index,
            '✅',
            data.detail || `${NODE_LABELS[data.node] || '该步骤'}已完成`
          )
          scrollToBottom()
        }
      },
      onClarification: (data) => {
        if (data?.question) {
          ElMessage.info(`需要澄清：${data.question}`)
        }
      },
      onDone: (data) => {
        if (data && streamMsg.value) {
          // 用最终回复定稿流式气泡（步骤文本被正式回复替换）
          streamMsg.value.content = data.reply || '行程已生成，请在右侧查看。'
          streamMsg.value.streaming = false
          streamMsg.value.extra = {
            itinerary: data.itinerary,
            version: data.version,
          }
          streamMsg.value = null
          streamSteps.value = []
        }
      },
      onError: (err) => {
        // 出错时移除流式气泡，避免留下半截步骤
        removeStreamMessage()
        ElMessage.error(err?.message || '发送失败')
      },
    })

    if (resData?.version != null || resData?.itinerary) {
      await itineraryStore.loadItinerary(sessionId.value)
    }
    await scrollToBottom()
    return resData
  } catch (err) {
    // 失败时移除 AI 气泡和用户消息
    removeStreamMessage()
    chatStore.messages.pop()
    throw err
  } finally {
    chatStore.sending = false
    // 发送完成后延迟清空进度条状态
    setTimeout(() => {
      resetStreamState()
    }, 1500)
  }
}

// 发送消息
async function handleSend() {
  const text = inputText.value.trim()
  if (!text || sending.value) return
  inputText.value = ''
  try {
    if (useStreamMode.value) {
      await handleSendStream(text)
    } else {
      const res = await chatStore.sendMessage(sessionId.value, text)
      if (res?.version != null || res?.itinerary) {
        await itineraryStore.loadItinerary(sessionId.value)
      }
      await scrollToBottom()
    }
  } catch (err) {
    // 错误已处理
  }
}

// 回车发送（Shift+Enter 换行）
function handleEnter(e) {
  if (e.shiftKey) return
  e.preventDefault()
  handleSend()
}

// 跳转到详情页
function goDetail() {
  router.push(`/itinerary/${sessionId.value}`)
}

// 跳转到版本对比
function goCompare() {
  router.push(`/compare/${sessionId.value}`)
}

// 初始化：加载会话、历史、行程
onMounted(async () => {
  if (!sessionId.value) return
  try {
    await chatStore.selectSession(sessionId.value)
    await itineraryStore.loadItinerary(sessionId.value)
    await scrollToBottom()
  } catch (err) {
    // 错误已处理
  }
})

// 消息变化时自动滚动
watch(
  () => messages.value.length,
  () => scrollToBottom()
)
</script>

<template>
  <div class="create-view">
    <!-- 顶栏 -->
    <header class="top-bar">
      <div class="bar-left">
        <el-button text @click="router.push('/')">
          <el-icon><ArrowLeft /></el-icon>返回
        </el-button>
        <span class="session-title">{{ session?.title || '行程生成' }}</span>
      </div>
      <div class="bar-right">
        <el-button v-if="itinerary" size="small" @click="goDetail">
          <el-icon><Document /></el-icon>详情
        </el-button>
        <el-button v-if="itinerary" size="small" @click="goCompare">
          <el-icon><CopyDocument /></el-icon>版本对比
        </el-button>
      </div>
    </header>

    <!-- 主体：左右分栏 -->
    <div class="split-layout">
      <!-- 左侧对话区 (40%) -->
      <section class="chat-panel">
        <div ref="messageListRef" class="chat-messages">
          <!-- 空状态 -->
          <el-empty
            v-if="!messages.length && !chatStore.loading"
            description="开始和 AI 对话，生成你的专属行程"
            :image-size="100"
          />
          <!-- 消息列表 -->
          <div
            v-for="(msg, idx) in messages"
            :key="idx"
            class="message-item"
            :class="msg.role"
          >
            <div class="message-avatar">
              <el-icon v-if="msg.role === 'user'"><User /></el-icon>
              <el-icon v-else><ChatLineRound /></el-icon>
            </div>
            <div class="message-content">
              <div class="message-role">{{ msg.role === 'user' ? '我' : 'AI 助手' }}</div>
              <!-- 流式气泡：尚无内容时显示打字点 -->
              <div v-if="msg.streaming && !msg.content" class="message-text">
                <span class="typing-inline"><span></span><span></span><span></span></span>
              </div>
              <!-- 流式 / 普通文本（流式时末尾带闪烁光标） -->
              <div v-else class="message-text" :class="{ 'is-streaming': msg.streaming }">
                {{ msg.content }}<span v-if="msg.streaming" class="stream-cursor">▍</span>
              </div>
            </div>
          </div>
          <!-- 加载中（非流式模式 / 尚未建立气泡时显示） -->
          <div v-if="sending && !hasStreamingMessage" class="message-item assistant">
            <div class="message-avatar"><el-icon><ChatLineRound /></el-icon></div>
            <div class="message-content">
              <div class="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        </div>

        <!-- 流式进度条（发送中显示） -->
        <div v-if="sending" class="stream-progress-wrap">
          <div class="progress-header">
            <span class="current-node">
              {{ currentNodeIndex + 1 }} / {{ totalNodes }}
              ·
              {{ NODE_LABELS[currentNode] || currentNode || '处理中' }}
            </span>
            <span class="progress-pct">{{ streamProgress }}%</span>
          </div>
          <div class="progress-bar">
            <div
              class="progress-fill"
              :style="{ width: streamProgress + '%' }"
            ></div>
          </div>
          <div class="progress-meta">
            <span v-if="currentTokens > 0">Token: {{ currentTokens }}</span>
            <span class="progress-tip">正在生成行程，请稍候...</span>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="chat-input">
          <div class="input-topbar">
            <label class="stream-switch">
              <input
                type="checkbox"
                v-model="useStreamMode"
                :disabled="sending"
              />
              <span>流式生成</span>
            </label>
          </div>
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="输入你的想法，按 Enter 发送，Shift+Enter 换行"
            @keydown.enter="handleEnter"
          />
          <el-button
            type="primary"
            :loading="sending"
            :disabled="!inputText.trim()"
            @click="handleSend"
            class="send-btn"
          >
            <el-icon><Promotion /></el-icon>
            发送
          </el-button>
        </div>
      </section>

      <!-- 右侧行程展示区 (60%) -->
      <section class="itinerary-panel">
        <div v-if="itineraryStore.loading" class="panel-loading">
          <el-icon class="is-loading" :size="32"><Loading /></el-icon>
          <span>行程生成中...</span>
        </div>

        <template v-else-if="itinerary">
          <!-- 行程头部信息 -->
          <div class="itinerary-header">
            <div class="header-info">
              <span class="version-tag">v{{ currentVersion }}</span>
              <span v-if="itinerary.total_budget" class="budget-tag">
                预算 ¥{{ itinerary.total_budget }}
              </span>
            </div>
            <div class="header-actions">
              <el-button size="small" @click="goDetail">查看详情</el-button>
            </div>
          </div>

          <!-- 预算明细面板 -->
          <div v-if="itineraryStore.budgetBreakdown" class="budget-panel">
            <div class="panel-title">预算明细</div>
            <div class="budget-grid">
              <div class="budget-item">
                <span class="budget-label">住宿</span>
                <span class="budget-value">¥{{ itineraryStore.budgetBreakdown.hotel || 0 }}</span>
              </div>
              <div class="budget-item">
                <span class="budget-label">餐饮</span>
                <span class="budget-value">¥{{ itineraryStore.budgetBreakdown.food || 0 }}</span>
              </div>
              <div class="budget-item">
                <span class="budget-label">交通</span>
                <span class="budget-value">¥{{ itineraryStore.budgetBreakdown.transport || 0 }}</span>
              </div>
              <div class="budget-item">
                <span class="budget-label">门票</span>
                <span class="budget-value">¥{{ itineraryStore.budgetBreakdown.tickets || 0 }}</span>
              </div>
              <div class="budget-item">
                <span class="budget-label">其他</span>
                <span class="budget-value">¥{{ itineraryStore.budgetBreakdown.other || 0 }}</span>
              </div>
              <div class="budget-item total">
                <span class="budget-label">总计</span>
                <span class="budget-value">¥{{ itineraryStore.budgetBreakdown.total || 0 }}</span>
              </div>
            </div>
          </div>

          <!-- 天气信息 -->
          <div v-if="itineraryStore.weatherInfo" class="weather-panel">
            <span class="weather-icon">🌤</span>
            <span v-if="itineraryStore.weatherInfo.forecasts">
              {{ itineraryStore.weatherInfo.forecasts?.[0]?.dayweather || '' }}
              {{ itineraryStore.weatherInfo.forecasts?.[0]?.daytemp_float || itineraryStore.weatherInfo.forecasts?.[0]?.daytemp || '' }}°
            </span>
            <span v-else>{{ JSON.stringify(itineraryStore.weatherInfo).slice(0, 80) }}</span>
          </div>

          <!-- 地图面板 -->
          <div v-if="itineraryStore.mapData && itineraryStore.mapData.markers?.length" class="map-panel">
            <div class="panel-title">行程地图</div>
            <div class="map-info">
              <span>{{ itineraryStore.mapData.markers?.length || 0 }} 个标记点</span>
              <span v-if="itineraryStore.mapData.polylines?.length">
                · {{ itineraryStore.mapData.polylines.length }} 条路线
              </span>
            </div>
          </div>

          <!-- 天数切换 -->
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
        </template>

        <!-- 空状态 -->
        <el-empty
          v-else
          description="还没有行程，发送消息开始生成吧"
          :image-size="120"
        />
      </section>
    </div>
  </div>
</template>

<style scoped>
.create-view {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f0f2f5;
}
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  z-index: 10;
}
.bar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.session-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.bar-right {
  display: flex;
  gap: 8px;
}
.split-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}
.chat-panel {
  width: 40%;
  min-width: 320px;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-right: 1px solid #ebeef5;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.message-item {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}
.message-avatar {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f0f2f5;
  color: #909399;
}
.message-item.user .message-avatar {
  background: #409eff;
  color: #fff;
}
.message-content {
  flex: 1;
  min-width: 0;
}
.message-role {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.message-text {
  display: inline-block;
  padding: 10px 14px;
  background: #f5f7fa;
  border-radius: 10px;
  font-size: 14px;
  color: #303133;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.message-item.user .message-text {
  background: #ecf5ff;
  color: #303133;
}
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 14px;
  background: #f5f7fa;
  border-radius: 10px;
  width: fit-content;
}
.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c0c4cc;
  animation: typing 1.2s infinite ease-in-out;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing {
  0%, 60%, 100% { transform: scale(0.7); opacity: 0.5; }
  30% { transform: scale(1); opacity: 1; }
}
/* 流式气泡内联打字点（内容尚未到达时） */
.typing-inline {
  display: inline-flex;
  gap: 4px;
}
.typing-inline span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c0c4cc;
  animation: typing 1.2s infinite ease-in-out;
}
.typing-inline span:nth-child(2) { animation-delay: 0.2s; }
.typing-inline span:nth-child(3) { animation-delay: 0.4s; }
/* 流式文本末尾闪烁光标 */
.message-text.is-streaming {
  border-bottom-right-radius: 2px;
}
.stream-cursor {
  display: inline-block;
  margin-left: 2px;
  color: #409eff;
  font-weight: 400;
  animation: stream-blink 1s steps(1) infinite;
}
@keyframes stream-blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}
.stream-progress-wrap {
  padding: 10px 16px;
  border-top: 1px solid #ebeef5;
  background: #fafbfc;
}
.progress-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 6px;
}
.current-node {
  color: #409eff;
  font-weight: 500;
}
.progress-pct {
  color: #606266;
  font-variant-numeric: tabular-nums;
}
.progress-bar {
  width: 100%;
  height: 6px;
  background: #e4e7ed;
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #409eff, #67c23a);
  border-radius: 3px;
  transition: width 0.3s ease;
}
.progress-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}
.chat-input {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px 12px;
  border-top: 1px solid #ebeef5;
}
.input-topbar {
  display: flex;
  align-items: center;
  justify-content: flex-start;
}
.stream-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #606266;
  cursor: pointer;
  user-select: none;
}
.stream-switch input[type="checkbox"] {
  width: 14px;
  height: 14px;
  accent-color: #409eff;
  cursor: pointer;
}
.stream-switch:has(input:disabled) {
  cursor: not-allowed;
  opacity: 0.6;
}
.chat-input .el-textarea {
  width: 100%;
}
.send-btn {
  align-self: flex-end;
}
.itinerary-panel {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.panel-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: #909399;
}
.itinerary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.header-info {
  display: flex;
  align-items: center;
  gap: 8px;
}
.version-tag {
  padding: 4px 10px;
  background: #ecf5ff;
  color: #409eff;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
}
.budget-tag {
  padding: 4px 10px;
  background: #fdf6ec;
  color: #e6a23c;
  border-radius: 6px;
  font-size: 13px;
}
.day-items {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.budget-panel {
  background: #f5f7fa;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}
.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.budget-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.budget-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 4px;
  background: #fff;
  border-radius: 6px;
}
.budget-item.total {
  background: #ecf5ff;
}
.budget-label {
  font-size: 12px;
  color: #909399;
}
.budget-value {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.budget-item.total .budget-value {
  color: #409eff;
}
.weather-panel {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: #fdf6ec;
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #e6a23c;
}
.map-panel {
  background: #f0f9eb;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}
.map-info {
  font-size: 13px;
  color: #67c23a;
}
@media (max-width: 768px) {
  .split-layout { flex-direction: column; }
  .chat-panel { width: 100%; min-width: 0; height: 50%; border-right: none; border-bottom: 1px solid #ebeef5; }
  .itinerary-panel { height: 50%; }
}
</style>
