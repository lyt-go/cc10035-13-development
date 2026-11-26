"""差额补领单 / 轮次签收对账的行为测试。

完整覆盖题述场景：
R1 的 07:10、07:20 没签，R2 也有一个 07:10；接收人选 R1 两窗，
R1 07:10 迟到签收与补领操作重合；领取后仅 R1 07:20 被补发，
R2 同名窗保持未签；重开单可见 07:10 由哪笔原交付签收；
未生成片段可续领，已交付项保留自己的回单。
"""
from __future__ import annotations

import pytest

from app.services.aggregate_sink import AggregateSinkService
from app.services.claim_order import ClaimOrderService


@pytest.fixture
def svc() -> ClaimOrderService:
    service = ClaimOrderService()
    service.reset()
    return service


def test_seed_matches_r1_r2_scenario(svc: ClaimOrderService):
    assert [w["window"] for w in svc.list_owed_windows("R1")] == ["07:10", "07:20"]
    assert [w["window"] for w in svc.list_owed_windows("R2")] == ["07:10"]
    # 同名 07:10 在两个轮次里是两条独立欠件，且重算值不同。
    r1 = next(w for w in svc.windows if w["round_no"] == "R1" and w["window"] == "07:10")
    r2 = next(w for w in svc.windows if w["round_no"] == "R2" and w["window"] == "07:10")
    assert r1["id"] != r2["id"]
    assert r1["value"] != r2["value"]


def test_only_matching_round_and_source_is_offset(svc: ClaimOrderService):
    import copy
    twin = copy.deepcopy(next(
        w for w in svc.windows if w["round_no"] == "R1" and w["window"] == "07:10"))
    twin.update({
        "id": "WIN-R1-0710-SRC2", "window_id": "WIN-R1-0710-SRC2",
        "source": "SRC-OTHER", "来源": "SRC-OTHER",
        "signed": False, "已签收": False, "receipt_no": None, "回单号": None})
    svc.windows.append(twin)

    result = svc.sign(round_no="R1", window="07:10", source="SRC-MAIN")
    assert result["ok"] is True
    assert result["冲销欠件"]["source"] == "SRC-MAIN"
    other = next(w for w in svc.windows if w["id"] == "WIN-R1-0710-SRC2")
    assert other["signed"] is False
    # R2 的同名窗也不受影响。
    r2 = next(w for w in svc.windows if w["round_no"] == "R2" and w["window"] == "07:10")
    assert r2["signed"] is False


def test_late_sign_after_preview_is_not_redelivered(svc: ClaimOrderService):
    created = svc.create_order(round_no="R1", windows=["07:10", "07:20"])
    assert created["ok"] is True
    order_no = created["order_no"]

    preview = svc.preview_order(order_no)["preview"]
    assert preview["deliverable_windows"] == ["07:10", "07:20"]

    # 预览之后、真正领取之前，R1 07:10 的原交付签收迟到。
    sign = svc.sign(round_no="R1", window="07:10")
    assert sign["ok"] is True
    receipt_no = sign["receipt"]["receipt_no"]
    delivery_no = sign["receipt"]["delivery_no"]

    result = svc.claim_order(order_no)
    assert result["ok"] is True
    assert result["delivered_windows"] == ["07:20"]
    assert result["covered_windows"] == ["07:10"]

    # R2 同名窗保持未签。
    r2 = next(w for w in svc.windows if w["round_no"] == "R2" and w["window"] == "07:10")
    assert r2["signed"] is False

    # 重新打开：07:10 标注来自哪笔原交付/回单；07:20 有自己的补领回单。
    detail = svc.get_order(order_no)
    line_710 = next(l for l in detail["lines"] if l["window"] == "07:10")
    line_720 = next(l for l in detail["lines"] if l["window"] == "07:20")
    assert line_710["state"] == "原交付已签收"
    assert line_710["original_delivery_no"] == delivery_no == "JF-20261126-R1"
    assert line_710["original_receipt_no"] == receipt_no
    assert line_720["state"] == "已补发"
    assert line_720["receipt_no"]
    assert line_720["batch_no"]

    # 再次领取不得重复交付 07:20，也不会改动 07:10 的归属。
    again = svc.claim_order(order_no)
    assert again["delivered_windows"] == []
    assert "07:20" in again["already_delivered_windows"]
    detail2 = svc.get_order(order_no)
    assert next(l for l in detail2["lines"] if l["window"] == "07:20")["receipt_no"] \
        == line_720["receipt_no"]
    assert next(l for l in detail2["lines"] if l["window"] == "07:10")[
        "original_receipt_no"] == receipt_no


def test_export_contains_only_actual_fragments(svc: ClaimOrderService):
    order_no = svc.create_order(round_no="R1", windows=["07:10", "07:20"])["order_no"]
    svc.sign(round_no="R1", window="07:10")
    result = svc.claim_order(order_no)
    batch_no = result["batch_no"]

    export = svc.export_csv(order_no, batch_no=batch_no)
    body = export["csv"].removeprefix("\ufeff")
    rows = [line for line in body.splitlines()[1:] if line.strip()]
    assert rows and all(",07:20," in row for row in rows)
    assert all("07:10" not in row.split(",")[2] for row in rows)
    assert all(order_no in row for row in rows)


def test_missing_fragment_can_be_continued_and_keeps_old_receipt(svc: ClaimOrderService):
    order_no = "BL-XP-01"
    before = svc.get_order(order_no)
    old_receipt = next(l for l in before["lines"] if l["window"] == "08:00")["receipt_no"]
    assert before["status"] == "部分领取"

    blocked = svc.claim_order(order_no)
    assert blocked["delivered_windows"] == []
    assert blocked["fragment_missing_windows"] == ["08:10"]

    assert svc.generate_fragment(round_no="R3", window="08:10")["ok"]
    done = svc.claim_order(order_no)
    assert done["delivered_windows"] == ["08:10"]

    after = svc.get_order(order_no)
    line_800 = next(l for l in after["lines"] if l["window"] == "08:00")
    line_810 = next(l for l in after["lines"] if l["window"] == "08:10")
    assert line_800["receipt_no"] == old_receipt
    assert line_810["receipt_no"] and line_810["receipt_no"] != old_receipt
    assert after["status"] == "已完成"
    assert len(after["batches"]) == 2


def test_aggregate_service_delegates_and_aliases(svc: ClaimOrderService):
    # AggregateSinkService 与路由共用 claim_service 单例；这里只验证委托形态。
    from app.services.claim_order import claim_service
    service = AggregateSinkService()
    try:
        board = service.reconciliation_board("R1")
        assert board["ok"] is True
        assert board["本轮尚缺"] == ["07:10", "07:20"]
        created = service.create_claim_order(round_no="R1", windows=["07:10", "07:20"])
        assert created["ok"] is True
        # 语义别名 / 兜底方法名都应可调。
        assert callable(service.create_shortfall_order)
        assert callable(service.preview_difference_claim)
        assert callable(service.reopen_balance_order)
    finally:
        # 还原共享单例的标准种子，避免污染同进程后续 API 测试。
        claim_service.reset()
