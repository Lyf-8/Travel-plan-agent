<script setup>
// 根组件：使用中文语言包包裹路由出口
import { ElConfigProvider } from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
</script>

<template>
  <el-config-provider :locale="zhCn">
    <router-view />
  </el-config-provider>
</template>

<style>
/* 全局样式在 styles/global.css 中维护 */
</style>
