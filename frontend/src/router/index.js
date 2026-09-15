// Vue Router 路由配置
import { createRouter, createWebHistory } from 'vue-router'

// 路由表
const routes = [
  {
    path: '/',
    name: 'home',
    // 落地页：创建新行程
    component: () => import('../views/HomeView.vue'),
    meta: { title: 'AI 智能旅行规划' },
  },
  {
    path: '/chat/:sessionId',
    name: 'chat',
    // 对话 + 行程生成页
    component: () => import('../views/ItineraryCreate.vue'),
    meta: { title: '行程生成' },
    props: true,
  },
  {
    path: '/itinerary/:sessionId',
    name: 'itinerary',
    // 行程详情全屏页
    component: () => import('../views/ItineraryDetail.vue'),
    meta: { title: '行程详情' },
    props: true,
  },
  {
    path: '/compare/:sessionId',
    name: 'compare',
    // 版本对比页
    component: () => import('../views/VersionCompare.vue'),
    meta: { title: '版本对比' },
    props: true,
  },
  {
    path: '/share/:code',
    name: 'share',
    // 行程分享落地页
    component: () => import('../views/ShareView.vue'),
    meta: { title: '行程分享' },
    props: true,
  },
  // 兜底：未知路由回到首页
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  // 切换路由时滚动到顶部
  scrollBehavior() {
    return { top: 0 }
  },
})

// 全局前置守卫：设置页面标题
router.beforeEach((to, from, next) => {
  const baseTitle = 'AI 旅行攻略生成系统'
  if (to.meta?.title) {
    document.title = `${to.meta.title} - ${baseTitle}`
  } else {
    document.title = baseTitle
  }
  next()
})

export default router
