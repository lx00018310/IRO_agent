import os
import sys
import json
import argparse
from pathlib import Path
from iro_agent.config import get_config, load_config, IROConfig
from iro_agent.security.policy import validate_read_path
from iro_agent.security.audit import AuditLogger
from iro_agent.readers.git_reader import GitReader
from iro_agent.readers.code_reader import CodeReader
from iro_agent.readers.wrelease_reader import WReleaseReader
from iro_agent.readers.log_reader import LogReader
from iro_agent.readers.db_reader import DatabaseReader
from iro_agent.memory.incident_store import IncidentStore
from iro_agent.llm.glm_client import GlmClient
from iro_agent.gateway.wechat import WeChatGatewayServer

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def init_agent_engine(config: IROConfig) -> GlmClient:
    """组装所有只读读取器并注册到大模型/分析引擎"""
    audit = AuditLogger()
    git_reader = GitReader(audit_logger=audit)
    code_reader = CodeReader(audit_logger=audit)
    wrelease_reader = WReleaseReader(audit_logger=audit)
    log_reader = LogReader(audit_logger=audit)
    memory_store = IncidentStore()

    client = GlmClient(glm_cfg=config.glm, audit_logger=audit)

    # 注册只读工具
    client.register_tool_handler("wrelease_list", lambda: wrelease_reader.list_available_releases())
    client.register_tool_handler("wrelease_compare", lambda ver_a, ver_b: wrelease_reader.compare_releases(ver_a, ver_b))
    client.register_tool_handler("log_search", lambda **kwargs: log_reader.search_logs(**kwargs))
    client.register_tool_handler("git_recent_commits", lambda limit=20: git_reader.get_recent_commits(limit=limit))
    client.register_tool_handler("code_search", lambda query: code_reader.search_code(query))
    client.register_tool_handler("memory_similar_stats", lambda keyword: memory_store.get_similar_incident_stats(keyword))

    return client


def cmd_doctor(args):
    """工控机与本地开发机环境体检"""
    print("==================================================")
    print("  IRO_agent 系统与运行环境自检 (Doctor Check)     ")
    print("==================================================")
    config = get_config()

    checks = []

    # 1. 检查 Python 版本
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("Python 运行环境", py_ver, sys.version_info >= (3, 10)))

    # 2. 项目根目录
    root_ok = Path(config.project_root).exists()
    checks.append(("项目源码根路径", config.project_root, root_ok))

    # 3. WRelease 目录
    wrel_path = Path(config.wrelease_dir)
    wrel_ok = wrel_path.exists()
    wrel_count = len(list(wrel_path.glob("*.wrelease"))) if wrel_ok else 0
    checks.append(("WRelease 交付目录", f"{config.wrelease_dir} (发现 {wrel_count} 个发布包)", wrel_ok and wrel_count > 0))

    # 4. 日志目录
    log_ok_count = sum(1 for d in config.log_dirs if Path(d).exists())
    checks.append(("日志目录有效性", f"{log_ok_count}/{len(config.log_dirs)} 目录存在", log_ok_count > 0))

    # 5. Git 仓库状态
    git_ok = False
    git_info = "不可用"
    try:
        gr = GitReader()
        status = gr.get_status()
        git_ok = True
        git_info = status.strip()
    except Exception as e:
        git_info = f"异常: {e}"
    checks.append(("Git 只读状态", git_info, git_ok))

    # 6. SQLite 数据库
    audit_ok = False
    try:
        al = AuditLogger()
        audit_ok = True
    except Exception:
        pass
    checks.append(("审计与记忆数据库 (SQLite)", "正常初始化", audit_ok))

    # 7. GLM 模型接口状态
    glm_ok = bool(config.glm.api_key and config.glm.api_key != "YOUR_GLM_API_KEY")
    glm_detail = f"已就绪 (模型: {config.glm.model})" if glm_ok else "未配置 API Key (需在 config.json 中填入)"
    checks.append(("GLM-5.3-Flash 接口", glm_detail, glm_ok))

    for name, detail, passed in checks:
        status_icon = "[PASS]" if passed else "[WARN/FAIL]"
        print(f"{status_icon:12} {name:20}: {detail}")

    print("==================================================")
    all_passed = all(c[2] for c in checks)
    if all_passed:
        print("环境校验通过！系统具备只读诊断作业条件。")
    else:
        print("注意：部分配置存在未通过项，请先检查并修改 config.json。")


def cmd_config(args):
    """查看或打印配置"""
    config = get_config()
    print("当前有效配置内容:")
    print(json.dumps(config.model_dump(), indent=2, ensure_ascii=False))


def cmd_chat(args):
    """交互式本地控制台诊断会话"""
    config = get_config()

    if not config.glm.api_key or config.glm.api_key == "YOUR_GLM_API_KEY":
        print("==================================================")
        print("  [提示] 尚未配置有效的 GLM API Key！")
        print("  IRO_agent 严格依赖 GLM-5.3-Flash 进行诊断分析与工具调用。")
        print("  请先用记事本打开并编辑根目录下的 config.json 文件，")
        print("  在 'glm': { 'api_key': '填入您的智谱API_KEY' } 中配置后重试。")
        print("==================================================")
        return

    engine = init_agent_engine(config)

    print("==================================================")
    print("  IRO_agent 交互式工业诊断控制台 (CLI Chat)        ")
    print(f"  当前目标工程: {config.project_name}")
    print(f"  模型引擎: {config.glm.model} (在线模式)")
    print("  提示: 输入故障疑问 (如 '为什么今天系统卡住了？')，输入 'exit' 退出")
    print("==================================================")

    memory_store = IncidentStore()
    history = []

    while True:
        try:
            user_input = input("\n[现场提问] > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("退出诊断控制台。")
                break

            history.append({"role": "user", "content": user_input})
            print("\n正在查询诊断...")

            reply = engine.chat_completion(history, image_path=args.image if hasattr(args, "image") else None)
            history.append({"role": "assistant", "content": reply})

            print(reply)

            # 自动沉淀至故障记忆
            memory_store.record_incident({
                "symptom": user_input[:100],
                "user_question": user_input,
                "status": "investigated",
                "resolution_summary": reply[:300],
            })

        except (KeyboardInterrupt, EOFError):
            print("\n退出诊断控制台。")
            break
        except Exception as e:
            print(f"\n[诊断异常] {e}")


def cmd_gateway(args):
    """微信网关启停与状态查看"""
    config = get_config()
    action = args.action

    if action == "start":
        if not config.glm.api_key or config.glm.api_key == "YOUR_GLM_API_KEY":
            print("[错误] 未配置有效的 GLM API Key，无法启动微信网关服务。请先编辑 config.json 填入 api_key。")
            return
        engine = init_agent_engine(config)
        server = WeChatGatewayServer(
            host=config.wechat.listen_host,
            port=config.wechat.listen_port,
            glm_client=engine,
        )
        server.start(block=True)
    elif action == "status":
        import urllib.request
        url = f"http://127.0.0.1:{config.wechat.listen_port}"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                print(f"[Gateway 状态] 运行中 (HTTP {resp.status})")
        except Exception as e:
            print(f"[Gateway 状态] 未运行或不可达 ({e})")


def main():
    parser = argparse.ArgumentParser(description="IRO_agent - 工业软件只读智能诊断助手")
    parser.add_argument("--config", "-c", help="指定配置文件路径 (默认查找 config.json / config.example.json)")
    subparsers = parser.add_subparsers(dest="command")

    # chat
    chat_parser = subparsers.add_parser("chat", help="启动交互式只读诊断会话")
    chat_parser.add_argument("--image", "-i", help="传入待分析的现场故障截图路径")

    # config
    subparsers.add_parser("config", help="查看当前生效的配置项")

    # doctor
    subparsers.add_parser("doctor", help="执行工控机与系统环境体检")

    # gateway
    gateway_parser = subparsers.add_parser("gateway", help="微信网关服务控制")
    gateway_parser.add_argument("action", choices=["start", "status"], help="操作指令")

    args = parser.parse_args()

    if args.config:
        load_config(args.config)

    if args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "chat":
        cmd_chat(args)
    elif args.command == "gateway":
        cmd_gateway(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
