import re
from enum import Enum
from typing import Dict, Any, List


class QueryIntent(str, Enum):
    CONFIGURATION = "configuration"
    BUSINESS_DATA = "business_data"
    CODE_STRUCTURE = "code_structure"
    RUNTIME_FAULT = "runtime_fault"
    VERSION = "version"
    HISTORY = "history"
    GENERAL = "general"


class IntentRouter:
    """现场提问意图路由器：依据工业工控语义识别问题类型，决议优先检索路径与工具链"""

    @classmethod
    def route(cls, query: str) -> Dict[str, Any]:
        q = (query or "").strip().lower()
        if not q:
            return {
                "intent": QueryIntent.GENERAL,
                "confidence": 0.0,
                "recommended_tools": ["project_lookup"],
                "execution_strategy": "通用问答，默认查阅项目知识库",
            }

        # 1. 版本与发布意图 (优先判定是否有显式发版、commit 问询)
        version_keywords = ["发布了什么", "发布什么", "最新版本", "当前版本", "更新了什么", "commit", "提交记录", "发版", "上线了什么", "wrelease"]
        if any(vk in q for vk in version_keywords) and not any(fk in q for fk in ["为什么", "卡住", "异常", "报错"]):
            return {
                "intent": QueryIntent.VERSION,
                "confidence": 0.95,
                "recommended_tools": ["version_current", "version_recent", "version_compare"],
                "execution_strategy": "优先调用版本提供者 (GitReader / WReleaseReader) 获取版本与发布变更",
            }

        # 2. 历史案例与故障记忆意图
        history_keywords = ["过去", "以前", "历史", "发生过", "类似问题", "以往", "相似事故", "记忆库", "多少次", "频次"]
        if any(hk in q for hk in history_keywords):
            return {
                "intent": QueryIntent.HISTORY,
                "confidence": 0.9,
                "recommended_tools": ["learning_recall", "diagnostic_pipeline"],
                "execution_strategy": "优先调用 IncidentStore 检索历史事故记忆库及案例统计",
            }

        # 3. 配置查询意图 (优先查 ConfigCatalog 而非代码盲搜 grep)
        config_keywords = ["配置", "config", "settings", "setting", "参数", "轮询时间", "超时时间", "在哪配", "怎么配", "端口", "ip地址"]
        if any(ck in q for ck in config_keywords) and not any(fk in q for fk in ["报错", "卡死", "失败", "拒绝"]):
            return {
                "intent": QueryIntent.CONFIGURATION,
                "confidence": 0.92,
                "recommended_tools": ["learning_recall", "config_lookup", "code_search"],
                "execution_strategy": "先调用 learning_recall 召回配置规则，再查 ConfigCatalog 检索配置文件与键，最后按需交叉验证代码",
            }

        # 4. 代码结构与调用拓扑意图
        code_keywords = ["接口", "api", "调用", "写哪张表", "查哪张表", "哪个类", "controller", "service", "mapper", "链路", "拓扑", "怎么实现"]
        if any(code_k in q for code_k in code_keywords) and not any(fk in q for fk in ["卡死", "故障", "现场报错"]):
            return {
                "intent": QueryIntent.CODE_STRUCTURE,
                "confidence": 0.88,
                "recommended_tools": ["project_lookup", "code_trace_api_to_table", "code_find_table_usage", "flow_lookup"],
                "execution_strategy": "优先使用代码拓扑图追溯 API -> Controller -> Service -> Mapper -> Table 调用链",
            }

        # 5. 运行时故障与异常诊断意图
        fault_keywords = ["卡死", "卡住", "报错", "异常", "掉线", "中断", "失败", "拒绝", "拒收", "暂停", "超时", "死锁", "无法", "坏了", "为什么", "怎么回事", "error", "exception", "failed"]
        if any(fk in q for fk in fault_keywords):
            return {
                "intent": QueryIntent.RUNTIME_FAULT,
                "confidence": 0.95,
                "recommended_tools": ["learning_recall", "diagnostic_pipeline", "log_search", "version_current", "project_lookup"],
                "execution_strategy": "综合调用 learning_recall、project_lookup、版本时序比对、日志检索与多维故障归因编排流水线",
            }

        # 6. 业务现场数据与主事实源查询意图
        biz_keywords = ["最新一托", "当前托盘", "当前叫料", "叫料状态", "装车状态", "实时状态", "现场数据", "进度"]
        if any(bk in q for bk in biz_keywords):
            return {
                "intent": QueryIntent.BUSINESS_DATA,
                "confidence": 0.85,
                "recommended_tools": ["learning_recall", "project_lookup", "db_query"],
                "execution_strategy": "先通过 project_lookup 锁定权威事实源 (Source of Truth)，严禁误查回执表，再通过只读 DB 查询真实状态",
            }

        return {
            "intent": QueryIntent.GENERAL,
            "confidence": 0.5,
            "recommended_tools": ["learning_recall", "project_lookup"],
            "execution_strategy": "通用问题排查，融合历史学习规则与项目认知库",
        }
