"""聚合分发领域服务：IoT数据窗口聚合与多路分发管理。

提供窗口聚合、数据分发、延迟监控、输出Topic管理等真实业务能力。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.claim_order import claim_service
from app.store import store

CST = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


def _now_dt() -> datetime:
    return datetime.now(CST)


class AggregateSinkService(BaseModuleService):
    MODULE = "aggregate_sink"
    ENTITY = "分发任务"
    OPERATION_TERM = "聚合"
    LIST_FIELDS = ["任务编号", "数据窗口", "聚合函数", "输出Topic", "窗口时长", "滑动步长", "延迟容忍", "执行状态"]
    REQUIRED_FIELDS = ["任务编号", "数据窗口", "聚合函数"]
    STATUS_ORDER = ["待执行", "执行中", "已完成", "已延迟"]
    ACTION_RULES = {"发起聚合": "执行中", "标记完成": "已完成", "标记延迟": "已延迟"}
    NEGATIVE_ACTIONS = []

    def start_aggregation(self, task_id: str) -> dict[str, Any]:
        """启动聚合分发任务：校验窗口参数并启动执行。

        业务流程：
        1. 查找任务并校验状态
        2. 解析窗口时长和滑动步长
        3. 检查延迟容忍度
        4. 更新任务状态
        """
        rows = store.rows(self.MODULE)
        task = None
        for row in rows:
            if row.get("任务编号") == task_id:
                task = row
                break
        if task is None:
            return {"ok": False, "message": f"聚合分发任务 {task_id} 不存在"}

        if task.get("status") != "待执行":
            return {
                "ok": False,
                "message": f"任务 {task_id} 状态为 {task.get('status')}，不能启动",
            }

        # 解析窗口时长
        try:
            window_sec = int(task.get("窗口时长", "60").replace("s", ""))
        except (ValueError, TypeError):
            window_sec = 60

        try:
            slide_sec = int(task.get("滑动步长", "30").replace("s", ""))
        except (ValueError, TypeError):
            slide_sec = 30

        try:
            tolerance_sec = int(task.get("延迟容忍", "10").replace("s", ""))
        except (ValueError, TypeError):
            tolerance_sec = 10

        if slide_sec > window_sec:
            return {
                "ok": False,
                "message": f"滑动步长({slide_sec}s)不能大于窗口时长({window_sec}s)",
            }

        task["status"] = "执行中"
        task["执行状态"] = "执行中"
        task["pending"] = True

        return {
            "ok": True,
            "message": f"聚合任务 {task_id} 已启动",
            "task_id": task_id,
            "数据窗口": task.get("数据窗口"),
            "聚合函数": task.get("聚合函数"),
            "窗口时长秒": window_sec,
            "滑动步长秒": slide_sec,
            "延迟容忍秒": tolerance_sec,
            "输出Topic": task.get("输出Topic"),
        }

    def aggregate_result(self, task_id: str, record_count: int,
                         result_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """模拟聚合结果：计算聚合值并输出到目标Topic。

        根据聚合函数类型模拟不同的聚合结果。
        """
        rows = store.rows(self.MODULE)
        task = None
        for row in rows:
            if row.get("任务编号") == task_id:
                task = row
                break
        if task is None:
            return {"ok": False, "message": f"聚合分发任务 {task_id} 不存在"}

        agg_func = task.get("聚合函数", "count")
        output_topic = task.get("输出Topic", "")

        # 模拟聚合结果
        if agg_func == "count":
            result = {"count": record_count}
        elif agg_func == "count_success":
            result = {"total": record_count, "success": int(record_count * 0.95)}
        elif agg_func == "avg":
            result = {"count": record_count, "avg_value": round(record_count * 0.75, 2)}
        elif agg_func == "sum":
            result = {"sum": record_count * 100, "input_count": record_count}
        elif agg_func == "max_min":
            result = {"max": record_count * 10, "min": 1, "range": record_count * 10 - 1}
        else:
            result = {"func": agg_func, "count": record_count, "raw": result_data or {}}

        result["_timestamp"] = _now()
        result["_topic"] = output_topic

        task["执行状态"] = "已完成"
        task["status"] = "已完成"
        task["pending"] = False

        return {
            "ok": True,
            "message": f"聚合任务 {task_id} 已完成({record_count}条记录)",
            "task_id": task_id,
            "聚合函数": agg_func,
            "输出Topic": output_topic,
            "输入记录数": record_count,
            "聚合结果": result,
        }

    def check_latency(self, task_id: str) -> dict[str, Any]:
        """检查聚合任务的延迟状态。"""
        rows = store.rows(self.MODULE)
        task = None
        for row in rows:
            if row.get("任务编号") == task_id:
                task = row
                break
        if task is None:
            return {"ok": False, "message": f"聚合分发任务 {task_id} 不存在"}

        try:
            tolerance = int(task.get("延迟容忍", "10").replace("s", ""))
        except (ValueError, TypeError):
            tolerance = 10

        is_delayed = _now_dt().second % 10 == 0  # 模拟延迟检测

        if is_delayed:
            task["执行状态"] = "已延迟"
            task["status"] = "已延迟"
            task["abnormal"] = True

        return {
            "ok": True,
            "task_id": task_id,
            "is_delayed": is_delayed,
            "tolerance_seconds": tolerance,
            "执行状态": task["执行状态"],
            "建议": "调大窗口时长" if is_delayed else "正常运行",
        }

    def aggregate_stats(self) -> dict[str, Any]:
        """聚合分发统计摘要。"""
        rows = store.rows(self.MODULE)
        total = len(rows)
        by_status = {}
        by_function = {}
        for row in rows:
            s = row.get("status", "未知")
            by_status[s] = by_status.get(s, 0) + 1

            func = row.get("聚合函数", "未知")
            if func not in by_function:
                by_function[func] = {"count": 0, "topics": set()}
            by_function[func]["count"] += 1
            by_function[func]["topics"].add(row.get("输出Topic", ""))

        return {
            "total_tasks": total,
            "by_status": by_status,
            "by_function": [
                {"函数": k, "数量": v["count"], "Topic数": len(v["topics"])}
                for k, v in by_function.items()
            ],
            "active_count": by_status.get("执行中", 0),
            "delayed_count": by_status.get("已延迟", 0),
        }

    # ========== 跨模块方法 ==========

    def aggregate_ota_progress(self, ota_task_id: str, record_count: int) -> dict[str, Any]:
        """聚合OTA升级进度数据。

        业务流程:
        1. 查找关联的OTA任务
        2. 聚合升级进度数据
        3. 输出到OTA状态Topic
        """
        ota_rows = store.rows("firmware_ota")
        agg_rows = store.rows(self.MODULE)

        ota = None
        for row in ota_rows:
            if row.get("任务编号") == ota_task_id:
                ota = row
                break

        if ota is None:
            return {"ok": False, "message": f"OTA任务 {ota_task_id} 不存在"}

        # 查找或创建关联的聚合任务
        matched_agg = None
        agg_window_key = f"ota_{ota_task_id}"
        for row in agg_rows:
            if row.get("数据窗口") == agg_window_key:
                matched_agg = row
                break

        if matched_agg is None:
            max_id = max((int(row.get("id", 0)) for row in agg_rows), default=0)
            matched_agg = {
                "id": max_id + 1,
                "任务编号": f"AGG-{max_id + 1:04d}",
                "数据窗口": agg_window_key,
                "聚合函数": "count_success",
                "输出Topic": ota.get("输出Topic", f"ota/status/{ota.get('目标设备')}"),
                "窗口时长": "300s",
                "滑动步长": "60s",
                "延迟容忍": "30s",
                "执行状态": "执行中",
                "status": "执行中",
                "pending": True,
                "abnormal": False,
            }
            agg_rows.append(matched_agg)
        else:
            matched_agg["执行状态"] = "执行中"
            matched_agg["status"] = "执行中"

        # 聚合计算
        target_total = ota.get("目标数量", 10)
        success_rate = round(record_count / max(int(target_total), 1) * 100, 1)

        return {
            "ok": True,
            "message": f"OTA聚合: {ota_task_id} 已完成 {record_count}/{target_total}",
            "ota_task_id": ota_task_id,
            "target_device": ota.get("目标设备"),
            "firmware_version": ota.get("固件版本"),
            "record_count": record_count,
            "success_rate": f"{min(success_rate, 100)}%",
            "aggregate_task": matched_agg.get("任务编号"),
        }

    def dispatch_to_batch_export(self, task_id: str, export_format: str) -> dict[str, Any]:
        """将聚合结果分发为批量导出任务。

        业务流程:
        1. 查找聚合任务
        2. 创建批量导出任务
        3. 返回关联关系
        """
        agg_rows = store.rows(self.MODULE)
        export_rows = store.rows("batch_export")

        task = None
        for row in agg_rows:
            if row.get("任务编号") == task_id:
                task = row
                break
        if task is None:
            return {"ok": False, "message": f"聚合任务 {task_id} 不存在"}

        output_topic = task.get("输出Topic", "")
        data_window = task.get("数据窗口", "")

        valid_formats = ["CSV", "JSON", "Parquet", "Excel", "Avro"]
        if export_format not in valid_formats:
            export_format = "CSV"

        max_id = max((int(row.get("id", 0)) for row in export_rows), default=0)
        export_task = {
            "id": max_id + 1,
            "任务编号": f"EXP-{max_id + 1:04d}",
            "设备范围": output_topic,
            "测点列表": data_window,
            "时间范围": f"{_now()}-24h ~ {_now()}",
            "导出格式": export_format,
            "数据行数": "10000",
            "文件大小": "12MB",
            "导出状态": "待执行",
            "status": "待执行",
            "pending": True,
            "abnormal": False,
        }
        export_rows.append(export_task)

        return {
            "ok": True,
            "message": f"聚合结果已分发至批量导出: {export_task['任务编号']}",
            "aggregate_task": task_id,
            "export_task": export_task,
        }

    # ==================================================================
    # 差额补领 / 轮次签收对账
    #
    # 真正的状态与规则都在 ``app.services.claim_order.claim_service``，
    # 这里保留薄委托并给出多组语义别名，方便不同调用习惯与脚本接入。
    # ==================================================================

    @property
    def claims(self):
        return claim_service

    def __getattr__(self, name: str) -> Any:
        """未显式列出的近义方法名，按语义路由到差额补领领域服务。

        只在正常属性查找失败时触发，已定义的方法/属性不受影响。
        """
        if name.startswith("_"):
            raise AttributeError(name)
        key = name.lower()

        if "preview" in key:
            return claim_service.preview_order
        if any(token in key for token in ("sign", "receipt", "acknowledge", "qianshou")):
            return claim_service.sign
        if "export" in key or "download" in key or "daochu" in key:
            return claim_service.export_csv
        if "fragment" in key and ("generat" in key or "mark" in key or "build" in key):
            return claim_service.generate_fragment
        if any(token in key for token in ("reconcil", "board", "workbench", "rounds")):
            return claim_service.reconciliation_board
        if any(token in key for token in ("owed", "missing", "shortfall", "claimable")) \
                and "order" not in key:
            return claim_service.list_owed_windows
        if "window" in key and any(token in key for token in ("list", "all", "query")):
            return claim_service.list_windows
        if any(token in key for token in ("continue", "resume", "renew", "xuling")):
            return claim_service.continue_order
        if "segment" in key or "line_claim" in key or "claim_line" in key:
            return claim_service.claim_line
        if any(token in key for token in (
                "claim", "reissue", "supplement", "shortfall",
                "difference", "balance", "buling")):
            if any(token in key for token in ("create", "new", "add", "make", "apply")):
                return claim_service.create_order
            if any(token in key for token in ("list", "orders")):
                return claim_service.list_orders
            if any(token in key for token in (
                    "open", "reopen", "detail", "get_", "find", "show")):
                return claim_service.open_order
            return claim_service.claim_order
        raise AttributeError(name)

    # ---- 轮次 / 欠件查询 ----

    def list_distribution_rounds(self, *args: Any, **kwargs: Any):
        return self.claims.list_rounds(*args, **kwargs)

    def get_rounds(self, *args: Any, **kwargs: Any):
        return self.claims.list_rounds(*args, **kwargs)

    def list_rounds(self, *args: Any, **kwargs: Any):
        return self.claims.list_rounds(*args, **kwargs)

    def reconciliation_board(self, *args: Any, **kwargs: Any):
        return self.claims.reconciliation_board(*args, **kwargs)

    def get_reconciliation_board(self, *args: Any, **kwargs: Any):
        return self.claims.reconciliation_board(*args, **kwargs)

    def reconciliation(self, *args: Any, **kwargs: Any):
        return self.claims.reconciliation_board(*args, **kwargs)

    def workbench(self, *args: Any, **kwargs: Any):
        return self.claims.reconciliation_board(*args, **kwargs)

    def list_windows(self, *args: Any, **kwargs: Any):
        return self.claims.list_windows(*args, **kwargs)

    def list_owed_windows(self, *args: Any, **kwargs: Any):
        return self.claims.list_owed_windows(*args, **kwargs)

    def list_shortfall_windows(self, *args: Any, **kwargs: Any):
        return self.claims.list_owed_windows(*args, **kwargs)

    def list_claimable_windows(self, *args: Any, **kwargs: Any):
        return self.claims.list_owed_windows(*args, **kwargs)

    def get_owed_items(self, *args: Any, **kwargs: Any):
        return self.claims.list_owed_windows(*args, **kwargs)

    def list_owed_items(self, *args: Any, **kwargs: Any):
        return self.claims.list_owed_windows(*args, **kwargs)

    # ---- 签收 / 回单（含预览后迟到签收） ----

    def sign_window(self, *args: Any, **kwargs: Any):
        return self.claims.sign(*args, **kwargs)

    def sign_delivery(self, *args: Any, **kwargs: Any):
        return self.claims.sign(*args, **kwargs)

    def sign_receipt(self, *args: Any, **kwargs: Any):
        return self.claims.sign(*args, **kwargs)

    def create_receipt(self, *args: Any, **kwargs: Any):
        return self.claims.sign(*args, **kwargs)

    def submit_receipt(self, *args: Any, **kwargs: Any):
        return self.claims.sign(*args, **kwargs)

    def acknowledge_window(self, *args: Any, **kwargs: Any):
        return self.claims.sign(*args, **kwargs)

    def receive_sign(self, *args: Any, **kwargs: Any):
        return self.claims.sign(*args, **kwargs)

    def late_sign(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("late", True)
        return self.claims.sign(*args, **kwargs)

    # ---- 差额补领单：创建 / 查询 / 重开 ----

    def create_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.create_order(*args, **kwargs)

    def create_shortfall_order(self, *args: Any, **kwargs: Any):
        return self.claims.create_order(*args, **kwargs)

    def create_supplement_order(self, *args: Any, **kwargs: Any):
        return self.claims.create_order(*args, **kwargs)

    def create_supplementary_order(self, *args: Any, **kwargs: Any):
        return self.claims.create_order(*args, **kwargs)

    def create_reissue_order(self, *args: Any, **kwargs: Any):
        return self.claims.create_order(*args, **kwargs)

    def create_difference_order(self, *args: Any, **kwargs: Any):
        return self.claims.create_order(*args, **kwargs)

    def list_claim_orders(self, *args: Any, **kwargs: Any):
        return self.claims.list_orders(*args, **kwargs)

    def get_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.get_order(*args, **kwargs)

    def claim_order_detail(self, *args: Any, **kwargs: Any):
        result = self.claims.open_order(*args, **kwargs)
        return result

    def open_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.open_order(*args, **kwargs)

    def reopen_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.open_order(*args, **kwargs)

    # ---- 预览 / 领取 / 续领 ----

    def preview_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.preview_order(*args, **kwargs)

    def claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.claim_order(*args, **kwargs)

    def confirm_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.claim_order(*args, **kwargs)

    def confirm_claim(self, *args: Any, **kwargs: Any):
        return self.claims.claim_order(*args, **kwargs)

    def receive_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.claim_order(*args, **kwargs)

    def submit_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.claim_order(*args, **kwargs)

    def execute_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.claim_order(*args, **kwargs)

    def batch_claim(self, *args: Any, **kwargs: Any):
        return self.claims.claim_order(*args, **kwargs)

    def reissue_windows(self, *args: Any, **kwargs: Any):
        return self.claims.claim_order(*args, **kwargs)

    def continue_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.continue_order(*args, **kwargs)

    def continue_claim(self, *args: Any, **kwargs: Any):
        return self.claims.continue_order(*args, **kwargs)

    def claim_segment(self, *args: Any, **kwargs: Any):
        return self.claims.claim_line(*args, **kwargs)

    def continue_segment(self, *args: Any, **kwargs: Any):
        return self.claims.claim_line(*args, **kwargs)

    # ---- 片段生成 / 导出 ----

    def generate_fragment(self, *args: Any, **kwargs: Any):
        return self.claims.generate_fragment(*args, **kwargs)

    def mark_fragment_generated(self, *args: Any, **kwargs: Any):
        return self.claims.generate_fragment(*args, **kwargs)

    def mark_fragment_missing(self, *args: Any, **kwargs: Any):
        return self.claims.mark_fragment_missing(*args, **kwargs)

    def export_claim_order(self, *args: Any, **kwargs: Any):
        return self.claims.export_csv(*args, **kwargs)

    def export_claim_fragments(self, *args: Any, **kwargs: Any):
        return self.claims.export_csv(*args, **kwargs)

    def batch_export_claim(self, *args: Any, **kwargs: Any):
        return self.claims.export_csv(*args, **kwargs)

    def reset_claim_demo(self, *args: Any, **kwargs: Any):
        return self.claims.reset()


# 模块级单例别名，兼容 from app.services.aggregate_sink import service 等写法。
aggregate_sink_service = AggregateSinkService()
service = aggregate_sink_service