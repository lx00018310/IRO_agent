from iro_agent.memory.correction_detector import CorrectionDetector


def test_correction_detection_patterns():
    """测试各类典型纠错与指导短语的准确识别与分类"""
    # 1. 显式记住指令
    text1 = "记住：查询配置应该遍历配置目录中的所有配置文件，不能只用 grep。"
    res1 = CorrectionDetector.detect(text1)
    assert res1 is not None
    assert res1["rule_type"] == "configuration_rule"
    assert "遍历配置目录" in res1["rule_text"]

    # 2. 查错修正
    text2 = "你查错了，正确的是以后排查叫料状态要以 ordersys_dock_task 表为准。"
    res2 = CorrectionDetector.detect(text2)
    assert res2 is not None
    assert res2["rule_type"] == "source_of_truth_correction"
    assert "ordersys_dock_task" in res2["rule_text"]

    # 3. 规范操作指示
    text3 = "以后应该在看日志前先确认当前生效的程序版本号。"
    res3 = CorrectionDetector.detect(text3)
    assert res3 is not None
    assert "先确认当前生效的程序版本号" in res3["rule_text"]


def test_correction_detection_negative_cases():
    """测试普通提问与日常会话不应被误判为纠错指令"""
    negatives = [
        "今天发布了什么版本？",
        "为什么日志里有物料拒收异常？",
        "你知道怎么配置数据库密码吗？",
        "系统卡住的时候应该查哪些表？",
        "今天天气怎么样？",
    ]
    for neg in negatives:
        res = CorrectionDetector.detect(neg)
        assert res is None, f"误报判定: '{neg}' 不应被识别为纠错指令"


def test_memory_honesty_formatting():
    """测试记忆诚实原则：保存成功方可声称已记住，失败据实反馈"""
    # 成功场景
    success_msg = CorrectionDetector.format_honesty_response(
        rule_id="RULE-20260910001",
        rule_text="查配置需遍历所有配置文件"
    )
    assert "已持久化记住该原则" in success_msg
    assert "RULE-20260910001" in success_msg

    # 失败场景
    failed_msg = CorrectionDetector.format_honesty_response(
        rule_id=None,
        rule_text="查配置需遍历所有配置文件",
        error="磁盘空间不足，SQLite 写入失败"
    )
    assert "持久化失败" in failed_msg
    assert "磁盘空间不足" in failed_msg
    assert "无法保证跨会话持久化" in failed_msg
