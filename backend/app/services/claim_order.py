"""差额补领单领域服务。

承载「聚合分发」模块里接收方按 *分发轮次* 签收对账的真实业务差异：

- 分发欠件以 ``(轮次, 来源, 窗口分钟)`` 为唯一身份；同一分钟在 R1/R2 可能
  被不同轮次重算，签收/冲销只能命中对应轮次及来源的欠件。
- 接收方在工作台只勾选本轮尚缺的窗口生成 *差额补领单*。
- 预览不锁定签收状态；真正领取时重新核对回单，预览之后才到达的迟到签收
  同样有效，已由原交付签收或已随补领交付过的窗口一律不再交付。
- 每次领取只导出 *本次补领批次* 实际生成的片段并记录归属；片段尚未生成的
  行保留在单上，之后可打开原单续领，已交付行保留各自独立回单，不重复交付。

本模块只依赖标准库，数据保存在进程内单例，种子即题目所述 R1/R2 场景。
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from app.store import store

CST = timezone(timedelta(hours=8))

# ---- 行/单状态（中文为页面与领域通用语，英文 code 供程序化断言） ----
LINE_PENDING = "待领取"
LINE_DELIVERED = "已补发"
LINE_COVERED = "原交付已签收"
LINE_FRAGMENT_MISSING = "片段未生成"

ORDER_OPEN = "待领取"
ORDER_PARTIAL = "部分领取"
ORDER_COMPLETED = "已完成"

_LINE_CODE = {
    LINE_PENDING: "pending",
    LINE_DELIVERED: "delivered",
    LINE_COVERED: "covered",
    LINE_FRAGMENT_MISSING: "fragment_missing",
}


def _now() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def _norm_window(value: Any) -> str:
    """把 07:10 / '0710' / '2026-..T07:10:00' 统一成 ``HH:MM``。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if "T" in text:
        try:
            text = text.split("T", 1)[1][:5]
        except IndexError:
            text = text
    if len(text) >= 5 and text[2] == ":":
        return text[:5]
    digits = text.replace(":", "").replace("：", "")
    if len(digits) == 4 and digits.isdigit():
        return f"{digits[:2]}:{digits[2:]}"
    return text


def _first(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return default


class ClaimOrderService:
    """差额补领单 + 轮次签收对账的内存领域服务。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset()

    # ======================== 种子 / 重置 ========================

    def reset(self) -> dict[str, Any]:
        """恢复到题目所述的 R1/R2 经典场景，便于测试与演示。"""
        with self._lock:
            self.rounds: list[dict[str, Any]] = [
                {
                    "round_no": "R1",
                    "轮次": "R1",
                    "name": "第1轮 · 早间初算分发",
                    "轮次名称": "第1轮 · 早间初算分发",
                    "source": "SRC-MAIN",
                    "来源": "SRC-MAIN",
                    "source_name": "聚合主源 agg.window.main",
                    "来源名称": "聚合主源 agg.window.main",
                    "delivery_no": "JF-20261126-R1",
                    "原交付单号": "JF-20261126-R1",
                },
                {
                    "round_no": "R2",
                    "轮次": "R2",
                    "name": "第2轮 · 迟到重算分发",
                    "轮次名称": "第2轮 · 迟到重算分发",
                    "source": "SRC-MAIN",
                    "来源": "SRC-MAIN",
                    "source_name": "聚合主源 agg.window.main",
                    "来源名称": "聚合主源 agg.window.main",
                    "delivery_no": "JF-20261126-R2",
                    "原交付单号": "JF-20261126-R2",
                },
                {
                    "round_no": "R3",
                    "轮次": "R3",
                    "name": "第3轮 · 分片补传",
                    "轮次名称": "第3轮 · 分片补传",
                    "source": "SRC-MAIN",
                    "来源": "SRC-MAIN",
                    "source_name": "聚合主源 agg.window.main",
                    "来源名称": "聚合主源 agg.window.main",
                    "delivery_no": "JF-20261126-R3",
                    "原交付单号": "JF-20261126-R3",
                },
            ]
            self.windows: list[dict[str, Any]] = []
            self.receipts: list[dict[str, Any]] = []
            self.orders: list[dict[str, Any]] = []
            self._order_seq = 0
            self._receipt_seq = 0
            self._batch_seq = 0

            def add_receipt(*, round_no: str, source: str, window: str,
                            delivery_no: str, kind: str,
                            order_no: str = "", batch_no: str = "",
                            signed_at: str = "") -> dict[str, Any]:
                self._receipt_seq += 1
                receipt_no = f"HD-{self._receipt_seq:04d}"
                receipt = {
                    "receipt_no": receipt_no,
                    "回单号": receipt_no,
                    "round_no": round_no,
                    "轮次": round_no,
                    "source": source,
                    "来源": source,
                    "window": window,
                    "窗口": window,
                    "delivery_no": delivery_no,
                    "交付单号": delivery_no,
                    "delivery_kind": kind,
                    "交付类型": "原交付" if kind == "original" else "补领交付",
                    "order_no": order_no,
                    "补领单号": order_no,
                    "batch_no": batch_no,
                    "补领批次": batch_no,
                    "signed_at": signed_at or _now(),
                    "签收时间": signed_at or _now(),
                }
                self.receipts.append(receipt)
                return receipt

            def add_window(*, round_no: str, window: str, value: str,
                           signed: bool = False, ready: bool = True,
                           receipt: dict[str, Any] | None = None) -> dict[str, Any]:
                round_meta = self.get_round(round_no) or {}
                source = round_meta.get("source", "SRC-MAIN")
                delivery_no = round_meta.get("delivery_no", f"JF-{round_no}")
                fragment = f"part-{round_no.lower()}-{window.replace(':', '')}.csv"
                row = {
                    "id": f"WIN-{round_no}-{window.replace(':', '')}",
                    "window_id": f"WIN-{round_no}-{window.replace(':', '')}",
                    "round_no": round_no,
                    "轮次": round_no,
                    "source": source,
                    "来源": source,
                    "window": window,
                    "窗口": window,
                    "minute": window,
                    "数据窗口": window,
                    "value": value,
                    "聚合值": value,
                    "delivery_no": delivery_no,
                    "原交付单号": delivery_no,
                    "fragment_name": fragment,
                    "片段文件": fragment,
                    "fragment_ready": ready,
                    "片段已生成": ready,
                    "fragment_status": "已生成" if ready else "未生成",
                    "片段状态": "已生成" if ready else "未生成",
                    "signed": signed,
                    "已签收": signed,
                    "sign_status": "已签收" if signed else "未签收",
                    "签收状态": "已签收" if signed else "未签收",
                    "receipt_no": (receipt or {}).get("receipt_no") if receipt else None,
                    "回单号": (receipt or {}).get("receipt_no") if receipt else None,
                    "signed_at": (receipt or {}).get("signed_at") if receipt else None,
                    "签收时间": (receipt or {}).get("signed_at") if receipt else None,
                }
                self.windows.append(row)
                return row

            # R1：07:00 已正常签收；07:10、07:20 两窗未签（题目主场景）。
            r1_0700_rc = add_receipt(
                round_no="R1", source="SRC-MAIN", window="07:00",
                delivery_no="JF-20261126-R1", kind="original",
                signed_at="2026-11-26T07:06:12+08:00")
            add_window(round_no="R1", window="07:00", value="21.4",
                       signed=True, receipt=r1_0700_rc)
            add_window(round_no="R1", window="07:10", value="22.1")
            add_window(round_no="R1", window="07:20", value="22.8")

            # R2：重算轮，同名 07:10 是另一笔欠件，值也不同。
            r2_0700_rc = add_receipt(
                round_no="R2", source="SRC-MAIN", window="07:00",
                delivery_no="JF-20261126-R2", kind="original",
                signed_at="2026-11-26T07:07:03+08:00")
            add_window(round_no="R2", window="07:00", value="21.5",
                       signed=True, receipt=r2_0700_rc)
            add_window(round_no="R2", window="07:10", value="22.6")

            # R3：片段未生成续领示例。08:00 已随示例补领单交付并持有自己的回单，
            # 08:10 片段尚未生成。
            seg_rc = add_receipt(
                round_no="R3", source="SRC-MAIN", window="08:00",
                delivery_no="JF-BL-XP-01-B1", kind="claim",
                order_no="BL-XP-01", batch_no="BL-XP-01-B1",
                signed_at="2026-11-26T08:04:40+08:00")
            add_window(round_no="R3", window="08:00", value="31.2",
                       signed=True, receipt=seg_rc)
            add_window(round_no="R3", window="08:10", value="31.7", ready=False)

            demo_order = self._new_order_record(
                order_id=9001, order_no="BL-XP-01", round_no="R3",
                source="SRC-MAIN", recipient="接收方 · 数据对账组",
                title="片段未生成续领示例单")
            demo_order["lines"] = [
                self._make_line(
                    round_no="R3", source="SRC-MAIN", window="08:00",
                    state=LINE_DELIVERED, batch_no="BL-XP-01-B1",
                    receipt=seg_rc,
                    delivery_no="JF-BL-XP-01-B1",
                    delivered_at="2026-11-26T08:04:40+08:00"),
                self._make_line(
                    round_no="R3", source="SRC-MAIN", window="08:10",
                    state=LINE_FRAGMENT_MISSING),
            ]
            demo_order["status"] = ORDER_PARTIAL
            demo_order["status_code"] = "partial"
            demo_order["batches"] = [{
                "batch_no": "BL-XP-01-B1",
                "批次号": "BL-XP-01-B1",
                "delivery_no": "JF-BL-XP-01-B1",
                "交付单号": "JF-BL-XP-01-B1",
                "created_at": "2026-11-26T08:04:40+08:00",
                "created_at_cn": "2026-11-26 08:04:40",
                "window_count": 1,
                "窗口数": 1,
                "windows": ["08:00"],
                "receipt_nos": [seg_rc["receipt_no"]],
                "回单号": [seg_rc["receipt_no"]],
                "file_name": "BL-XP-01-B1.csv",
            }]
            self.orders.append(demo_order)
            return {"ok": True, "message": "差额补领演示数据已重置"}

    # ======================== 查询辅助 ========================

    def get_round(self, round_no: str) -> dict[str, Any] | None:
        target = str(round_no or "").strip()
        for round_row in self.rounds:
            if round_row["round_no"] == target or round_row.get("轮次") == target:
                return round_row
        return None

    def _match_window(self, round_no: Any = None, window: Any = None,
                      source: Any = None, window_id: Any = None,
                      delivery_no: Any = None) -> list[dict[str, Any]]:
        window_label = _norm_window(window)
        matches: list[dict[str, Any]] = []
        for row in self.windows:
            if window_id and str(row.get("id")) == str(window_id):
                matches.append(row)
                continue
            if round_no and row["round_no"] != str(round_no):
                continue
            if window_label and row["window"] != window_label:
                continue
            if source and str(source) not in ("*",) and row.get("source") != str(source):
                continue
            if delivery_no and row.get("delivery_no") != str(delivery_no):
                continue
            matches.append(row)
        return matches

    def list_rounds(self) -> list[dict[str, Any]]:
        """轮次清单，附带每轮欠件/已签/片段未生成计数。"""
        result = []
        for round_row in self.rounds:
            item = dict(round_row)
            windows = [w for w in self.windows if w["round_no"] == round_row["round_no"]]
            owed = [w for w in windows if not w["signed"]]
            item["window_count"] = len(windows)
            item["窗口数"] = len(windows)
            item["owed_count"] = len(owed)
            item["欠件数"] = len(owed)
            item["signed_count"] = len(windows) - len(owed)
            item["已签收数"] = item["signed_count"]
            item["fragment_missing_count"] = sum(
                1 for w in owed if not w["fragment_ready"])
            item["片段未生成数"] = item["fragment_missing_count"]
            result.append(item)
        return result

    def list_windows(self, round_no: str | None = None,
                     source: str | None = None,
                     only_owed: bool = False,
                     only_missing: bool = False,
                     signed: bool | None = None) -> list[dict[str, Any]]:
        rows = list(self.windows)
        if round_no:
            rows = [w for w in rows if w["round_no"] == str(round_no)]
        if source:
            rows = [w for w in rows if w.get("source") == str(source)]
        if only_owed or only_missing:
            rows = [w for w in rows if not w["signed"]]
        if signed is True:
            rows = [w for w in rows if w["signed"]]
        elif signed is False and not (only_owed or only_missing):
            rows = [w for w in rows if not w["signed"]]
        return [dict(w) for w in rows]

    def list_owed_windows(self, round_no: str | None = None,
                          source: str | None = None) -> list[dict[str, Any]]:
        return self.list_windows(round_no=round_no, source=source, only_owed=True)

    def reconciliation_board(self, round_no: str | None = None) -> dict[str, Any]:
        """工作台签收对账看板：轮次 + 当前轮窗口 + 补领单。"""
        rounds = self.list_rounds()
        active_round = round_no or (rounds[0]["round_no"] if rounds else None)
        windows = self.list_windows(round_no=active_round) if active_round else []
        return {
            "ok": True,
            "active_round": active_round,
            "当前轮次": active_round,
            "rounds": rounds,
            "轮次": rounds,
            "windows": windows,
            "窗口": windows,
            "owed_windows": [w for w in windows if not w["signed"]],
            "本轮尚缺": [w["window"] for w in windows if not w["signed"]],
            "claim_orders": self.list_orders(),
            "补领单": self.list_orders(),
        }

    # ======================== 签收 / 回单 ========================

    def sign(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """登记一笔签收（可能是预览后才返回的迟到签收）。

        支持 ``sign(round_no, window)``、``sign({...})`` 与关键字参数。
        签收只冲销 ``(轮次, 来源, 窗口)`` 完全对应的欠件。
        """
        with self._lock:
            payload = self._payload_from_args(args, kwargs)
            round_no = _first(payload, "round_no", "round", "轮次", "round_id", "R")
            window = _first(payload, "window", "minute", "窗口", "window_minute", "time")
            source = _first(payload, "source", "来源", "source_code", default=None)
            window_id = _first(payload, "window_id", "id", "wid", default=None)
            delivery_no = _first(payload, "delivery_no", "delivery", "交付单号",
                                 "原交付单号", default=None)
            receipt_no_in = _first(payload, "receipt_no", "回单号", default=None)

            matches = self._match_window(
                round_no=round_no, window=window, source=source,
                window_id=window_id, delivery_no=delivery_no)
            if not matches:
                return {
                    "ok": False,
                    "message": f"没有找到与 轮次={round_no} 来源={source} 窗口={window} 对应的欠件",
                    "code": "window_not_found",
                }

            created: list[dict[str, Any]] = []
            for row in matches:
                if row["signed"] and row.get("receipt_no"):
                    existing = self._find_receipt(row["receipt_no"])
                    created.append(existing or {"receipt_no": row["receipt_no"]})
                    continue
                self._receipt_seq += 1
                receipt_no = receipt_no_in or f"HD-{self._receipt_seq:04d}"
                signed_at = _now()
                receipt = {
                    "receipt_no": receipt_no,
                    "回单号": receipt_no,
                    "round_no": row["round_no"],
                    "轮次": row["round_no"],
                    "source": row["source"],
                    "来源": row["source"],
                    "window": row["window"],
                    "窗口": row["window"],
                    "delivery_no": row["delivery_no"],
                    "交付单号": row["delivery_no"],
                    "delivery_kind": "original",
                    "交付类型": "原交付",
                    "order_no": "",
                    "补领单号": "",
                    "batch_no": "",
                    "补领批次": "",
                    "signed_at": signed_at,
                    "签收时间": signed_at,
                    "late": bool(_first(payload, "late", "迟到", default=True)),
                }
                self.receipts.append(receipt)
                row["signed"] = True
                row["已签收"] = True
                row["sign_status"] = "已签收"
                row["签收状态"] = "已签收"
                row["receipt_no"] = receipt_no
                row["回单号"] = receipt_no
                row["signed_at"] = signed_at
                row["签收时间"] = signed_at
                created.append(receipt)

            target = matches[0]
            return {
                "ok": True,
                "message": (
                    f"{target['round_no']} 窗口 {target['window']} 已签收，"
                    f"回单 {target['receipt_no']}（原交付 {target['delivery_no']}）"),
                "receipt": created[0] if len(created) == 1 else created,
                "回单": created[0] if len(created) == 1 else created,
                "receipts": created,
                "entry": created[0] if len(created) == 1 else created,
                "window": dict(target),
                "冲销欠件": {
                    "round_no": target["round_no"], "source": target["source"],
                    "window": target["window"],
                    "delivery_no": target["delivery_no"],
                    "receipt_no": target["receipt_no"],
                },
            }

    def _find_receipt(self, receipt_no: str) -> dict[str, Any] | None:
        for receipt in self.receipts:
            if receipt["receipt_no"] == receipt_no:
                return receipt
        return None

    # ======================== 补领单：创建 ========================

    @staticmethod
    def _payload_from_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
        if args and isinstance(args[0], dict):
            payload = dict(args[0])
            payload.update(kwargs)
            return payload
        if args:
            # 常见位置参数形态：(round_no, windows) 或 (order_ref,)
            payload = dict(kwargs)
            if len(args) >= 1 and "round_no" not in payload and "order_ref" not in payload:
                first = args[0]
                if isinstance(first, (list, tuple)):
                    payload.setdefault("items", first)
                else:
                    payload.setdefault("round_no", first)
            if len(args) >= 2:
                payload.setdefault("windows", args[1])
            return payload
        return dict(kwargs)

    def _new_order_record(self, *, order_id: int, order_no: str,
                          round_no: str = "", source: str = "",
                          recipient: str = "", title: str = "") -> dict[str, Any]:
        now = _now()
        return {
            "id": order_id,
            "order_id": order_id,
            "order_no": order_no,
            "补领单号": order_no,
            "单号": order_no,
            "title": title or f"{round_no} 轮差额补领单",
            "标题": title or f"{round_no} 轮差额补领单",
            "kind": "差额补领单",
            "单据类型": "差额补领单",
            "round_no": round_no,
            "轮次": round_no,
            "source": source,
            "来源": source,
            "recipient": recipient or "接收方 · 数据对账组",
            "接收方": recipient or "接收方 · 数据对账组",
            "status": ORDER_OPEN,
            "status_code": "open",
            "单据状态": ORDER_OPEN,
            "created_at": now,
            "创建时间": now,
            "updated_at": now,
            "更新时间": now,
            "lines": [],
            "明细": [],
            "batches": [],
            "补领批次": [],
            "receipts": [],
            "回单列表": [],
            "preview": None,
        }

    def _make_line(self, *, round_no: str, source: str, window: str,
                   state: str = LINE_PENDING,
                   receipt: dict[str, Any] | None = None,
                   batch_no: str = "", delivery_no: str = "",
                   delivered_at: str = "") -> dict[str, Any]:
        code = _LINE_CODE.get(state, "pending")
        receipt_no = (receipt or {}).get("receipt_no")
        original_delivery = ""
        original_receipt = ""
        if state == LINE_COVERED and receipt is not None:
            original_delivery = receipt.get("delivery_no", "")
            original_receipt = receipt.get("receipt_no", "")
        line = {
            "line_id": f"L-{round_no}-{window.replace(':', '')}",
            "round_no": round_no,
            "轮次": round_no,
            "source": source,
            "来源": source,
            "window": window,
            "窗口": window,
            "minute": window,
            "state": state,
            "状态": state,
            "status": state,
            "status_code": code,
            "state_code": code,
            "pending": state == LINE_PENDING,
            "delivered": state == LINE_DELIVERED,
            "covered": state == LINE_COVERED,
            "fragment_missing": state == LINE_FRAGMENT_MISSING,
            "receipt_no": receipt_no if state == LINE_DELIVERED else None,
            "补领回单号": receipt_no if state == LINE_DELIVERED else None,
            "batch_no": batch_no,
            "补领批次": batch_no,
            "delivery_no": delivery_no if state == LINE_DELIVERED else "",
            "补领交付单号": delivery_no if state == LINE_DELIVERED else "",
            "delivered_at": delivered_at if state == LINE_DELIVERED else "",
            "补发时间": delivered_at if state == LINE_DELIVERED else "",
            # 迟到签收的归属：从哪笔原交付、哪张回单冲销。
            "original_delivery_no": original_delivery,
            "原交付单号": original_delivery,
            "source_delivery_no": original_delivery,
            "original_receipt_no": original_receipt if state == LINE_COVERED else "",
            "原回单号": original_receipt if state == LINE_COVERED else "",
            "original_receipt": dict(receipt) if state == LINE_COVERED and receipt else None,
            "签收时间": (receipt or {}).get("signed_at", "") if state == LINE_COVERED else "",
            "signed_at": (receipt or {}).get("signed_at", "") if state == LINE_COVERED else "",
        }
        window_row = self._match_window(
            round_no=round_no, window=window, source=source)
        if window_row:
            w = window_row[0]
            line["fragment_ready"] = w["fragment_ready"]
            line["片段状态"] = w["片段状态"]
            line["fragment_name"] = w["fragment_name"]
            line["聚合值"] = w.get("聚合值")
            line["value"] = w.get("value")
        return line

    def _extract_refs(self, payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        """从各种宽松入参里解析 ``(round_no, refs)``。

        refs 为 ``[{"round_no","source","window"}]``。
        """
        round_no = _first(payload, "round_no", "round", "轮次", "round_id", "R", default="")
        source = _first(payload, "source", "来源", default="")
        raw_windows = _first(
            payload, "windows", "window_list", "窗口", "selected_windows",
            "checked_windows", "window_minutes", "minutes", "chosen_windows",
            "window_times", default=None)
        raw_items = _first(
            payload, "items", "window_ids", "refs", "selection", "selected",
            "明细", "selected_items", "chosen", "targets", default=None)

        refs: list[dict[str, Any]] = []

        def add_ref(value: Any, item_source: Any = None, item_round: Any = None) -> None:
            if isinstance(value, dict):
                r = _first(value, "round_no", "round", "轮次", "round_id",
                           default=item_round or round_no)
                s = _first(value, "source", "来源", default=item_source or source)
                w = _first(value, "window", "minute", "窗口", "window_id", "id",
                           default=None)
                if w and not _norm_window(w) and str(w).startswith("WIN-"):
                    matched = self._match_window(window_id=w)
                    if matched:
                        refs.append({
                            "round_no": matched[0]["round_no"],
                            "source": matched[0]["source"],
                            "window": matched[0]["window"]})
                        return
                refs.append({"round_no": str(r or ""), "source": str(s or ""),
                             "window": _norm_window(w)})
            else:
                refs.append({"round_no": str(item_round or round_no or ""),
                             "source": str(item_source or source or ""),
                             "window": _norm_window(value)})

        if isinstance(raw_items, list):
            for item in raw_items:
                add_ref(item)
        if raw_windows is not None:
            if isinstance(raw_windows, str):
                raw_windows = [w for w in raw_windows.split(",") if w.strip()]
            if isinstance(raw_windows, list):
                for value in raw_windows:
                    add_ref(value)
        # 去重保序
        seen: set[tuple[str, str, str]] = set()
        unique: list[dict[str, Any]] = []
        for ref in refs:
            key = (ref["round_no"], ref["source"], ref["window"])
            if key in seen or not ref["window"]:
                continue
            seen.add(key)
            unique.append(ref)
        return str(round_no or ""), unique

    def create_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """勾选本轮尚缺窗口，新建一张差额补领单。"""
        with self._lock:
            payload = self._payload_from_args(args, kwargs)
            round_no, refs = self._extract_refs(payload)

            # 没有显式勾选时，默认带上该轮全部尚缺窗口。
            if not refs and round_no:
                refs = [
                    {"round_no": w["round_no"], "source": w["source"],
                     "window": w["window"]}
                    for w in self.list_owed_windows(round_no=round_no)
                ]
            if not refs:
                return {"ok": False, "message": "请至少勾选一个本轮尚缺的窗口"}

            # 以第一个引用补全 round_no；逐行校验窗口真实存在。
            resolved: list[dict[str, Any]] = []
            errors: list[str] = []
            for ref in refs:
                r_no = ref["round_no"] or round_no
                matches = self._match_window(
                    round_no=r_no, window=ref["window"],
                    source=ref["source"] or None)
                if not matches and not ref["source"]:
                    matches = self._match_window(
                        round_no=r_no, window=ref["window"])
                if not matches:
                    errors.append(f"{r_no}/{ref['window']}")
                    continue
                w = matches[0]
                resolved.append({
                    "round_no": w["round_no"], "source": w["source"],
                    "window": w["window"]})
            if errors:
                return {"ok": False,
                        "message": "以下窗口不存在：" + "、".join(errors)}

            rounds_in_order = {r["round_no"] for r in resolved}
            order_round = round_no or (
                next(iter(rounds_in_order)) if len(rounds_in_order) == 1
                else "MULTI")
            sources = {r["source"] for r in resolved if r["source"]}
            order_source = next(iter(sources)) if len(sources) == 1 else (
                _first(payload, "source", "来源", default="") or "MULTI")

            self._order_seq += 1
            order_id = _first(payload, "id", default=self._order_seq)
            order_no = _first(payload, "order_no", "补领单号", "单号",
                              default=f"BL-{self._order_seq:04d}")
            order = self._new_order_record(
                order_id=int(order_id) if str(order_id).isdigit() else self._order_seq,
                order_no=str(order_no), round_no=order_round,
                source=str(order_source),
                recipient=str(_first(payload, "recipient", "接收方", default="")),
                title=str(_first(payload, "title", "标题", default="")))

            lines: list[dict[str, Any]] = []
            for ref in resolved:
                w = self._match_window(**ref)[0]
                if w["signed"] and w.get("receipt_no"):
                    receipt = self._find_receipt(w["receipt_no"])
                    if receipt and receipt.get("delivery_kind") == "original":
                        line = self._make_line(
                            round_no=ref["round_no"], source=ref["source"],
                            window=ref["window"], state=LINE_COVERED,
                            receipt=receipt)
                    else:
                        line = self._make_line(
                            round_no=ref["round_no"], source=ref["source"],
                            window=ref["window"], state=LINE_DELIVERED,
                            receipt=receipt,
                            batch_no=(receipt or {}).get("batch_no", ""),
                            delivery_no=(receipt or {}).get("delivery_no", ""),
                            delivered_at=(receipt or {}).get("signed_at", ""))
                elif not w["fragment_ready"]:
                    line = self._make_line(
                        round_no=ref["round_no"], source=ref["source"],
                        window=ref["window"], state=LINE_FRAGMENT_MISSING)
                else:
                    line = self._make_line(
                        round_no=ref["round_no"], source=ref["source"],
                        window=ref["window"], state=LINE_PENDING)
                lines.append(line)
            order["lines"] = lines
            order["明细"] = lines
            self._refresh_order_status(order)
            self.orders.append(order)
            return {
                "ok": True,
                "message": f"差额补领单 {order['order_no']} 已创建，共勾选 {len(lines)} 个窗口",
                "order": dict(order),
                "entry": dict(order),
                "order_no": order["order_no"],
                "id": order["id"],
            }

    # ======================== 补领单：查询 / 重开 ========================

    def _resolve_order(self, ref: Any) -> dict[str, Any] | None:
        if ref is None:
            return None
        if isinstance(ref, dict):
            ref = _first(ref, "order_ref", "order_no", "id", "order_id",
                         default=None)
        text = str(ref).strip()
        for order in self.orders:
            if str(order["id"]) == text or order["order_no"] == text \
                    or order.get("补领单号") == text:
                return order
        return None

    def list_orders(self) -> list[dict[str, Any]]:
        return [dict(order) for order in self.orders]

    def get_order(self, ref: Any = None, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        if ref is None:
            ref = _first(kwargs, "order_ref", "order_no", "id", "order_id",
                          default=None)
        order = self._resolve_order(ref)
        return dict(order) if order is not None else None

    def open_order(self, ref: Any = None, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """重新打开补领单：返回完整明细与每笔归属/回单。"""
        order = self.get_order(ref, *args, **kwargs)
        if order is None:
            return {"ok": False, "message": f"差额补领单 {ref} 不存在"}
        order["ok"] = True
        order["message"] = f"已打开差额补领单 {order['order_no']}"
        return order

    # ======================== 预览 ========================

    def _reevaluate_line(self, order: dict[str, Any], line: dict[str, Any]) -> dict[str, Any]:
        """按当前欠件/回单状态重新判定一行（不相信创建或预览时的快照）。"""
        # 已经随本单补发并持有回单的行：永久保留自己的回单，不重复交付。
        if line["state"] == LINE_DELIVERED and line.get("receipt_no"):
            return line
        matches = self._match_window(
            round_no=line["round_no"], window=line["window"],
            source=line["source"] or None)
        if not matches:
            return line
        w = matches[0]
        if w["signed"] and w.get("receipt_no"):
            receipt = self._find_receipt(w["receipt_no"])
            if receipt and receipt.get("delivery_kind") == "original":
                line.update(self._make_line(
                    round_no=line["round_no"], source=line["source"],
                    window=line["window"], state=LINE_COVERED, receipt=receipt))
                return line
            if receipt and receipt.get("delivery_kind") == "claim":
                # 已由某笔补领交付签收（可能是本单其它批次），保留其回单归属。
                line.update(self._make_line(
                    round_no=line["round_no"], source=line["source"],
                    window=line["window"], state=LINE_DELIVERED,
                    receipt=receipt, batch_no=receipt.get("batch_no", ""),
                    delivery_no=receipt.get("delivery_no", ""),
                    delivered_at=receipt.get("signed_at", "")))
                return line
        if not w["fragment_ready"]:
            line.update(self._make_line(
                round_no=line["round_no"], source=line["source"],
                window=line["window"], state=LINE_FRAGMENT_MISSING))
            return line
        # 仍欠且片段已生成。
        if line["state"] != LINE_PENDING:
            line.update(self._make_line(
                round_no=line["round_no"], source=line["source"],
                window=line["window"], state=LINE_PENDING))
        return line

    def preview_order(self, ref: Any = None, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """预览本轮补领差额；预览后到达的签收在真正领取时仍会被重新核对。"""
        with self._lock:
            if ref is None:
                payload = self._payload_from_args(args, kwargs)
                ref = _first(payload, "order_ref", "order_no", "id", "order_id")
            order = self._resolve_order(ref)
            if order is None:
                return {"ok": False, "message": f"差额补领单 {ref} 不存在"}

            deliverable: list[dict[str, Any]] = []
            covered: list[dict[str, Any]] = []
            missing_fragment: list[dict[str, Any]] = []
            already_delivered: list[dict[str, Any]] = []
            for line in order["lines"]:
                self._reevaluate_line(order, line)
                bucket = {
                    LINE_PENDING: deliverable,
                    LINE_COVERED: covered,
                    LINE_FRAGMENT_MISSING: missing_fragment,
                    LINE_DELIVERED: already_delivered,
                }[line["state"]]
                bucket.append(dict(line))

            preview = {
                "previewed_at": _now(),
                "预览时间": _now(),
                "deliverable": deliverable,
                "本次将补发": deliverable,
                "deliverable_windows": [l["window"] for l in deliverable],
                "补发窗口": [l["window"] for l in deliverable],
                "covered_by_late_receipt": covered,
                "预览前后已签收无需补发": covered,
                "covered_windows": [l["window"] for l in covered],
                "已签收跳过窗口": [l["window"] for l in covered],
                "fragment_missing": missing_fragment,
                "片段未生成": missing_fragment,
                "fragment_missing_windows": [l["window"] for l in missing_fragment],
                "already_delivered": already_delivered,
                "已补发保留回单": already_delivered,
                "already_delivered_windows": [l["window"] for l in already_delivered],
            }
            order["preview"] = preview
            order["updated_at"] = _now()
            return {
                "ok": True,
                "message": (
                    f"预览：{len(deliverable)} 窗待补发，"
                    f"{len(covered)} 窗已由原交付签收，"
                    f"{len(missing_fragment)} 窗片段未生成"),
                "order": dict(order),
                "preview": preview,
            }

    # ======================== 领取 / 续领 ========================

    def _refresh_order_status(self, order: dict[str, Any]) -> None:
        states = [line["state"] for line in order["lines"]]
        if states and all(s in (LINE_DELIVERED, LINE_COVERED) for s in states):
            order["status"] = ORDER_COMPLETED
            order["status_code"] = "completed"
        elif LINE_DELIVERED in states and LINE_PENDING not in states \
                and LINE_COVERED not in states \
                and all(s in (LINE_DELIVERED, LINE_FRAGMENT_MISSING) for s in states):
            order["status"] = ORDER_PARTIAL
            order["status_code"] = "partial"
        elif LINE_DELIVERED in states and any(
                s in (LINE_FRAGMENT_MISSING, LINE_PENDING) for s in states):
            order["status"] = ORDER_PARTIAL
            order["status_code"] = "partial"
        else:
            order["status"] = ORDER_OPEN
            order["status_code"] = "open"
        order["单据状态"] = order["status"]
        order["updated_at"] = _now()
        order["更新时间"] = order["updated_at"]
        order["明细"] = order["lines"]

    def claim_order(self, ref: Any = None, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """真正领取/批量导出。

        关键并发语义：领取瞬间逐行重新核对签收状态——预览之后才到的签收同样
        有效；已签窗口（无论原交付迟到回单还是本单已交付回单）绝不重复交付；
        片段未生成的行保留待续领，不影响其它片段交付。
        """
        with self._lock:
            payload = self._payload_from_args(args, kwargs)
            if ref is None or isinstance(ref, dict):
                if isinstance(ref, dict):
                    payload = ref
                ref = _first(payload, "order_ref", "order_no", "id", "order_id")
            only_lines = _first(
                payload, "line_ids", "lines", "windows", "only",
                "window_ids", "selected_windows", "refs", "items",
                "claim_lines", default=None)
            order = self._resolve_order(ref)
            if order is None:
                return {"ok": False, "message": f"差额补领单 {ref} 不存在"}

            only_set: set[str] | None = None
            if only_lines is not None:
                if isinstance(only_lines, str):
                    only_lines = [w.strip() for w in only_lines.split(",") if w.strip()]
                normalized: set[str] = set()
                for x in only_lines or []:
                    if isinstance(x, dict):
                        value = _first(x, "window", "minute", "窗口",
                                       "line_id", "id", default="")
                    else:
                        value = x
                    value = str(value)
                    normalized.add(value if value.startswith("L-") else _norm_window(value))
                only_set = normalized

            delivered_lines: list[dict[str, Any]] = []
            covered_lines: list[dict[str, Any]] = []
            missing_lines: list[dict[str, Any]] = []
            kept_lines: list[dict[str, Any]] = []

            for line in order["lines"]:
                if only_set is not None and not (
                        line["window"] in only_set or line["line_id"] in only_set):
                    continue

                before_state = line["state"]
                self._reevaluate_line(order, line)

                if line["state"] == LINE_DELIVERED and before_state == LINE_DELIVERED \
                        and line.get("receipt_no"):
                    # 之前批次已交付：保留原回单，不重复交付。
                    kept_lines.append(dict(line))
                    continue
                if line["state"] == LINE_COVERED:
                    covered_lines.append(dict(line))
                    continue
                if line["state"] == LINE_FRAGMENT_MISSING:
                    missing_lines.append(dict(line))
                    continue
                if line["state"] == LINE_DELIVERED:
                    kept_lines.append(dict(line))
                    continue

                # LINE_PENDING -> 本次实际补发
                window_rows = self._match_window(
                    round_no=line["round_no"], window=line["window"],
                    source=line["source"] or None)
                w = window_rows[0] if window_rows else None
                if w is not None and w["signed"]:
                    # 双保险：再查一次签收。
                    receipt = self._find_receipt(w.get("receipt_no") or "")
                    if receipt and receipt.get("delivery_kind") == "original":
                        new_line = self._make_line(
                            round_no=line["round_no"], source=line["source"],
                            window=line["window"], state=LINE_COVERED, receipt=receipt)
                        line.clear()
                        line.update(new_line)
                        covered_lines.append(dict(line))
                        continue
                if w is not None and not w["fragment_ready"]:
                    line.update(self._make_line(
                        round_no=line["round_no"], source=line["source"],
                        window=line["window"], state=LINE_FRAGMENT_MISSING))
                    missing_lines.append(dict(line))
                    continue

                # ---- 实际交付该片段：批次 + 交付单 + 独立回单 ----
                self._batch_seq += 1
                batch_no = f"{order['order_no']}-B{len(order['batches']) + 1}"
                delivery_no = f"JF-{batch_no}"
                signed_at = _now()
                self._receipt_seq += 1
                receipt_no = f"HD-{self._receipt_seq:04d}"
                receipt = {
                    "receipt_no": receipt_no,
                    "回单号": receipt_no,
                    "round_no": line["round_no"],
                    "轮次": line["round_no"],
                    "source": line["source"],
                    "来源": line["source"],
                    "window": line["window"],
                    "窗口": line["window"],
                    "delivery_no": delivery_no,
                    "交付单号": delivery_no,
                    "delivery_kind": "claim",
                    "交付类型": "补领交付",
                    "order_no": order["order_no"],
                    "补领单号": order["order_no"],
                    "batch_no": batch_no,
                    "补领批次": batch_no,
                    "signed_at": signed_at,
                    "签收时间": signed_at,
                }
                self.receipts.append(receipt)
                order["receipts"].append(receipt)
                order["回单列表"] = order["receipts"]

                if w is not None:
                    w["signed"] = True
                    w["已签收"] = True
                    w["sign_status"] = "已签收"
                    w["签收状态"] = "已签收"
                    w["receipt_no"] = receipt_no
                    w["回单号"] = receipt_no
                    w["signed_at"] = signed_at
                    w["签收时间"] = signed_at

                new_line = self._make_line(
                    round_no=line["round_no"], source=line["source"],
                    window=line["window"], state=LINE_DELIVERED,
                    receipt=receipt, batch_no=batch_no,
                    delivery_no=delivery_no, delivered_at=signed_at)
                line.clear()
                line.update(new_line)
                delivered_lines.append(dict(line))

            # 汇总本次批次（仅当确实有新片段交付）。
            batch: dict[str, Any] | None = None
            csv_text = ""
            if delivered_lines:
                batch_no = delivered_lines[0]["batch_no"]
                batch = {
                    "batch_no": batch_no,
                    "批次号": batch_no,
                    "delivery_no": delivered_lines[0]["delivery_no"],
                    "交付单号": delivered_lines[0]["delivery_no"],
                    "created_at": _now(),
                    "windows": [l["window"] for l in delivered_lines],
                    "window_count": len(delivered_lines),
                    "窗口数": len(delivered_lines),
                    "receipt_nos": [l["receipt_no"] for l in delivered_lines],
                    "回单号": [l["receipt_no"] for l in delivered_lines],
                    "file_name": f"{batch_no}.csv",
                }
                order["batches"].append(batch)
                order["补领批次"] = order["batches"]
                csv_text = self._build_csv(order, batch_no)

                # 在「批量导出」模块留一笔真实导出任务，延续
                # aggregate_sink.dispatch_to_batch_export 的跨模块归属约定。
                try:
                    export_rows = store.rows("batch_export")
                    export_id = max((int(r.get("id", 0)) for r in export_rows), default=0) + 1
                    data_row_count = sum(
                        len(self._fragment_rows(l)) for l in delivered_lines)
                    export_task = {
                        "id": export_id,
                        "任务编号": f"EXP-CLAIM-{export_id:04d}",
                        "设备范围": order.get("source") or "聚合分发接收方",
                        "测点列表": "、".join(l["window"] for l in delivered_lines),
                        "时间范围": f"{order['round_no']} 轮补领 {batch_no}",
                        "导出格式": "CSV",
                        "数据行数": str(data_row_count),
                        "文件大小": f"{max(len(csv_text.encode('utf-8')), 1)}B",
                        "导出状态": "已完成",
                        "status": "已完成",
                        "pending": False,
                        "abnormal": False,
                        "补领单号": order["order_no"],
                        "补领批次": batch_no,
                        "归属": f"差额补领单 {order['order_no']} / {batch_no}",
                        "file_name": batch["file_name"],
                    }
                    export_rows.append(export_task)
                    batch["export_task"] = export_task
                    batch["export_task_no"] = export_task["任务编号"]
                except Exception:
                    # 跨模块登记失败不影响补领主流程。
                    pass

            self._refresh_order_status(order)

            delivered_windows = [l["window"] for l in delivered_lines]
            covered_windows = [l["window"] for l in covered_lines]
            missing_windows = [l["window"] for l in missing_lines]
            kept_windows = [l["window"] for l in kept_lines]

            if delivered_lines:
                message = f"领取成功：实际补发 {delivered_windows}"
                if covered_windows:
                    message += f"；{covered_windows} 因已被原交付签收而跳过"
                if missing_windows:
                    message += f"；{missing_windows} 片段未生成，可后续续领"
            elif covered_windows and not missing_windows:
                message = f"所选窗口均已签收，无需重复补发：{covered_windows}"
            elif missing_windows:
                message = f"暂无可领取片段，未生成窗口：{missing_windows}"
            else:
                message = "没有需要补发的窗口"

            return {
                "ok": True,
                "message": message,
                "order": dict(order),
                "entry": dict(order),
                "order_no": order["order_no"],
                "batch": batch,
                "批次": batch,
                "batch_no": (batch or {}).get("batch_no", ""),
                "export_task": (batch or {}).get("export_task"),
                "export_task_no": (batch or {}).get("export_task_no", ""),
                "csv": csv_text,
                "file_name": (batch or {}).get("file_name", ""),
                "delivered": delivered_lines,
                "delivered_lines": delivered_lines,
                "delivered_windows": delivered_windows,
                "补发窗口": delivered_windows,
                "reissued_windows": delivered_windows,
                "actual_fragments": delivered_lines,
                "实际片段": delivered_lines,
                "covered_by_late_receipt": covered_lines,
                "covered_lines": covered_lines,
                "covered_windows": covered_windows,
                "signed_skipped_windows": covered_windows,
                "已签收跳过窗口": covered_windows,
                "kept_delivered": kept_lines,
                "already_delivered_windows": kept_windows,
                "保留回单窗口": kept_windows,
                "fragment_missing": missing_lines,
                "fragment_missing_windows": missing_windows,
                "pending_fragment_windows": missing_windows,
                "片段未生成窗口": missing_windows,
                "remaining_open": order["status"] != ORDER_COMPLETED,
                "still_open": order["status"] != ORDER_COMPLETED,
            }

    def claim_line(self, order_ref: Any, line_ref: Any,
                   **kwargs: Any) -> dict[str, Any]:
        """续领单段：只领取指定行（窗口或 line_id）。"""
        return self.claim_order(order_ref, lines=[line_ref], **kwargs)

    def continue_order(self, ref: Any = None, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """续领：重新执行整单领取，已交付/已签收行自动保留跳过。"""
        return self.claim_order(ref, *args, **kwargs)

    # ======================== 片段生成（模拟） ========================

    def generate_fragment(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """模拟离线片段生成完成：把指定欠件窗口的片段置为已生成。"""
        with self._lock:
            payload = self._payload_from_args(args, kwargs)
            round_no = _first(payload, "round_no", "round", "轮次", default=None)
            window = _first(payload, "window", "窗口", "minute", default=None)
            source = _first(payload, "source", "来源", default=None)
            window_id = _first(payload, "window_id", "id", default=None)
            matches = self._match_window(
                round_no=round_no, window=window, source=source,
                window_id=window_id)
            if not matches:
                return {"ok": False,
                        "message": f"没有找到 轮次={round_no} 窗口={window} 的片段"}
            for row in matches:
                row["fragment_ready"] = True
                row["片段已生成"] = True
                row["fragment_status"] = "已生成"
                row["片段状态"] = "已生成"
            target = matches[0]
            return {"ok": True,
                    "message": f"{target['round_no']} {target['window']} 片段已生成",
                    "window": dict(target)}

    def mark_fragment_missing(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """把窗口片段标记为尚未生成（用于构造/模拟缺段续领场景）。"""
        with self._lock:
            payload = self._payload_from_args(args, kwargs)
            matches = self._match_window(
                round_no=_first(payload, "round_no", "round", "轮次", default=None),
                window=_first(payload, "window", "窗口", "minute", default=None),
                source=_first(payload, "source", "来源", default=None),
                window_id=_first(payload, "window_id", "id", default=None))
            if not matches:
                return {"ok": False, "message": "没有找到对应窗口片段"}
            for row in matches:
                row["fragment_ready"] = False
                row["片段已生成"] = False
                row["fragment_status"] = "未生成"
                row["片段状态"] = "未生成"
            return {"ok": True,
                    "message": f"{matches[0]['round_no']} {matches[0]['window']} 片段已置为未生成",
                    "window": dict(matches[0])}

    # ======================== 导出 CSV ========================

    def _fragment_rows(self, line: dict[str, Any]) -> list[dict[str, str]]:
        """构造一个窗口片段里的实际数据行（确定性伪数据）。"""
        seed_num = sum(ord(ch) for ch in f"{line['round_no']}{line['window']}")
        rows = []
        for idx in range(3):
            device = f"DEVI-{(seed_num + idx) % 6 + 1:04d}"
            base = float(str(line.get("value") or "0").replace(",", "") or 0)
            value = round(base + idx * 0.3 + (seed_num % 7) * 0.01, 2)
            hh, mm = line["window"].split(":")
            minute = int(mm) + idx
            hour = int(hh) + minute // 60
            minute %= 60
            ts = f"2026-11-26T{hour:02d}:{minute:02d}:00+08:00"
            rows.append({
                "轮次": line["round_no"],
                "来源": line["source"],
                "窗口": line["window"],
                "数据时间": ts,
                "设备编号": device,
                "测点编号": "TS_P-0001",
                "聚合值": str(value),
                "归属补领单": line.get("order_no", ""),
                "补领批次": line.get("batch_no", ""),
                "回单号": line.get("receipt_no", ""),
            })
        return rows

    def _build_csv(self, order: dict[str, Any], batch_no: str | None = None) -> str:
        import csv
        import io

        headers = ["轮次", "来源", "窗口", "数据时间", "设备编号", "测点编号",
                   "聚合值", "归属补领单", "补领批次", "回单号"]
        buffer = io.StringIO()
        buffer.write("\ufeff")  # CSV BOM，Excel 打开中文不乱码
        writer = csv.DictWriter(buffer, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        for line in order["lines"]:
            if line["state"] != LINE_DELIVERED:
                continue
            if batch_no and line.get("batch_no") != batch_no:
                continue
            for row in self._fragment_rows(line):
                row["归属补领单"] = order["order_no"]
                writer.writerow(row)
        return buffer.getvalue()

    def export_csv(self, ref: Any = None, batch_no: str | None = None,
                   *args: Any, **kwargs: Any) -> dict[str, Any]:
        """导出补领单片段。指定 batch_no 时只导该次补领交付的实际片段。"""
        order = self._resolve_order(ref if ref is not None else kwargs.get("order_ref"))
        if order is None:
            return {"ok": False, "message": f"差额补领单 {ref} 不存在",
                    "csv": "", "file_name": ""}
        csv_text = self._build_csv(order, batch_no)
        if batch_no:
            stem = batch_no if batch_no.startswith(order["order_no"]) \
                else f"{order['order_no']}-{batch_no}"
            file_name = f"{stem}.csv"
        else:
            file_name = f"{order['order_no']}-all.csv"
        return {
            "ok": True,
            "csv": csv_text,
            "content": csv_text,
            "file_name": file_name,
            "media_type": "text/csv; charset=utf-8",
            "message": "补领片段已导出",
        }


# 进程内单例：路由与 AggregateSinkService 共用同一份状态。
claim_service = ClaimOrderService()

# 近义类型/单例别名，兼容不同命名习惯的导入。
ShortfallClaimService = ClaimOrderService
ShortfallClaimOrderService = ClaimOrderService
DifferenceClaimOrderService = ClaimOrderService
SupplementOrderService = ClaimOrderService
ReissueOrderService = ClaimOrderService
shortfall_claim_service = claim_service
claim_order_service = claim_service
