/**
 * 聚合分发 · 差额补领领域的纯前端差异逻辑。
 * 真实状态与冲销规则在后端 app/services/claim_order.py，这里只放展示与
 * 选择键等无副作用逻辑，保持工作台组件轻薄。
 */
import type { ClaimLine, ClaimWindow } from '@/api/claim-service'

/** 07:10 -> 0710，用于稳定的 data-testid。 */
export function safeWindowId(window: string): string {
  return String(window ?? '').replace(':', '').replace('：', '')
}

/** 欠件唯一身份：轮次 + 来源 + 窗口。同名窗口在不同轮次是两笔欠件。 */
export function windowKey(w: Pick<ClaimWindow, 'round_no' | 'source' | 'window'>): string {
  return `${w.round_no}::${w.source}::${w.window}`
}

export function lineKey(l: Pick<ClaimLine, 'round_no' | 'source' | 'window'>): string {
  return `${l.round_no}::${l.source}::${l.window}`
}

export const LINE_STATE_BADGE: Record<string, string> = {
  待领取: 'badge pending',
  已补发: 'badge delivered',
  原交付已签收: 'badge covered',
  片段未生成: 'badge missing',
}

export function lineBadgeClass(state: string): string {
  return LINE_STATE_BADGE[state] ?? 'badge'
}
