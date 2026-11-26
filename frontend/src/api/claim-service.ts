/** 差额补领 / 轮次签收对账接口封装。
 * 后端同时提供 /api/aggregate_sink/* 与 /api/claim-orders/* 两组路径，
 * 这里统一使用模块前缀，语义更贴近工作台。
 */
import { request } from './client'

export type ClaimWindow = {
  id: string
  round_no: string
  轮次?: string
  source: string
  来源?: string
  window: string
  窗口?: string
  value?: string
  delivery_no?: string
  原交付单号?: string
  fragment_ready: boolean
  片段状态?: string
  signed: boolean
  签收状态?: string
  receipt_no?: string | null
  回单号?: string | null
  signed_at?: string | null
  [key: string]: unknown
}

export type ClaimLine = {
  line_id: string
  round_no: string
  source: string
  window: string
  state: string
  状态?: string
  status_code?: string
  delivered?: boolean
  covered?: boolean
  fragment_missing?: boolean
  pending?: boolean
  receipt_no?: string | null
  batch_no?: string
  delivery_no?: string
  original_delivery_no?: string
  原交付单号?: string
  original_receipt_no?: string
  原回单号?: string
  [key: string]: unknown
}

export type ClaimOrder = {
  id: number
  order_no: string
  补领单号?: string
  title?: string
  round_no: string
  source: string
  recipient?: string
  status: string
  status_code?: string
  lines: ClaimLine[]
  batches?: Array<Record<string, unknown>>
  receipts?: Array<Record<string, unknown>>
  preview?: ClaimPreview | null
  [key: string]: unknown
}

export type ClaimPreview = {
  deliverable_windows: string[]
  covered_windows: string[]
  fragment_missing_windows: string[]
  already_delivered_windows?: string[]
  [key: string]: unknown
}

export type ClaimResult = {
  ok: boolean
  message: string
  order?: ClaimOrder
  batch_no?: string
  file_name?: string
  csv?: string
  delivered_windows?: string[]
  covered_windows?: string[]
  fragment_missing_windows?: string[]
  already_delivered_windows?: string[]
  [key: string]: unknown
}

async function jsonOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `接口返回 ${response.status}`
    try {
      const body = await response.json()
      detail = body?.message || body?.detail || detail
    } catch {
      /* 忽略非 JSON 错误体 */
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export async function fetchBoard(roundNo?: string): Promise<{
  rounds: Array<Record<string, unknown>>
  windows: ClaimWindow[]
  owed_windows: ClaimWindow[]
  claim_orders: ClaimOrder[]
}> {
  const query = roundNo ? `?round_no=${encodeURIComponent(roundNo)}` : ''
  const res = await request(`/api/aggregate_sink/reconciliation${query}`)
  return jsonOrThrow(res)
}

export async function fetchRounds(): Promise<{ items: Array<Record<string, unknown>> }> {
  const res = await request('/api/aggregate_sink/rounds')
  return jsonOrThrow(res)
}

export async function signWindow(payload: {
  round_no: string
  window: string
  source?: string
}): Promise<ClaimResult> {
  const res = await request('/api/aggregate_sink/sign', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return jsonOrThrow(res)
}

export async function generateFragment(payload: {
  round_no: string
  window: string
  source?: string
}): Promise<ClaimResult> {
  const res = await request('/api/aggregate_sink/fragments/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return jsonOrThrow(res)
}

export async function createClaimOrder(payload: {
  round_no?: string
  windows?: string[]
  items?: Array<Record<string, string>>
  recipient?: string
}): Promise<ClaimResult & { order?: ClaimOrder; order_no?: string; id?: number }> {
  const res = await request('/api/aggregate_sink/claim-orders', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return jsonOrThrow(res)
}

export async function listClaimOrders(): Promise<{ items: ClaimOrder[] }> {
  const res = await request('/api/aggregate_sink/claim-orders')
  return jsonOrThrow(res)
}

export async function getClaimOrder(ref: string | number): Promise<ClaimOrder & ClaimResult> {
  const res = await request(`/api/aggregate_sink/claim-orders/${encodeURIComponent(String(ref))}`)
  return jsonOrThrow(res)
}

export async function previewClaimOrder(ref: string | number): Promise<ClaimResult & { preview: ClaimPreview }> {
  const res = await request(
    `/api/aggregate_sink/claim-orders/${encodeURIComponent(String(ref))}/preview`,
    { method: 'POST', body: JSON.stringify({}) },
  )
  return jsonOrThrow(res)
}

export async function submitClaim(
  ref: string | number,
  body: Record<string, unknown> = {},
): Promise<ClaimResult> {
  const res = await request(
    `/api/aggregate_sink/claim-orders/${encodeURIComponent(String(ref))}/claim`,
    { method: 'POST', body: JSON.stringify(body) },
  )
  return jsonOrThrow(res)
}

export function claimExportUrl(ref: string | number, batchNo?: string): string {
  const base = `/api/aggregate_sink/claim-orders/${encodeURIComponent(String(ref))}/export`
  return batchNo ? `${base}?batch_no=${encodeURIComponent(batchNo)}` : base
}

/** 触发浏览器下载补领片段 CSV（走统一 request 封装以携带代理前缀）。 */
export async function downloadClaimCsv(ref: string | number, batchNo?: string): Promise<void> {
  const response = await request(claimExportUrl(ref, batchNo))
  if (!response.ok) throw new Error('补领片段导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const matched = /filename="?([^"]+)"?/.exec(disposition)
  anchor.download = matched?.[1] ?? `claim-${ref}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}
