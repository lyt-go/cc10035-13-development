<template>
  <section class="claim-panel" data-testid="claim-panel" data-module="aggregate_sink">
    <div class="claim-head">
      <div>
        <h3>分发轮次签收对账 · 差额补领单</h3>
        <p class="claim-desc">
          按分发轮次核对欠件，工作台只允许勾选本轮尚缺的窗口生成差额补领单；
          同一分钟在不同轮次/来源是不同欠件，签收只冲销对应轮次及来源。
          预览后到达的迟到签收同样有效，真正领取时不会重复交付已签窗口；
          片段未生成可保留原单续领，已交付片段保留各自回单。
        </p>
      </div>
      <div class="claim-head-actions">
        <button class="btn" type="button" data-testid="refresh-board" @click="reloadAll">
          刷新对账
        </button>
        <button
          class="btn primary"
          type="button"
          data-testid="create-claim-order"
          :disabled="creating || selectedCount === 0"
          @click="createFromSelection"
        >
          {{ creating ? '生成中…' : `新增差额补领单（已勾 ${selectedCount} 窗）` }}
        </button>
      </div>
    </div>

    <p v-if="banner" class="claim-banner" data-testid="claim-banner">{{ banner }}</p>
    <p v-if="errorMessage" class="error-text" data-testid="claim-error">{{ errorMessage }}</p>

    <!-- ============ 各轮欠件（同页平铺，便于核对 R1/R2 同名窗） ============ -->
    <div
      v-for="round in rounds"
      :key="String(round.round_no)"
      class="round-block"
      :data-testid="`round-section-${round.round_no}`"
      :data-round="String(round.round_no)"
    >
      <div class="round-head">
        <h4>
          轮次 <span class="round-no">{{ round.round_no }}</span>
          <span class="round-name">{{ round.name }}</span>
        </h4>
        <span class="round-meta">
          来源 {{ round.source }}（{{ round.source_name }}） ·
          原交付 {{ round.delivery_no }} ·
          欠件 <b :data-testid="`owed-count-${round.round_no}`">{{ round.owed_count }}</b> ·
          已签 {{ round.signed_count }}
        </span>
      </div>

      <table class="data-table window-table" :data-testid="`window-table-${round.round_no}`">
        <thead>
          <tr>
            <th class="col-check">补领勾选</th>
            <th>窗口</th>
            <th>来源</th>
            <th>本轮聚合值</th>
            <th>原交付单</th>
            <th>文件片段</th>
            <th>签收 / 回单</th>
            <th>签收操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="w in windowsOf(String(round.round_no))"
            :key="w.id"
            :data-testid="`window-row-${w.round_no}-${safeWindowId(w.window)}`"
            :data-round="w.round_no"
            :data-window="w.window"
            :data-source="w.source"
            :data-signed="String(w.signed)"
            :class="{ 'row-signed': w.signed }"
          >
            <td class="col-check">
              <input
                v-if="!w.signed"
                type="checkbox"
                class="window-check"
                :data-testid="`claim-check-${w.round_no}-${safeWindowId(w.window)}`"
                :aria-label="`${w.round_no} ${w.window}`"
                :data-round="w.round_no"
                :data-source="w.source"
                :data-window="w.window"
                :checked="!!chosen[windowKey(w)]"
                @change="toggleCheck(w)"
              />
              <span v-else class="muted">—</span>
            </td>
            <td class="window-cell">{{ w.window }}</td>
            <td>{{ w.source }}</td>
            <td>{{ w.value ?? '—' }}</td>
            <td class="mono">{{ w.delivery_no }}</td>
            <td>
              <span :class="w.fragment_ready ? 'frag ready' : 'frag missing'">
                {{ w.片段状态 ?? (w.fragment_ready ? '已生成' : '未生成') }}
              </span>
              <button
                v-if="!w.fragment_ready"
                type="button"
                class="link"
                :data-testid="`gen-fragment-${w.round_no}-${safeWindowId(w.window)}`"
                @click="generateWindowFragment(w)"
              >
                模拟生成
              </button>
            </td>
            <td>
              <span v-if="w.signed" class="signed-text">
                已签收 · 回单
                <span class="mono" :data-testid="`window-receipt-${w.round_no}-${safeWindowId(w.window)}`">
                  {{ w.receipt_no }}
                </span>
              </span>
              <span v-else class="unsigned-text">未签收（欠件）</span>
            </td>
            <td>
              <button
                v-if="!w.signed"
                type="button"
                class="link"
                :data-testid="`sign-${w.round_no}-${safeWindowId(w.window)}`"
                @click="sign(w)"
              >
                签收
              </button>
              <span v-else class="muted">已签</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ============ 差额补领单列表 ============ -->
    <div class="order-list-block" data-testid="claim-order-list">
      <div class="order-list-head">
        <h4>差额补领单（{{ orders.length }}）</h4>
        <button class="btn ghost" type="button" data-testid="reload-orders" @click="reloadAll">
          刷新
        </button>
      </div>
      <p v-if="!orders.length" class="empty-state">
        还没有差额补领单，在上方勾选本轮尚缺窗口后点击「新增差额补领单」。
      </p>
      <div
        v-for="o in orders"
        :key="o.order_no"
        class="order-card"
        :data-testid="`claim-order-card-${o.order_no}`"
        :data-order="o.order_no"
        :data-status="o.status"
      >
        <div class="order-card-main">
          <span class="order-no">{{ o.order_no }}</span>
          <span class="order-title">{{ o.title }}</span>
          <span class="badge" :class="statusBadgeClass(String(o.status_code ?? ''), String(o.status))">
            {{ o.status }}
          </span>
          <span class="muted">轮次 {{ o.round_no }} · {{ lineSummary(o) }}</span>
        </div>
        <button
          class="btn"
          type="button"
          :data-testid="`open-order-${o.order_no}`"
          @click="openOrder(String(o.order_no))"
        >
          打开 / 续领
        </button>
      </div>
    </div>

    <!-- ============ 补领单详情（可重开；内联展示，不遮挡工作台的签收操作） ============ -->
    <div
      v-if="current"
      class="claim-detail-wrap"
      data-testid="claim-order-modal"
    >
      <div class="claim-modal-inline" role="dialog" :aria-label="`差额补领单 ${current.order_no}`">
        <h3>
          差额补领单
          <span class="mono" data-testid="detail-order-no">{{ current.order_no }}</span>
        </h3>
        <p class="claim-meta">
          轮次 <b>{{ current.round_no }}</b> · 来源 {{ current.source }} ·
          {{ current.recipient }} · 当前状态
          <span class="badge" :class="statusBadgeClass(String(current.status_code ?? ''), String(current.status))" data-testid="detail-status">
            {{ current.status }}
          </span>
        </p>

        <div class="detail-actions">
          <button class="btn" type="button" data-testid="preview-order" :disabled="busy" @click="previewCurrent">
            预览差额
          </button>
          <button
            class="btn primary"
            type="button"
            data-testid="confirm-claim"
            :disabled="busy"
            @click="claimCurrent()"
          >
            {{ busy ? '领取中…' : '确认领取并批量导出' }}
          </button>
          <button class="btn" type="button" data-testid="continue-claim" :disabled="busy" @click="claimCurrent()">
            续领未交片段
          </button>
          <a
            class="btn ghost"
            data-testid="export-order-csv"
            :href="claimExportUrl(current.order_no)"
            target="_blank"
            rel="noopener"
          >
            批量导出全部片段
          </a>
        </div>

        <div v-if="previewData" class="preview-panel" data-testid="preview-panel">
          <p>
            预览结果（领取时会再次核对迟到签收）：
            <span data-testid="preview-deliverable">
              将补发 {{ previewData.deliverable_windows?.length ? previewData.deliverable_windows.join('、') : '无' }}
            </span>
            ｜
            <span data-testid="preview-covered">
              已签收跳过 {{ previewData.covered_windows?.length ? previewData.covered_windows.join('、') : '无' }}
            </span>
            ｜
            <span data-testid="preview-missing">
              片段未生成 {{ previewData.fragment_missing_windows?.length ? previewData.fragment_missing_windows.join('、') : '无' }}
            </span>
          </p>
        </div>

        <div
          v-if="lastResult"
          class="claim-result"
          :class="{ 'result-ok': lastResult.ok, 'result-fail': !lastResult.ok }"
          data-testid="claim-result"
        >
          <p data-testid="claim-message">{{ lastResult.message }}</p>
          <p class="result-lists">
            <span data-testid="result-delivered">
              本次实际补发：{{ joinOrNone(lastResult.delivered_windows) }}
            </span>
            <span data-testid="result-covered">
              迟到签收冲销：{{ joinOrNone(lastResult.covered_windows) }}
            </span>
            <span data-testid="result-missing">
              片段仍未生成：{{ joinOrNone(lastResult.fragment_missing_windows) }}
            </span>
            <span data-testid="result-kept">
              保留原回单：{{ joinOrNone(lastResult.already_delivered_windows) }}
            </span>
          </p>
        </div>

        <table class="data-table line-table" data-testid="order-line-table">
          <thead>
            <tr>
              <th>窗口</th>
              <th>来源</th>
              <th>状态</th>
              <th>归属 / 回单</th>
              <th>续领操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="line in current.lines"
              :key="line.line_id"
              :data-testid="`order-line-${line.round_no}-${safeWindowId(line.window)}`"
              :data-window="line.window"
              :data-state="line.state"
            >
              <td class="window-cell">{{ line.window }}</td>
              <td>{{ line.source }}</td>
              <td>
                <span class="badge" :class="lineBadgeClass(String(line.state))" data-testid="line-state">
                  {{ line.state }}
                </span>
              </td>
              <td class="attribution-cell">
                <!-- 迟到签收：能看到是从哪笔原交付、哪张回单签收的 -->
                <span
                  v-if="line.covered"
                  class="attribution covered"
                  :data-testid="`attribution-${line.round_no}-${safeWindowId(line.window)}`"
                >
                  该窗已由<b>原交付 {{ line.original_delivery_no || line.原交付单号 }}</b>
                  签收，回单号
                  <b class="mono">{{ line.original_receipt_no || line.原回单号 }}</b>
                  <span v-if="line.signed_at || line.签收时间" class="muted">
                    （{{ line.signed_at || line.签收时间 }}）
                  </span>
                </span>
                <!-- 已补发：本次补领交付的独立回单与批次 -->
                <span
                  v-else-if="line.delivered"
                  class="attribution delivered"
                  :data-testid="`receipt-${line.round_no}-${safeWindowId(line.window)}`"
                >
                  已随补领批次 <span class="mono">{{ line.batch_no }}</span>
                  交付（{{ line.delivery_no }}），自有回单
                  <b class="mono">{{ line.receipt_no }}</b>
                </span>
                <span v-else-if="line.fragment_missing" class="attribution missing">
                  该段文件片段尚未生成，单据保留，可在片段生成后续领。
                </span>
                <span v-else class="muted">等待领取</span>
              </td>
              <td>
                <button
                  v-if="line.fragment_missing"
                  type="button"
                  class="link"
                  :data-testid="`gen-line-fragment-${line.round_no}-${safeWindowId(line.window)}`"
                  @click="generateLineFragment(line)"
                >
                  生成片段
                </button>
                <button
                  v-if="!line.delivered && !line.covered"
                  type="button"
                  class="link warn-link"
                  :data-testid="`late-sign-${line.round_no}-${safeWindowId(line.window)}`"
                  @click="signLine(line)"
                >
                  模拟迟到签收
                </button>
                <button
                  v-if="line.fragment_missing || line.pending"
                  type="button"
                  class="link"
                  :data-testid="`claim-line-${line.round_no}-${safeWindowId(line.window)}`"
                  @click="claimLine(line)"
                >
                  续领此段
                </button>
                <a
                  v-if="line.delivered && line.batch_no"
                  class="link"
                  :data-testid="`download-line-${line.round_no}-${safeWindowId(line.window)}`"
                  :href="claimExportUrl(current.order_no, String(line.batch_no))"
                  target="_blank"
                  rel="noopener"
                >
                  下载该批片段
                </a>
              </td>
            </tr>
          </tbody>
        </table>

        <div class="receipt-list" data-testid="receipt-list">
          <h5>本单回单（已交付项各自保留独立回单）</h5>
          <ul>
            <li v-for="r in current.receipts ?? []" :key="String(r.receipt_no)" :data-testid="`receipt-item-${r.receipt_no}`">
              <span class="mono">{{ r.receipt_no }}</span>
              · {{ r.轮次 }} {{ r.窗口 }}
              · {{ r.交付类型 }}
              <template v-if="r.补领批次"> · 批次 {{ r.补领批次 }}</template>
            </li>
            <li v-if="!(current.receipts ?? []).length" class="muted">暂无回单</li>
          </ul>
        </div>

        <div class="page-actions modal-footer">
          <button class="btn" type="button" data-testid="close-order" @click="closeOrder">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'

import {
  claimExportUrl,
  createClaimOrder,
  downloadClaimCsv,
  fetchRounds,
  getClaimOrder,
  listClaimOrders,
  previewClaimOrder,
  signWindow,
  submitClaim,
  generateFragment,
  type ClaimOrder,
  type ClaimPreview,
  type ClaimResult,
  type ClaimWindow,
} from '@/api/claim-service'
import { lineBadgeClass, safeWindowId, windowKey } from '@/domain/aggregate_sink'
import { request } from '@/api/client'

const rounds = ref<Array<Record<string, unknown>>>([])
const windows = ref<ClaimWindow[]>([])
const orders = ref<ClaimOrder[]>([])
const chosen = ref<Record<string, ClaimWindow>>({})
const current = ref<ClaimOrder | null>(null)
const previewData = ref<ClaimPreview | null>(null)
const lastResult = ref<ClaimResult | null>(null)
const selectedCount = ref(0)
const creating = ref(false)
const busy = ref(false)
const errorMessage = ref('')
const banner = ref('')

function windowsOf(roundNo: string): ClaimWindow[] {
  return windows.value.filter((w) => w.round_no === roundNo)
}

function toggleCheck(w: ClaimWindow) {
  const key = windowKey(w)
  if (chosen.value[key]) {
    delete chosen.value[key]
  } else {
    chosen.value[key] = w
  }
  selectedCount.value = Object.keys(chosen.value).length
}

function joinOrNone(values?: string[]): string {
  return values && values.length ? values.join('、') : '无'
}

function lineSummary(o: ClaimOrder): string {
  const lines = o.lines ?? []
  const delivered = lines.filter((l) => l.delivered).length
  const covered = lines.filter((l) => l.covered).length
  const missing = lines.filter((l) => l.fragment_missing).length
  return `共 ${lines.length} 窗 / 已补 ${delivered} / 原签冲销 ${covered} / 片段待生成 ${missing}`
}

function statusBadgeClass(code: string, status: string): string {
  if (code === 'completed' || status === '已完成') return 'badge delivered'
  if (code === 'partial' || status === '部分领取') return 'badge pending'
  return 'badge'
}

async function loadBoard() {
  const [roundPayload, windowRes, orderPayload] = await Promise.all([
    fetchRounds(),
    request('/api/aggregate_sink/windows').then((r) => r.json()) as Promise<{
      items: ClaimWindow[]
    }>,
    listClaimOrders(),
  ])
  rounds.value = roundPayload.items as Array<Record<string, unknown>>
  windows.value = windowRes.items ?? []
  orders.value = orderPayload.items ?? []
}

async function reloadAll() {
  errorMessage.value = ''
  try {
    await loadBoard()
    if (current.value) {
      const refreshed = await getClaimOrder(current.value.order_no)
      if (refreshed?.ok !== false) current.value = refreshed
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '对账数据读取失败'
  }
}

async function createFromSelection() {
  errorMessage.value = ''
  banner.value = ''
  const picked = Object.values(chosen.value)
  if (!picked.length) {
    errorMessage.value = '请先勾选本轮尚缺的窗口'
    return
  }
  creating.value = true
  try {
    const result = await createClaimOrder({
      items: picked.map((w) => ({ round_no: w.round_no, source: w.source, window: w.window })),
    })
    if (!result.ok) throw new Error(result.message)
    chosen.value = {}
    selectedCount.value = 0
    banner.value = result.message
    await loadBoard()
    if (result.order_no) await openOrder(result.order_no)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '创建差额补领单失败'
  } finally {
    creating.value = false
  }
}

async function sign(w: ClaimWindow) {
  errorMessage.value = ''
  try {
    const result = await signWindow({
      round_no: w.round_no,
      window: w.window,
      source: w.source,
    })
    if (!result.ok) throw new Error(result.message)
    banner.value = result.message
    await loadBoard()
    // 若补领单开着，顺手重算预览，让“预览后迟到签收”立刻可见。
    if (current.value) {
      try {
        const pv = await previewClaimOrder(current.value.order_no)
        previewData.value = pv.preview
        current.value = { ...current.value, lines: pv.order?.lines ?? current.value.lines }
      } catch {
        /* 预览刷新不阻塞签收 */
      }
      const refreshed = await getClaimOrder(current.value.order_no)
      if (refreshed?.ok !== false) current.value = refreshed
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '签收失败'
  }
}

async function signLine(line: { round_no: string; window: string; source: string }) {
  await sign(line as ClaimWindow)
}

async function openOrder(ref: string | number) {
  errorMessage.value = ''
  lastResult.value = null
  previewData.value = null
  try {
    const detail = await getClaimOrder(ref)
    if (detail?.ok === false) throw new Error(detail.message as string)
    current.value = detail
    await nextTick()
    document
      .querySelector('[data-testid="claim-order-modal"]')
      ?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '打开补领单失败'
  }
}

function closeOrder() {
  current.value = null
  previewData.value = null
  lastResult.value = null
}

async function previewCurrent() {
  if (!current.value) return
  errorMessage.value = ''
  try {
    const result = await previewClaimOrder(current.value.order_no)
    previewData.value = result.preview
    if (result.order) current.value = result.order
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '预览失败'
  }
}

async function claimCurrent(body: Record<string, unknown> = {}) {
  if (!current.value) return
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await submitClaim(current.value.order_no, body)
    lastResult.value = result
    banner.value = result.message
    if (!result.ok) throw new Error(result.message)
    if (result.order) current.value = result.order
    // 有真实新片段交付时，立即下载该次补领批次的实际片段。
    if (result.delivered_windows?.length && result.batch_no) {
      try {
        await downloadClaimCsv(current.value.order_no, result.batch_no)
      } catch {
        /* 下载失败不影响领取结果展示，页面内仍有导出链接 */
      }
    }
    await loadBoard()
    const refreshed = await getClaimOrder(current.value.order_no)
    if (refreshed?.ok !== false) current.value = refreshed
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '领取失败'
  } finally {
    busy.value = false
  }
}

async function claimLine(line: { window: string }) {
  await claimCurrent({ windows: [line.window] })
}

async function generateWindowFragment(w: ClaimWindow) {
  errorMessage.value = ''
  try {
    const result = await generateFragment({
      round_no: w.round_no,
      window: w.window,
      source: w.source,
    })
    if (!result.ok) throw new Error(result.message)
    banner.value = result.message
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '片段生成失败'
  }
}

async function generateLineFragment(line: { round_no: string; window: string; source: string }) {
  errorMessage.value = ''
  try {
    const result = await generateFragment({
      round_no: line.round_no,
      window: line.window,
      source: line.source,
    })
    if (!result.ok) throw new Error(result.message)
    banner.value = result.message
    if (current.value) {
      const pv = await previewClaimOrder(current.value.order_no)
      previewData.value = pv.preview
      if (pv.order) current.value = pv.order
    }
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '片段生成失败'
  }
}

onMounted(reloadAll)
</script>

<style scoped>
.claim-panel {
  margin: 16px 0 24px;
  padding: 18px 20px;
  border: 1px solid #d9e2ec;
  border-radius: 12px;
  background: #fbfdff;
}
.claim-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  flex-wrap: wrap;
}
.claim-head h3 {
  margin: 0 0 6px;
  font-size: 18px;
}
.claim-desc {
  margin: 0;
  max-width: 820px;
  color: #52606d;
  font-size: 13px;
  line-height: 1.7;
}
.claim-head-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.claim-banner {
  margin: 10px 0 0;
  padding: 8px 12px;
  background: #e6f6ec;
  border: 1px solid #9ad8b4;
  border-radius: 8px;
  color: #1c6b3c;
  font-size: 13px;
}
.round-block {
  margin-top: 18px;
  border: 1px solid #e4eaf1;
  border-radius: 10px;
  padding: 12px 14px;
  background: #fff;
}
.round-head h4 {
  margin: 0 0 4px;
  font-size: 15px;
}
.round-no {
  display: inline-block;
  background: #1f6feb;
  color: #fff;
  border-radius: 6px;
  padding: 1px 8px;
  margin: 0 4px;
}
.round-name {
  color: #334e68;
  font-weight: 500;
}
.round-meta {
  font-size: 12.5px;
  color: #627d98;
}
.window-table,
.line-table {
  margin-top: 10px;
}
.col-check {
  width: 72px;
  text-align: center;
}
.window-cell {
  font-weight: 600;
  white-space: nowrap;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
}
.muted {
  color: #9aa5b1;
  font-size: 12.5px;
}
.row-signed {
  background: #f6f8fa;
  color: #7b8794;
}
.signed-text {
  color: #1c6b3c;
  font-size: 13px;
}
.unsigned-text {
  color: #b42318;
  font-size: 13px;
  font-weight: 600;
}
.frag {
  border-radius: 6px;
  padding: 1px 8px;
  font-size: 12px;
  margin-right: 6px;
}
.frag.ready {
  background: #e6f6ec;
  color: #1c6b3c;
}
.frag.missing {
  background: #fff3e0;
  color: #b54708;
}
.order-list-block {
  margin-top: 20px;
}
.order-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.order-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #d9e2ec;
  border-radius: 10px;
  padding: 10px 14px;
  margin-top: 8px;
  background: #fff;
}
.order-card-main {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.order-no {
  font-weight: 700;
  color: #102a43;
}
.order-title {
  color: #486581;
  font-size: 13.5px;
}
.badge {
  display: inline-block;
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 12px;
  background: #e4e7eb;
  color: #334e68;
}
.badge.delivered {
  background: #d1fadf;
  color: #027a48;
}
.badge.covered {
  background: #dbeafe;
  color: #1d4ed8;
}
.badge.missing {
  background: #fef0c7;
  color: #b54708;
}
.badge.pending {
  background: #e0e7ff;
  color: #3730a3;
}
.claim-detail-wrap {
  margin-top: 16px;
  border: 2px solid #1f6feb;
  border-radius: 12px;
  background: #f4f8ff;
  padding: 14px;
}
.claim-modal-inline {
  background: #fff;
  border: 1px solid #d9e2ec;
  border-radius: 10px;
  padding: 18px 20px;
  width: 100%;
  max-height: none;
  overflow: visible;
}
.claim-meta {
  color: #486581;
  font-size: 13.5px;
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.detail-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin: 12px 0;
}
.preview-panel {
  background: #f0f7ff;
  border: 1px solid #b9d7ff;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.8;
}
.claim-result {
  border-radius: 8px;
  padding: 8px 12px;
  margin: 10px 0;
  font-size: 13.5px;
  line-height: 1.7;
}
.claim-result.result-ok {
  background: #ecfdf3;
  border: 1px solid #6ce9a6;
}
.claim-result.result-fail {
  background: #fef3f2;
  border: 1px solid #fda29b;
}
.result-lists {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin: 4px 0 0;
}
.attribution-cell {
  font-size: 13px;
  line-height: 1.7;
  max-width: 360px;
}
.attribution.covered {
  color: #1d4ed8;
}
.attribution.delivered {
  color: #027a48;
}
.attribution.missing {
  color: #b54708;
}
.receipt-list {
  margin-top: 14px;
  border-top: 1px dashed #d9e2ec;
  padding-top: 8px;
}
.receipt-list h5 {
  margin: 0 0 6px;
}
.receipt-list ul {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.9;
}
.modal-footer {
  justify-content: flex-end;
  margin-top: 12px;
}
a.link {
  cursor: pointer;
  text-decoration: none;
}
.warn-link {
  color: #b54708 !important;
  margin: 0 8px;
}
</style>
