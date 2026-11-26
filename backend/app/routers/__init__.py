"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import claim_orders, cross_module, resource

# claim_orders 含 /api/claim-orders 等固定路径，必须排在 resource 的
# /api/{module} 动态通配路由之前。
ROUTERS = [claim_orders, cross_module, resource]
