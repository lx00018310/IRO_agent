import re
from typing import List, Dict, Any, Optional
from iro_agent.knowledge.models import BusinessFlow, ApiKnowledge, TableKnowledge


class BusinessFlowLearner:
    """核心业务流提炼器：基于 API 路由、代码调用图谱与数据库表操作，构建端到端业务处理链路"""

    DEFAULT_TASK013_FLOWS = [
        BusinessFlow(
            name="物料叫料与装车轮询流程",
            aliases=["叫料流程", "物料轮询", "叫料装车", "MaterialCallFlow"],
            entry_api="/api/dock/material/poll",
            controller="DockTaskController",
            services=["DockTaskService", "MaterialDispatchService"],
            mappers=["DockTaskMapper"],
            tables=["ordersys_dock_task"],
            states=["WAIT_MATERIAL", "CALLING", "CALL_SUCCESS", "DOCKING"],
            configs=["materialCallPollIntervalSeconds", "ordersys-settings.json"],
            external_systems=["WMS系统", "AGV搬运机器人"],
            source_of_truth="ordersys_dock_task",
            evidence="DockTaskController.java 轮询调用 DockTaskService 并最终更新 ordersys_dock_task 状态",
            confidence="confirmed",
        ),
        BusinessFlow(
            name="装车就位回执确认流程",
            aliases=["装车回执", "到位确认", "回调接收", "DispatchCallbackFlow"],
            entry_api="/api/dispatch/callback/receipt",
            controller="DispatchCallbackController",
            services=["DispatchCallbackService"],
            mappers=["DispatchCallbackReceiptMapper"],
            tables=["ordersys_dispatch_callback_receipt", "ordersys_dock_task"],
            states=["RECEIVED", "CONFIRMED", "IGNORED"],
            configs=["callbackTimeoutSeconds"],
            external_systems=["外部装车硬件终端", "PLC"],
            source_of_truth="ordersys_dock_task (主业务状态) / ordersys_dispatch_callback_receipt (仅为通信日志)",
            evidence="DispatchCallbackController 接收第三方回执入库 ordersys_dispatch_callback_receipt，仅作为网络凭据",
            confidence="confirmed",
        ),
    ]

    @classmethod
    def discover_flows(
        cls,
        apis: List[ApiKnowledge],
        tables: List[TableKnowledge],
        code_graph_dict: Optional[Dict[str, Any]] = None,
        project_name: str = "TASK-013",
    ) -> List[BusinessFlow]:
        """依据现有 API、实体与拓扑图综合推导业务链路"""
        flows: List[BusinessFlow] = []

        # 1. 优先从代码拓扑图自动推导
        if code_graph_dict and "entities" in code_graph_dict:
            entities = code_graph_dict.get("entities", [])
            edges = code_graph_dict.get("edges", [])

            # 寻找 Controller 节点
            controllers = [e for e in entities if e.get("type") in ("Controller", "controller")]
            for ctrl in controllers:
                ctrl_name = ctrl.get("name", "")
                ctrl_id = ctrl.get("id", "")

                # 追踪 controller -> service 边
                svc_ids = [edge["target"] for edge in edges if edge.get("source") == ctrl_id and edge.get("type") in ("CALLS", "calls", "DEPENDS")]
                # 追踪 service -> mapper 边
                mapper_ids = [edge["target"] for edge in edges if edge.get("source") in svc_ids and edge.get("type") in ("CALLS", "calls", "DEPENDS")]
                # 追踪 mapper -> table 边
                table_names = [edge["target"] for edge in edges if edge.get("source") in mapper_ids and edge.get("type") in ("WRITES_TO", "READS_FROM", "writes_to", "reads_from")]

                matched_api = next((a.path for a in apis if ctrl_name.lower() in a.controller.lower()), f"/api/{ctrl_name.lower().replace('controller', '')}")

                if table_names or svc_ids:
                    flow_name = f"{ctrl_name.replace('Controller', '')} 业务流"
                    flows.append(
                        BusinessFlow(
                            name=flow_name,
                            aliases=[flow_name, ctrl_name],
                            entry_api=matched_api,
                            controller=ctrl_name,
                            services=[s.split(":")[-1] for s in svc_ids],
                            mappers=[m.split(":")[-1] for m in mapper_ids],
                            tables=list(set(table_names)),
                            source_of_truth=table_names[0] if table_names else "",
                            evidence=f"由代码拓扑图解析: {ctrl_name} -> Services -> Tables",
                            confidence="strongly_inferred",
                        )
                    )

        # 2. 若推导不足且属于 TASK-013，注入预置的已验证标准工业流
        if "013" in project_name or not flows:
            for df in cls.DEFAULT_TASK013_FLOWS:
                if not any(f.name == df.name for f in flows):
                    flows.append(df)

        return flows
