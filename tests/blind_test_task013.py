import sys
from pathlib import Path
from iro_agent.config import get_config
from iro_agent.cli import init_agent_engine

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def run_blind_tests():
    config = get_config()
    print("==================================================")
    print("  TASK-013 真实数据 5 个核心问题盲测验证")
    print(f"  目标工程: {config.project_name}")
    print(f"  工程路径: {config.project_root}")
    print("==================================================\n")

    engine = init_agent_engine(config)

    questions = [
        "今天发布了什么？",
        "今天日志里的物料拒收异常，发生在发布之前还是之后？",
        "这次物料拒收问题最可能属于哪个模块？",
        "过去90天以前发生过类似物料拒收或订单异常问题吗？",
        "这次异常会影响哪些业务？",
    ]

    for idx, q in enumerate(questions, start=1):
        print(f"--------------------------------------------------")
        print(f"【测试问题 {idx}】: {q}")
        print(f"--------------------------------------------------")
        reply = engine.chat_completion([{"role": "user", "content": q}])
        print(f"[IRO_agent 回答]:\n{reply}\n")
        import time
        time.sleep(2)

if __name__ == "__main__":
    run_blind_tests()
