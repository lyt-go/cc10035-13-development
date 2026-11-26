import { createRouter, createWebHistory } from 'vue-router'

import AggregateClaimPanel from '@/views/AggregateClaimPanel.vue'
import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 差额补领对账的独立全屏入口（工作台 /aggregate_sink 内也内嵌同一面板）。
    { path: '/claims', name: 'claims', component: AggregateClaimPanel },
    { path: '/aggregate_sink/claims', name: 'aggregate-claims', component: AggregateClaimPanel },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
