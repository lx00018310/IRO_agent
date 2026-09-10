import tempfile
from pathlib import Path
from iro_agent.knowledge.bootstrap import ProjectKnowledgeBootstrapper
from iro_agent.knowledge.lookup import ProjectLookupEngine
from iro_agent.knowledge.store import ProjectKnowledgeStore
from iro_agent.config import get_config


def test_generic_industrial_project_bootstrap():
    """第二工业系统泛化测试 (全链路非TASK-013项目: Java Spring + MyBatis + Vue 自动化立体仓储)"""

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        java_dir = root / "src" / "main" / "java" / "com" / "wms"
        java_dir.mkdir(parents=True)
        res_dir = root / "src" / "main" / "resources" / "mapper"
        res_dir.mkdir(parents=True)
        vue_dir = root / "frontend" / "src" / "api"
        vue_dir.mkdir(parents=True)

        # 1. 写入 Spring Boot Controller
        (java_dir / "AgvMissionController.java").write_text(
            """
package com.wms;

import org.springframework.web.bind.annotation.*;
import org.springframework.beans.factory.annotation.Autowired;

@RestController
@RequestMapping("/api/agv")
public class AgvMissionController {

    @Autowired
    private AgvMissionService agvService;

    @GetMapping("/current-mission")
    public Object getCurrentMission() {
        return agvService.getCurrentMission();
    }
}
""",
            encoding="utf-8",
        )

        # 2. 写入 Spring Boot Service
        (java_dir / "AgvMissionService.java").write_text(
            """
package com.wms;

import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;

@Service
public class AgvMissionService {

    @Autowired
    private AgvMissionMapper agvMapper;

    public Object getCurrentMission() {
        return agvMapper.selectCurrentMission();
    }
}
""",
            encoding="utf-8",
        )

        # 3. 写入 MyBatis XML (读写 wms_agv_mission 表)
        (res_dir / "AgvMissionMapper.xml").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN" "http://mybatis.org/dtd/mybatis-3-mapper.dtd">
<mapper namespace="com.wms.AgvMissionMapper">
    <select id="selectCurrentMission" resultType="map">
        SELECT id, current_agv_slot, status, created_at FROM wms_agv_mission WHERE status = 'RUNNING' ORDER BY id DESC LIMIT 1
    </select>
    <insert id="insertCallback">
        INSERT INTO wms_agv_callback_receipt (mission_id, received_at) VALUES (1, NOW())
    </insert>
</mapper>
""",
            encoding="utf-8",
        )

        # 4. 写入 Vue 前端 API
        (vue_dir / "agv.js").write_text(
            """
import request from '@/utils/request';

export function getAgvCurrent() {
    return request.get('/api/agv/current-mission');
}
""",
            encoding="utf-8",
        )
        (root / "package.json").write_text('{"name": "wms-ui"}', encoding="utf-8")

        # 5. 执行项目认知初始化 (Bootstrap)
        cfg = get_config()
        orig_root = cfg.project_root
        orig_name = cfg.project_name
        try:
            cfg.project_root = str(root)
            cfg.project_name = "SMART_WMS_AGV"

            bootstrapper = ProjectKnowledgeBootstrapper(config=cfg)
            bp = bootstrapper.run_bootstrap(refresh=True, use_llm=False)

            # 验证技术栈与基础解析
            assert bp.project.project_name == "SMART_WMS_AGV"
            table_names = [t.table_name for t in bp.database_tables]
            assert "wms_agv_mission" in table_names
            assert "wms_agv_callback_receipt" in table_names

            # 验证表角色自动识别
            mission_tbl = next(t for t in bp.database_tables if t.table_name == "wms_agv_mission")
            assert mission_tbl.table_type == "current_state"
            callback_tbl = next(t for t in bp.database_tables if t.table_name == "wms_agv_callback_receipt")
            assert callback_tbl.table_type == "callback"

            # 验证代码关系图已完整构建
            store = ProjectKnowledgeStore(base_dir=root)
            engine = ProjectLookupEngine(store=store)

            # 执行业务提问对齐检索
            res = engine.lookup("查询当前车辆或最新AGV调度状态")
            assert res["status"] == "SUCCESS"
            assert len(res["concepts"]) >= 1

            # 确认主数据源推断为 wms_agv_mission
            top_concept = res["concepts"][0]
            assert top_concept["canonical_source"]["table"] == "wms_agv_mission"

            # 确认警告中包含了严禁以回执表为主的避坑防护
            warning_str = " ".join(res["warnings"])
            assert "wms_agv_callback_receipt" in warning_str

            # 确认查询接口路径时能追溯到对应表
            res_api = engine.lookup("排查接口 /api/agv/current-mission 写到哪张表")
            assert "wms_agv_mission" in res_api["code_relationships"] or any("api_trace" in k for k in res_api["code_relationships"])

        finally:
            cfg.project_root = orig_root
            cfg.project_name = orig_name
