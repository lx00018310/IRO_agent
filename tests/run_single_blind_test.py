import sys
import time
from iro_agent.config import get_config
from iro_agent.cli import init_agent_engine

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

questions = [
    "今天发布了什么？",
    "今天日志里的物料拒收异常，发生在发布之前还是之后？",
    "这次物料拒收问题最可能属于哪个模块？",
    "过去90天以前发生过类似物料拒收或订单异常问题吗？",
    "这次异常会影响哪些业务？",
]

def run_one(q_idx):
    config = get_config()
    engine = init_agent_engine(config)
    q = questions[q_idx]
    print(f"\n==================================================")
    print(f"【测试问题 {q_idx + 1}】: {q}")
    print(f"==================================================")
    reply = engine.chat_completion([{"role": "user", "content": q}])
    print(f"[IRO_agent 回答]:\n{reply}")

if __name__ == "__main__":
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    run_one(idx)
