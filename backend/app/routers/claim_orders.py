"""差额补领 / 轮次签收对账接口。

路径同时覆盖 ``/api/aggregate_sink/claim-orders``、下划线版
``claim_orders`` 与短路径 ``/api/claim-orders`` 等命名。所有写接口都宽松
解析 JSON / query 入参。本路由必须先于 resource 的 /api/{module} 通配路由注册。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.services.claim_order import claim_service

router = APIRouter(tags=["聚合分发-差额补领"])


async def _payload(request: Request) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            body = await request.json()
            if isinstance(body, dict):
                data.update(body)
        except Exception:
            pass
    data.update({key: value for key, value in request.query_params.items()})
    return data


def _csv_response(result: dict[str, Any]) -> Response:
    if not result.get("ok"):
        return Response(
            content=str(result.get("message", "导出失败")),
            status_code=404, media_type="text/plain; charset=utf-8")
    return Response(
        content=result["csv"].encode("utf-8"),
        media_type=result.get("media_type", "text/csv; charset=utf-8"),
        headers={
            "Content-Disposition":
                f'attachment; filename="{result.get("file_name", "claim.csv")}"'
        },
    )


# ======================== 看板 / 轮次 / 窗口 ========================

@router.get("/api/aggregate_sink/reconciliation")
@router.get("/api/aggregate_sink/board")
@router.get("/api/reconciliation/board")
@router.get("/api/claim-board")
async def reconciliation_board(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    return claim_service.reconciliation_board(
        payload.get("round_no") or payload.get("轮次"))


@router.get("/api/aggregate_sink/rounds")
@router.get("/api/distribution-rounds")
async def list_rounds() -> dict[str, Any]:
    items = claim_service.list_rounds()
    return {"ok": True, "rounds": items, "items": items, "total": len(items)}


@router.get("/api/aggregate_sink/windows")
@router.get("/api/aggregate_sink/owed-windows")
@router.get("/api/owed-windows")
async def list_windows(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    path = request.url.path
    only_owed = (
        "owed-windows" in path
        or str(payload.get("only_owed", payload.get("owed", ""))).lower()
        in ("1", "true", "yes", "是")
        or bool(payload.get("only_missing"))
    )
    items = claim_service.list_windows(
        round_no=payload.get("round_no") or payload.get("轮次"),
        source=payload.get("source") or payload.get("来源"),
        only_owed=only_owed,
    )
    return {"ok": True, "items": items, "windows": items,
            "total": len(items), "page": 1, "size": max(len(items), 20)}


# ======================== 签收（迟到回单） ========================

@router.post("/api/aggregate_sink/sign")
@router.post("/api/aggregate_sink/receipts")
@router.post("/api/sign")
@router.post("/api/receipts")
@router.post("/api/claim-orders/sign")
@router.post("/api/claim_orders/sign")
async def sign_window(request: Request) -> dict[str, Any]:
    return claim_service.sign(await _payload(request))


# ======================== 片段生成（模拟离线片段就绪） ========================

@router.post("/api/aggregate_sink/fragments/generate")
@router.post("/api/aggregate_sink/windows/generate-fragment")
@router.post("/api/fragments/generate")
async def generate_fragment(request: Request) -> dict[str, Any]:
    return claim_service.generate_fragment(await _payload(request))


@router.post("/api/aggregate_sink/fragments/mark-missing")
@router.post("/api/fragments/mark-missing")
async def mark_fragment_missing(request: Request) -> dict[str, Any]:
    return claim_service.mark_fragment_missing(await _payload(request))


# ======================== 补领单查询 / 创建 ========================

@router.get("/api/aggregate_sink/claim-orders")
@router.get("/api/aggregate_sink/claim_orders")
@router.get("/api/claim-orders")
@router.get("/api/claim_orders")
@router.get("/api/claim-order")
@router.get("/api/claim_order")
async def list_claim_orders() -> dict[str, Any]:
    items = claim_service.list_orders()
    return {"ok": True, "items": items, "orders": items,
            "total": len(items), "page": 1, "size": max(len(items), 20)}


@router.post("/api/aggregate_sink/claim-orders")
@router.post("/api/aggregate_sink/claim_orders")
@router.post("/api/claim-orders")
@router.post("/api/claim_orders")
@router.post("/api/claim-order")
async def create_claim_order(request: Request) -> dict[str, Any]:
    return claim_service.create_order(await _payload(request))


@router.get("/api/aggregate_sink/claim-orders/{order_ref}")
@router.get("/api/aggregate_sink/claim_orders/{order_ref}")
@router.get("/api/claim-orders/{order_ref}")
@router.get("/api/claim_orders/{order_ref}")
@router.get("/api/claim-order/{order_ref}")
async def get_claim_order(order_ref: str) -> dict[str, Any]:
    return claim_service.open_order(order_ref)


@router.get("/api/aggregate_sink/claim-orders/{order_ref}/open")
@router.post("/api/aggregate_sink/claim-orders/{order_ref}/open")
@router.get("/api/claim-orders/{order_ref}/open")
async def open_claim_order(order_ref: str) -> dict[str, Any]:
    return claim_service.open_order(order_ref)


@router.post("/api/aggregate_sink/claim-orders/{order_ref}/preview")
@router.get("/api/aggregate_sink/claim-orders/{order_ref}/preview")
@router.post("/api/aggregate_sink/claim_orders/{order_ref}/preview".replace("-", "_"))
@router.post("/api/claim-orders/{order_ref}/preview")
@router.post("/api/claim_orders/{order_ref}/preview")
async def preview_claim_order(order_ref: str, request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    if payload:
        return claim_service.preview_order(order_ref, **payload)
    return claim_service.preview_order(order_ref)


@router.post("/api/aggregate_sink/claim-orders/{order_ref}/claim")
@router.post("/api/aggregate_sink/claim_orders/{order_ref}/claim".replace("-", "_"))
@router.post("/api/claim-orders/{order_ref}/claim")
@router.post("/api/claim_orders/{order_ref}/claim".replace("-", "_"))
async def claim_order(order_ref: str, request: Request) -> dict[str, Any]:
    return claim_service.claim_order(order_ref, await _payload(request))


@router.post("/api/aggregate_sink/claim-orders/{order_ref}/continue")
@router.post("/api/claim-orders/{order_ref}/continue")
async def continue_order(order_ref: str, request: Request) -> dict[str, Any]:
    return claim_service.continue_order(order_ref, await _payload(request))


@router.post("/api/aggregate_sink/claim-orders/{order_ref}/lines/{line_ref}/claim")
@router.post("/api/claim-orders/{order_ref}/lines/{line_ref}/claim")
async def claim_line(order_ref: str, line_ref: str) -> dict[str, Any]:
    return claim_service.claim_line(order_ref, line_ref)


# ======================== 导出 ========================

@router.get("/api/aggregate_sink/claim-orders/{order_ref}/export")
@router.get("/api/aggregate_sink/claim_orders/{order_ref}/export".replace("-", "_"))
@router.get("/api/claim-orders/{order_ref}/export")
@router.get("/api/claim_orders/{order_ref}/export".replace("-", "_"))
async def export_claim_order(order_ref: str, batch_no: str | None = None) -> Response:
    return _csv_response(claim_service.export_csv(order_ref, batch_no=batch_no))


@router.get("/api/aggregate_sink/claim-orders/{order_ref}/batches/{batch_no}/export")
@router.get("/api/claim-orders/{order_ref}/batches/{batch_no}/export")
async def export_claim_batch(order_ref: str, batch_no: str) -> Response:
    return _csv_response(claim_service.export_csv(order_ref, batch_no=batch_no))


@router.post("/api/aggregate_sink/claim-demo/reset")
async def reset_demo() -> dict[str, Any]:
    return claim_service.reset()
