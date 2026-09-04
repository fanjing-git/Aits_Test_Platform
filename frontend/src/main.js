import { createApp } from 'vue'
import { ElForm, ElFormItem, ElInput, ElTag } from 'element-plus'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/input/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/message/style/css'

import App from './App.vue'
import router from './router'
import { pinia } from './stores'
import './styles/index.css'

const app = createApp(App)

app.use(pinia)
app.use(router)
app.component(ElForm.name, ElForm)
app.component(ElFormItem.name, ElFormItem)
app.component(ElInput.name, ElInput)
app.component(ElTag.name, ElTag)
app.mount('#app')
