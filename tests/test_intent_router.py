from iro_agent.router.intent_router import IntentRouter, QueryIntent


def test_intent_router_classification():
    """测试各类工控现场典型提问的意图分流准确性"""
    # 1. 配置意图
    res_cfg = IntentRouter.route("叫料轮询时间配置在哪？")
    assert res_cfg["intent"] == QueryIntent.CONFIGURATION
    assert "config_lookup" in res_cfg["recommended_tools"]

    # 2. 版本意图
    res_ver = IntentRouter.route("今天系统发布了什么版本？")
    assert res_ver["intent"] == QueryIntent.VERSION
    assert "version_current" in res_ver["recommended_tools"]

    # 3. 故障诊断意图
    res_fault = IntentRouter.route("为什么今天现场物料拒收卡住了？")
    assert res_fault["intent"] == QueryIntent.RUNTIME_FAULT
    assert "diagnostic_pipeline" in res_fault["recommended_tools"]

    # 4. 代码结构意图
    res_code = IntentRouter.route("这个物料叫料接口最后写哪张表？")
    assert res_code["intent"] == QueryIntent.CODE_STRUCTURE
    assert "code_trace_api_to_table" in res_code["recommended_tools"]

    # 5. 业务现场主数据意图
    res_biz = IntentRouter.route("查一下最新一托的实时状态")
    assert res_biz["intent"] == QueryIntent.BUSINESS_DATA
    assert "project_lookup" in res_biz["recommended_tools"]

    # 6. 历史故障记忆意图
    res_hist = IntentRouter.route("过去90天发生过类似物料拒收故障吗？")
    assert res_hist["intent"] == QueryIntent.HISTORY
