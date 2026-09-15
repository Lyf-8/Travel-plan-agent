<script setup>
// 落地页：填写出行需求并创建会话
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useChatStore } from '../stores/chat'
import { formatBudget } from '../utils/format'

const router = useRouter()
const chatStore = useChatStore()

// 表单数据
const form = reactive({
  destination: '',
  travel_days: 3,
  budget_min: 1000,
  budget_max: 5000,
  travel_style: '休闲',
})

// 旅行风格选项
const styleOptions = [
  { label: '休闲度假', value: '休闲' },
  { label: '文化历史', value: '文化' },
  { label: '美食之旅', value: '美食' },
  { label: '户外冒险', value: '冒险' },
  { label: '亲子家庭', value: '亲子' },
  { label: '摄影打卡', value: '摄影' },
]

// 创建中
const creating = ref(false)

// 预算预览文案
const budgetPreview = () => formatBudget(form.budget_min, form.budget_max)

// 开始规划
async function handleStart() {
  if (!form.destination.trim()) {
    ElMessage.warning('请输入目的地')
    return
  }
  creating.value = true
  try {
    const payload = {
      destination: form.destination.trim(),
      travel_days: form.travel_days,
      budget_min: form.budget_min,
      budget_max: form.budget_max,
      preferences: { travel_style: form.travel_style },
      title: `${form.destination} ${form.travel_days}日游`,
    }
    const res = await chatStore.createSession(payload)
    if (res?.session_id) {
      ElMessage.success('行程已创建，开始对话吧！')
      router.push(`/chat/${res.session_id}`)
    }
  } catch (err) {
    // 错误提示已由拦截器处理
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <div class="home-view">
    <!-- 顶部导航 -->
    <header class="home-header">
      <div class="logo">
        <el-icon :size="28"><Position /></el-icon>
        <span>AI 旅行攻略生成系统</span>
      </div>
    </header>

    <!-- 主体 -->
    <main class="home-main">
      <!-- Hero 区 -->
      <section class="hero">
        <h1 class="hero-title">AI 智能旅行规划</h1>
        <p class="hero-subtitle">告诉我你想去哪，我来为你定制专属行程</p>
        <div class="hero-features">
          <div class="feature-chip">
            <el-icon><ChatDotRound /></el-icon>
            <span>对话式生成</span>
          </div>
          <div class="feature-chip">
            <el-icon><MapLocation /></el-icon>
            <span>智能路线</span>
          </div>
          <div class="feature-chip">
            <el-icon><Coin /></el-icon>
            <span>预算管控</span>
          </div>
          <div class="feature-chip">
            <el-icon><RefreshRight /></el-icon>
            <span>版本迭代</span>
          </div>
        </div>
      </section>

      <!-- 表单卡片 -->
      <section class="form-card">
        <el-form :model="form" label-position="top" class="plan-form">
          <!-- 目的地 -->
          <el-form-item label="目的地">
            <el-input
              v-model="form.destination"
              placeholder="例如：成都、厦门、大理"
              size="large"
              clearable
            >
              <template #prefix><el-icon><LocationFilled /></el-icon></template>
            </el-input>
          </el-form-item>

          <!-- 天数 + 风格 -->
          <div class="form-row">
            <el-form-item label="旅行天数">
              <el-input-number v-model="form.travel_days" :min="1" :max="15" size="large" />
            </el-form-item>
            <el-form-item label="旅行风格">
              <el-select v-model="form.travel_style" size="large" placeholder="选择风格">
                <el-option
                  v-for="opt in styleOptions"
                  :key="opt.value"
                  :label="opt.label"
                  :value="opt.value"
                />
              </el-select>
            </el-form-item>
          </div>

          <!-- 预算区间 -->
          <el-form-item label="预算区间">
            <div class="budget-row">
              <el-input-number v-model="form.budget_min" :min="0" :step="500" size="large" />
              <span class="budget-sep">至</span>
              <el-input-number v-model="form.budget_max" :min="form.budget_min" :step="500" size="large" />
              <el-tag type="info" effect="plain" round>{{ budgetPreview() }}</el-tag>
            </div>
          </el-form-item>

          <!-- 提交按钮 -->
          <el-form-item>
            <el-button
              type="primary"
              size="large"
              class="start-btn"
              :loading="creating"
              @click="handleStart"
            >
              <el-icon><Promotion /></el-icon>
              开始规划
            </el-button>
          </el-form-item>
        </el-form>
      </section>
    </main>
  </div>
</template>

<style scoped>
.home-view {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.home-header {
  padding: 20px 40px;
}
.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #fff;
  font-size: 20px;
  font-weight: 700;
}
.home-main {
  max-width: 760px;
  margin: 0 auto;
  padding: 40px 20px 80px;
}
.hero {
  text-align: center;
  color: #fff;
  margin-bottom: 36px;
}
.hero-title {
  font-size: 42px;
  font-weight: 800;
  letter-spacing: 2px;
  margin-bottom: 12px;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.15);
}
.hero-subtitle {
  font-size: 18px;
  opacity: 0.92;
  margin-bottom: 24px;
}
.hero-features {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 12px;
}
.feature-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: rgba(255, 255, 255, 0.18);
  backdrop-filter: blur(6px);
  border-radius: 999px;
  font-size: 14px;
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.25);
}
.form-card {
  background: #fff;
  border-radius: 20px;
  padding: 32px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
}
.plan-form .form-row {
  display: flex;
  gap: 20px;
}
.plan-form .form-row .el-form-item {
  flex: 1;
}
.budget-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  width: 100%;
}
.budget-sep {
  color: #909399;
}
.start-btn {
  width: 100%;
  height: 52px;
  font-size: 18px;
  font-weight: 600;
  border-radius: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
}
.start-btn:hover {
  opacity: 0.92;
}
@media (max-width: 640px) {
  .hero-title { font-size: 30px; }
  .plan-form .form-row { flex-direction: column; gap: 0; }
  .form-card { padding: 20px; }
}
</style>
