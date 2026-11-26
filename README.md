# IoT设备数据接入与协议适配平台

面向IoT设备注册、多协议适配、消息路由与时序数据归集的设备数据接入平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 设备注册 | `device_registry` | 设备档案 | 设备编号、设备类型、协议类型 |
| 协议配置 | `protocol_cfg` | 协议配置 | 配置编号、协议名称、传输方式 |
| 报文解码 | `msg_decode` | 解码规则 | 规则编号、协议类型、报文标识 |
| 消息路由 | `msg_router` | 路由规则 | 规则编号、匹配Topic、目标Topic |
| 时序测点 | `ts_point` | 测点定义 | 测点编号、设备编号、测点名称 |
| 时序存储 | `ts_store` | 存储策略 | 策略编号、测点编号、存储引擎 |
| 降采样 | `downsample` | 降采样任务 | 任务编号、源测点、目标粒度 |
| 告警触发 | `alarm_trigger` | 告警规则 | 规则编号、关联测点、告警条件 |
| 固件升级 | `firmware_ota` | 升级任务 | 任务编号、目标设备、固件版本 |
| 网关管理 | `gateway_mgmt` | 网关节点 | 网关编号、网关地址、挂载设备数 |
| 设备影子 | `shadow_dev` | 影子记录 | 记录编号、设备编号、期望状态 |
| 数据断点 | `data_gap` | 断点记录 | 记录编号、设备编号、测点编号 |
| 批量导出 | `batch_export` | 导出任务 | 任务编号、设备范围、测点列表 |
| 规则引擎 | `rule_engine` | 联动规则 | 规则编号、触发条件、执行动作 |
| 边缘缓存 | `edge_cache` | 缓存配置 | 配置编号、网关编号、缓存大小 |
| 标签绑定 | `tag_binding` | 标签关系 | 关系编号、设备编号、标签键 |
| 数据流管道 | `data_stream` | 流管道 | 管道编号、输入源、处理算子链 |
| 聚合分发 | `aggregate_sink` | 分发任务 | 任务编号、数据窗口、聚合函数 |

## 差额补领与轮次签收对账（聚合分发）

聚合分发模块内置接收方按 **分发轮次** 签收对账与 **差额补领单** 流程，工作台
`/aggregate_sink`（或独立页 `/claims`）直接可用：

- 欠件以 `(轮次, 来源, 窗口分钟)` 为唯一身份；同一分钟（如 `07:10`）在 R1/R2
  是两笔独立欠件，签收只冲销对应轮次及来源。
- 只勾选本轮尚缺窗口生成差额补领单；可先 **预览差额**。
- 预览之后才到达的 **迟到签收** 同样有效：真正「确认领取并批量导出」时会重新
  核对回单，已被原交付签收或已随补领交付过的窗口绝不重复交付。
- 每次领取生成独立补领批次与每窗自己的 **回单**，导出的 CSV 只含该次实际片段，
  并带 `归属补领单/补领批次/回单号` 列，同时在「批量导出」模块登记一笔导出任务。
- 片段尚未生成时该行保留为「片段未生成」，之后可打开原单 **续领此段**，
  已交付行的回单保持不变。
- 种子即题述场景：R1 的 `07:10/07:20` 未签、R2 也有一个 `07:10`；另有
  `BL-XP-01` 演示缺段续领。

主要接口（同时提供 `/api/aggregate_sink/...` 与 `/api/claim-orders...` 两组路径，
下划线 `claim_orders`、单数 `claim-order` 亦可）：

| 方法与路径 | 说明 |
| --- | --- |
| `GET /api/aggregate_sink/reconciliation?round_no=R1` | 轮次/欠件/补领单对账看板 |
| `GET /api/aggregate_sink/rounds` / `.../windows?only_owed=true` | 轮次计数 / 窗口欠件 |
| `POST /api/aggregate_sink/sign` | 登记签收（支持预览后迟到签收，按轮次+来源冲销） |
| `POST /api/aggregate_sink/claim-orders` | 勾选窗口新建差额补领单 |
| `GET  /api/aggregate_sink/claim-orders/{号}` | 重新打开单据与归属/回单明细 |
| `POST .../claim-orders/{号}/preview` | 预览本次将补/已签跳过/片段未生成 |
| `POST .../claim-orders/{号}/claim` | 领取并导出本次实际片段（幂等，可续领） |
| `GET  .../claim-orders/{号}/export[?batch_no=...]` | 下载整单或指定批次片段 CSV |
| `POST /api/aggregate_sink/fragments/generate` | 模拟离线片段生成完成 |

领域逻辑在 `backend/app/services/claim_order.py`（`ClaimOrderService` 单例
`claim_service`），`AggregateSinkService` 上保留 `create_claim_order`、
`preview_claim_order`、`claim_order`、`sign_window`、`open_claim_order` 等委托
与近义方法别名；行为测试见 `backend/tests/test_claim_orders.py`。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据采集、爬虫与RPA
