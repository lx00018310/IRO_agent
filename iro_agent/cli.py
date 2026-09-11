import os
import sys
import json
import argparse
from pathlib import Path
from typing import Optional, Tuple
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
from iro_agent.gateway.feishu import FeishuGateway
from iro_agent.gateway.http_adapter import HttpGatewayAdapter

import re

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def extract_image_path(text: str) -> tuple[Optional[str], str]:
    """从用户输入中提取本地存在的图片路径（支持拖入、双引号包裹），返回 (图片路径, 剥离图片后的提问文本)"""
    # 1. 匹配双引号或单引号包裹的路径
    quoted_pattern = r'["\']([^"\']+\.(?:jpg|jpeg|png|bmp|webp))["\']'
    match = re.search(quoted_pattern, text, re.IGNORECASE)
    if match:
        candidate = Path(match.group(1).strip())
        if candidate.is_file():
            clean_text = (text[:match.start()] + " " + text[match.end():]).strip()
            return str(candidate.resolve()), clean_text or "请结合此现场图片分析故障原因并给出诊断建议。"

    # 2. 匹配无引号的路径（支持 Windows 盘符与路径，直到空格或句末）
    unquoted_pattern = r'([a-zA-Z]:[\\/][^\s<>:"|?*]+\.(?:jpg|jpeg|png|bmp|webp)|\b[^\s<>:"|?*]+\.(?:jpg|jpeg|png|bmp|webp))'
    for m in re.finditer(unquoted_pattern, text, re.IGNORECASE):
        candidate = Path(m.group(1).strip())
        if candidate.is_file():
            clean_text = (text[:m.start()] + " " + text[m.end():]).strip()
            return str(candidate.resolve()), clean_text or "请结合此现场图片分析故障原因并给出诊断建议。"

    return None, text


def _is_fault_incident(user_question: str, reply: str) -> bool:
    """判定是否属于真实故障事件，避免日常查询（如查目录、查版本）污染事故记忆库"""
    fault_keywords = [
        "报错", "异常", "故障", "卡死", "卡住", "掉线", "中断", "失败",
        "拒绝", "拒收", "暂停", "超时", "死锁", "无法", "重置", "坏了",
        "error", "exception", "failed", "crash", "timeout"
    ]
    has_fault_kw = any(kw in (user_question + " " + reply).lower() for kw in fault_keywords)
    has_diag_structure = "**核心结论**" in reply
    return has_fault_kw and has_diag_structure


def init_agent_engine(config: IROConfig) -> GlmClient:
    """组装所有只读读取器并注册到大模型/分析引擎"""
    audit = AuditLogger()
    from iro_agent.readers.version_provider import VersionReaderResolver
    version_reader, active_provider = VersionReaderResolver.resolve(config=config, audit_logger=audit)

    git_reader = GitReader(audit_logger=audit)
    code_reader = CodeReader(audit_logger=audit)
    wrelease_reader = WReleaseReader(audit_logger=audit)
    log_reader = LogReader(audit_logger=audit)
    memory_store = IncidentStore()
    db_reader = DatabaseReader(db_config=config.database, audit_logger=audit)

    from iro_agent.analyzer.orchestrator import DiagnosticOrchestrator
    orchestrator = DiagnosticOrchestrator(audit_logger=audit)

    client = GlmClient(glm_cfg=config.glm, audit_logger=audit)

    # 注册统一版本抽象工具（隔离底层 Git / WRelease 实现细节）
    client.register_tool_handler(
        "version_current",
        lambda: version_reader.get_current_version() if version_reader else {
            "version": "UNKNOWN",
            "version_type": "none",
            "is_running_detected": False,
            "pointer_source": "none",
        },
    )
    client.register_tool_handler(
        "version_recent",
        lambda limit=10: version_reader.get_recent_versions(limit=limit) if version_reader else [],
    )
    client.register_tool_handler(
        "version_compare",
        lambda ver_a, ver_b: version_reader.compare_versions(ver_a, ver_b) if version_reader else {
            "from_release": ver_a,
            "to_release": ver_b,
            "has_changes": False,
        },
    )
    client.register_tool_handler(
        "version_events",
        lambda start_time=None, end_time=None: version_reader.get_version_events(start_time=start_time, end_time=end_time) if version_reader else [],
    )
    client.register_tool_handler("log_search", lambda **kwargs: log_reader.search_logs(**kwargs))
    client.register_tool_handler("code_search", lambda query: code_reader.search_code(query))
    from iro_agent.knowledge.lookup import ProjectLookupEngine
    from iro_agent.knowledge.store import ProjectKnowledgeStore
    knowledge_store = ProjectKnowledgeStore(base_dir=Path(config.project_root) if Path(config.project_root).exists() else Path.cwd())
    lookup_engine = ProjectLookupEngine(store=knowledge_store)

    from iro_agent.knowledge.code_graph import CodeRelationshipGraph

    def _trace_api(api_path: str):
        bp = knowledge_store.load_blueprint()
        if bp and bp.metadata.get("code_graph"):
            graph = CodeRelationshipGraph.from_dict(bp.metadata["code_graph"])
            return graph.trace_api_to_table(api_path)
        return {"error": "未发现已构建的代码关系图，请先运行 iro-agent init 进行知识提炼。"}

    def _table_usage(table_name: str):
        bp = knowledge_store.load_blueprint()
        if bp and bp.metadata.get("code_graph"):
            graph = CodeRelationshipGraph.from_dict(bp.metadata["code_graph"])
            return graph.find_table_usage(table_name)
        return {"error": "未发现已构建的代码关系图，请先运行 iro-agent init 进行知识提炼。"}

    client.register_tool_handler("code_trace_api_to_table", _trace_api)
    client.register_tool_handler("code_find_table_usage", _table_usage)
    client.register_tool_handler("project_lookup", lambda query: lookup_engine.lookup(query))
    client.register_tool_handler("config_lookup", lambda query, limit=5: lookup_engine.config_lookup(query, limit=limit))
    client.register_tool_handler("flow_lookup", lambda query, limit=3: lookup_engine.flow_lookup(query, limit=limit))
    client.register_tool_handler("module_lookup", lambda query: lookup_engine.module_lookup(query))

    from iro_agent.memory.learning_store import LearningMemoryStore
    learning_store = LearningMemoryStore()
    client.register_tool_handler("learning_save", lambda **kwargs: learning_store.save_rule(kwargs))
    client.register_tool_handler("learning_recall", lambda query, limit=5: learning_store.recall_rules(query, limit=limit))
    client.register_tool_handler("learning_list", lambda topic=None, status="active": learning_store.list_rules(topic=topic, status=status))

    client.register_tool_handler("db_list_tables", lambda: db_reader.list_tables())
    client.register_tool_handler("db_describe_table", lambda table_name: db_reader.describe_table(table_name))
    client.register_tool_handler("db_query", lambda query, max_rows=20: db_reader.execute_query(query, max_rows=max_rows))
    client.register_tool_handler("diagnostic_pipeline", lambda symptom, log_keyword=None, user_message_time=None: orchestrator.run_pipeline(symptom=symptom, log_keyword=log_keyword, user_message_time=user_message_time))

    from iro_agent.investigation.harness import InvestigationHarness
    inv_harness = InvestigationHarness(audit_logger=audit)

    def _run_inv(symptom: str, **kwargs):
        rep = inv_harness.investigate(symptom=symptom)
        return {
            "primary_root_cause": rep.primary_root_cause,
            "confidence": rep.confidence,
            "key_evidence": rep.key_evidence,
            "physical_checklist": rep.physical_escalation_checklist,
            "stop_reason": rep.stop_reason,
            "human_response": inv_harness.format_human_response(rep),
        }

    client.register_tool_handler("investigation_pipeline", _run_inv)

    from iro_agent.readers.web_reader import WebReader
    web_reader = WebReader(audit_logger=audit)
    client.register_tool_handler("web_fetch", lambda **kwargs: web_reader.fetch_page(**kwargs))

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

    # 6. 版本提供者决议 (二选一)
    from iro_agent.readers.version_provider import VersionReaderResolver
    _, active_prov = VersionReaderResolver.resolve(config=config)
    checks.append(("当前活跃版本源 (二选一)", active_prov, active_prov != "None"))

    # 7. SQLite 数据库
    audit_ok = False
    try:
        al = AuditLogger()
        audit_ok = True
    except Exception:
        pass
    checks.append(("审计与记忆数据库 (SQLite)", "正常初始化", audit_ok))

    # 8. GLM 模型接口状态
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
    """查看当前生效配置（强制敏感凭证脱敏）"""
    import copy
    config = get_config()
    cfg_data = copy.deepcopy(config.model_dump())

    def _mask_sensitive(d: dict):
        sensitive_keys = {"password", "api_key", "token", "aes_key", "secret", "private_key", "app_secret"}
        for k, v in d.items():
            if isinstance(v, dict):
                _mask_sensitive(v)
            elif isinstance(v, str) and (k.lower() in sensitive_keys or "secret" in k.lower() or "key" in k.lower()) and v:
                d[k] = "********"

    _mask_sensitive(cfg_data)
    print("==================================================")
    print("  IRO_agent 当前有效配置 (敏感字段已自动掩码脱敏)   ")
    print("==================================================")
    print(json.dumps(cfg_data, indent=2, ensure_ascii=False))


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

    from iro_agent.memory.learning_store import LearningMemoryStore
    from iro_agent.memory.correction_detector import CorrectionDetector
    from iro_agent.router.intent_router import IntentRouter

    learning_store = LearningMemoryStore()
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

            extracted_img, clean_prompt = extract_image_path(user_input)
            img_to_use = extracted_img or (args.image if hasattr(args, "image") else None)

            if extracted_img:
                print(f"[已识别现场截图]: {extracted_img}")

            # 1. 纠错与显式记忆指示拦截检测 (落实记忆诚实原则)
            correction = CorrectionDetector.detect(clean_prompt)
            if correction:
                try:
                    rule_id = learning_store.save_rule({
                        "project": config.project_name,
                        "rule_type": correction["rule_type"],
                        "topic": correction["topic"],
                        "rule_text": correction["rule_text"],
                        "reason": correction["reason"],
                        "source_type": "user_correction",
                        "confidence": "confirmed",
                    })
                    reply = CorrectionDetector.format_honesty_response(rule_id=rule_id, rule_text=correction["rule_text"])
                except Exception as e:
                    reply = CorrectionDetector.format_honesty_response(rule_id=None, rule_text=correction["rule_text"], error=str(e))

                print(f"\n[大模型诊断回复]:\n{reply}")
                history.append({"role": "user", "content": clean_prompt})
                history.append({"role": "assistant", "content": reply})
                continue

            # 2. 查询意图识别与前置学习记忆召回
            intent_res = IntentRouter.route(clean_prompt)
            print(f"[意图路由] 判定为: {intent_res['intent'].value} (置信度: {intent_res['confidence']:.2f}) | {intent_res['execution_strategy']}")

            recalled_rules = learning_store.recall_rules(clean_prompt, project=config.project_name, limit=3)
            prompt_to_send = clean_prompt
            if recalled_rules:
                rules_str = "\n".join(f"- {r['rule_text']} (领域: {r['topic']}, 依据: {r['reason']})" for r in recalled_rules)
                print(f"[前置记忆召回] 命中 {len(recalled_rules)} 条历史学习规则，已作为最高准则注入本次排查")
                prompt_to_send = f"【历史已确认学习规则提示（排查必须严格遵守此原则）】:\n{rules_str}\n\n现场提问: {clean_prompt}"

            history.append({"role": "user", "content": prompt_to_send})
            print("\n正在查询诊断...")

            reply = engine.chat_completion(history, image_path=img_to_use, verbose=True)
            history.append({"role": "assistant", "content": reply})

            print(f"\n[大模型诊断回复]:\n{reply}")

            # 故障记忆由 DiagnosticOrchestrator 在诊断流水线中统一单点沉淀，CLI 仅负责呈现，杜绝重复记录

        except (KeyboardInterrupt, EOFError):
            print("\n退出诊断控制台。")

            break
        except Exception as e:
            print(f"\n[诊断异常] {e}")


def run_gateway_doctor(config: IROConfig):
    """网关环境与链路专项健康检查 (严格屏蔽 Secret)"""
    print("==================================================")
    print("  IRO_agent 网关健康体检 (Gateway Doctor)         ")
    print("==================================================")

    checks = []

    # 1. 飞书 App ID
    app_id_ok = bool(config.feishu.app_id and config.feishu.app_id != "YOUR_FEISHU_APP_ID")
    checks.append(("FEISHU_APP_ID configured", f"已配置 ({config.feishu.app_id[:6]}***)" if app_id_ok else "未配置或为默认占位符", app_id_ok))

    # 2. 飞书 App Secret (严格掩码)
    app_secret_ok = bool(config.feishu.app_secret and config.feishu.app_secret != "YOUR_FEISHU_APP_SECRET")
    checks.append(("FEISHU_APP_SECRET configured", "已配置 (********)" if app_secret_ok else "未配置或为默认占位符", app_secret_ok))

    # 3. GLM API
    glm_ok = bool(config.glm.api_key and config.glm.api_key != "YOUR_GLM_API_KEY")
    checks.append(("GLM API reachable", f"已就绪 (模型: {config.glm.model})" if glm_ok else "未配置有效的 API Key", glm_ok))

    # 4. Project
    proj_ok = bool(config.project_name and os.path.exists(config.project_root))
    checks.append((f"{config.project_name} project configured", f"路径存在 ({config.project_root})" if proj_ok else f"路径不可达 ({config.project_root})", proj_ok))

    # 5. Version Provider
    from iro_agent.readers.version_provider import VersionReaderResolver
    audit = AuditLogger()
    v_reader, active_provider = VersionReaderResolver.resolve(config=config, audit_logger=audit)
    v_ok = active_provider != "None"
    checks.append((f"Version provider: {active_provider}", "激活成功" if v_ok else "无可用版本源", v_ok))

    # 6. LogReader path
    log_paths_ok = any(os.path.exists(d) for d in config.log_dirs)
    checks.append(("LogReader path readable", "日志目录可读" if log_paths_ok else "未发现有效日志目录", log_paths_ok))

    # 7. Database read-only connection
    db_reader = DatabaseReader(db_config=config.database, audit_logger=audit)
    db_ok = db_reader.test_connection()
    checks.append(("Database read-only connection", "连接成功 (只读)" if db_ok else "不可达或未启动", db_ok))

    # 8. Incident database writable
    mem_ok = os.path.exists(config.storage.memory_db_path)
    checks.append(("Incident database writable", "SQLite 可读写" if mem_ok else "未初始化", mem_ok))

    # 9. Feishu client initialized
    feishu_client_ok = False
    if app_id_ok and app_secret_ok:
        try:
            gw = FeishuGateway(config=config)
            feishu_client_ok = gw.client is not None
        except Exception:
            feishu_client_ok = False
    checks.append(("Feishu client initialized", "OpenAPI 客户端就绪" if feishu_client_ok else "未就绪 (凭据缺失或异常)", feishu_client_ok))

    for name, detail, passed in checks:
        status_icon = "[OK]" if passed else "[FAIL]"
        print(f"{status_icon:8} {name:32}: {detail}")

    print("==================================================")
    return all(c[2] for c in checks)


def cmd_gateway(args):
    """网关服务控制与状态体检"""
    config = get_config()
    action = args.action

    if action == "doctor":
        run_gateway_doctor(config)
        return

    gw_type = getattr(args, "type", None) or config.gateway.type or "feishu"

    if action == "start":
        if not config.glm.api_key or config.glm.api_key == "YOUR_GLM_API_KEY":
            print("[错误] 未配置有效的 GLM API Key，无法启动网关服务。请先编辑 config.json 填入 api_key。")
            return

        engine = init_agent_engine(config)

        if gw_type == "feishu":
            if not config.feishu.app_id or not config.feishu.app_secret:
                print("[错误] 未配置 FEISHU_APP_ID 或 FEISHU_APP_SECRET，无法启动飞书长连接网关。")
                print("请在 config.json 中配置 feishu.app_id 和 feishu.app_secret，或设置环境变量。")
                return
            gateway = FeishuGateway(config=config, glm_client=engine)
            gateway.start(block=True)
        elif gw_type == "http":
            adapter = HttpGatewayAdapter(
                host=config.gateway.listen_host,
                port=config.gateway.listen_port,
                glm_client=engine,
            )
            adapter.start(block=True)
        else:
            print(f"[错误] 未知的网关类型: {gw_type}")

    elif action == "status":
        if gw_type == "feishu":
            gw = FeishuGateway(config=config)
            info = gw.health()
            print(f"[Feishu Gateway 状态] 配置就绪: {info['app_id_configured']}, 长连接就绪: {info['websocket_client_ready']}")
        elif gw_type == "http":
            import urllib.request
            url = f"http://127.0.0.1:{config.gateway.listen_port}"
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    print(f"[Http Gateway 状态] 运行中 (HTTP {resp.status})")
            except Exception as e:
                print(f"[Http Gateway 状态] 未运行或不可达 ({e})")


def cmd_init(args):
    """初始化或刷新目标工业系统的项目业务蓝图"""
    config = get_config()
    if getattr(args, "project", None):
        config.project_name = args.project
    from iro_agent.knowledge.bootstrap import ProjectKnowledgeBootstrapper
    bootstrapper = ProjectKnowledgeBootstrapper(config)
    bootstrapper.run_bootstrap(
        refresh=getattr(args, "refresh", False),
        static_only=getattr(args, "static_only", False),
    )


def cmd_eval(args):
    """基准评测运行器入口"""
    if not getattr(args, "subcommand", None):
        print("请指定评测子命令: dev / regression / external")
        return
    from iro_agent.evaluation.runner import EvaluationRunner
    runner = EvaluationRunner(
        dataset_type=args.subcommand,
        custom_path=getattr(args, "dataset", None),
    )
    summary = runner.run(
        category=getattr(args, "category", None),
        case_id=getattr(args, "case", None),
        repeat=getattr(args, "repeat", 1),
        verbose=getattr(args, "verbose", False),
    )
    print("\n==================================================")
    print(f"  [Evaluation Run: {summary.run_id}] 评测完成")
    print(f"  数据集类型: {summary.dataset_type.upper()}")
    print(f"  用例总数: {summary.total_cases} | 通过: {summary.passed_cases} | 失败: {summary.failed_cases} | 异常: {summary.error_cases}")
    print(f"  平均综合得分: {summary.average_score * 100:.2f}%")
    print(f"  安全违规数: {summary.safety_violations}")
    print(f"  详细报告已保存至: .eval_runs/{summary.run_id}/report.md")
    print("==================================================")


def main():
    parser = argparse.ArgumentParser(description="IRO_agent - 工业软件只读智能诊断助手")
    parser.add_argument("--config", "-c", help="指定配置文件路径 (默认查找 config.json / config.example.json)")
    subparsers = parser.add_subparsers(dest="command")

    # init
    init_parser = subparsers.add_parser("init", help="初始化或刷新目标工程的业务认知蓝图 (Project Knowledge Bootstrap)")
    init_parser.add_argument("--project", "-p", help="指定目标工程标识/名称")
    init_parser.add_argument("--refresh", "-r", action="store_true", help="强制重新扫描并刷新已有知识蓝图")
    init_parser.add_argument("--static-only", action="store_true", help="仅执行纯静态扫描与启发式推断，不发起 GLM 模型调用")


    # chat
    chat_parser = subparsers.add_parser("chat", help="启动交互式只读诊断会话")
    chat_parser.add_argument("--image", "-i", help="传入待分析的现场故障截图路径")

    # config
    subparsers.add_parser("config", help="查看当前生效的配置项")

    # doctor
    subparsers.add_parser("doctor", help="执行工控机与系统环境体检")

    # gateway
    gateway_parser = subparsers.add_parser("gateway", help="网关服务控制 (飞书机器人/开发测试适配器)")
    gateway_parser.add_argument("action", choices=["start", "status", "doctor"], help="操作指令")
    gateway_parser.add_argument("--type", choices=["feishu", "http"], default=None, help="指定网关类型 (默认使用配置项)")

    # eval
    eval_parser = subparsers.add_parser("eval", help="执行工业故障诊断基准评测 (Evaluation Harness)")
    eval_subparsers = eval_parser.add_subparsers(dest="subcommand")

    for dt in ["dev", "regression"]:
        p = eval_subparsers.add_parser(dt, help=f"运行 {dt} 评测集")
        p.add_argument("--category", help="按案例故障类别过滤")
        p.add_argument("--case", help="指定单个案例ID")
        p.add_argument("--repeat", type=int, default=1, help="用例重复运行轮次")
        p.add_argument("--verbose", "-v", action="store_true", help="打印详细排查过程")

    ext_p = eval_subparsers.add_parser("external", help="运行外部私有盲测集 (External Blind Dataset)")
    ext_p.add_argument("--dataset", required=True, help="外部私有评测集目录路径")
    ext_p.add_argument("--category", help="按案例故障类别过滤")
    ext_p.add_argument("--case", help="指定单个案例ID")
    ext_p.add_argument("--repeat", type=int, default=1, help="用例重复运行轮次")
    ext_p.add_argument("--verbose", "-v", action="store_true", help="打印详细排查过程")

    args = parser.parse_args()

    if args.config:
        load_config(args.config)

    if args.command == "init":
        cmd_init(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "config":
        cmd_config(args)
    elif args.command == "chat":
        cmd_chat(args)
    elif args.command == "gateway":
        cmd_gateway(args)
    elif args.command == "eval":
        cmd_eval(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
