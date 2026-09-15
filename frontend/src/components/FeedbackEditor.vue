<script setup>
// 反馈编辑器：评分、评语、修改指令，提交后触发重生成
import { ref, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { submitFeedback as apiSubmitFeedback } from '../api/itinerary'

const props = defineProps({
  // 会话 ID
  sessionId: {
    type: String,
    required: true,
  },
  // 版本 ID
  versionId: {
    type: [Number, String],
    default: null,
  },
  // 是否在对话框中使用
  visible: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['submit', 'update:visible'])

// 表单数据
const form = reactive({
  rating: 5,
  comment: '',
  edit_instructions: '',
})
// 提交中
const submitting = ref(false)
// 表单引用
const formRef = ref(null)

// 表单校验规则
const rules = {
  rating: [{ required: true, message: '请选择评分', trigger: 'change' }],
}

// 监听对话框打开时重置表单
watch(
  () => props.visible,
  (val) => {
    if (val) {
      form.rating = 5
      form.comment = ''
      form.edit_instructions = ''
    }
  }
)

// 提交反馈
async function handleSubmit() {
  if (!props.versionId) {
    ElMessage.warning('缺少版本信息')
    return
  }
  if (formRef.value) {
    try {
      await formRef.value.validate()
    } catch {
      return
    }
  }
  submitting.value = true
  try {
    const payload = {
      version_id: props.versionId,
      rating: form.rating,
      comment: form.comment,
      edit_instructions: form.edit_instructions || undefined,
    }
    const res = await apiSubmitFeedback(props.sessionId, payload)
    ElMessage.success('反馈已提交')
    emit('submit', res)
    // 关闭对话框
    emit('update:visible', false)
  } catch (err) {
    // 错误提示已由拦截器处理
  } finally {
    submitting.value = false
  }
}

// 取消
function handleCancel() {
  emit('update:visible', false)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="行程反馈"
    width="520px"
    @update:model-value="(v) => emit('update:visible', v)"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <!-- 评分 -->
      <el-form-item label="整体评分" prop="rating">
        <el-rate v-model="form.rating" :max="5" show-text :texts="['很差', '较差', '一般', '较好', '很好']" />
      </el-form-item>

      <!-- 评语 -->
      <el-form-item label="评价内容">
        <el-input
          v-model="form.comment"
          type="textarea"
          :rows="3"
          placeholder="对本次行程的整体评价，例如：节奏合适、景点选择不错..."
          maxlength="500"
          show-word-limit
        />
      </el-form-item>

      <!-- 修改指令 -->
      <el-form-item label="修改建议">
        <el-input
          v-model="form.edit_instructions"
          type="textarea"
          :rows="4"
          placeholder="告诉 AI 如何调整，例如：第二天行程太满，希望减少景点；增加一家当地特色餐厅..."
          maxlength="1000"
          show-word-limit
        />
        <div class="form-tip">
          <el-icon><InfoFilled /></el-icon>
          <span>填写修改建议后，系统将基于反馈重新生成行程</span>
        </div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="handleCancel">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSubmit">
        提交反馈
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.form-tip {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 4px;
  color: #909399;
  font-size: 12px;
  line-height: 1.4;
}
</style>
