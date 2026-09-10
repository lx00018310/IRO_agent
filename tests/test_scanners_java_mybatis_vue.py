import tempfile
from pathlib import Path
from iro_agent.knowledge.scanners.sql_parser import LightweightSqlParser
from iro_agent.knowledge.scanners.java_spring import JavaSpringScanner
from iro_agent.knowledge.scanners.mybatis import MyBatisScanner
from iro_agent.knowledge.scanners.vue import VueFrontendScanner


def test_sql_parser():
    # 测试 SELECT
    sql_sel = "SELECT t.id, t.status FROM ordersys_dock_task t WHERE t.station_no = '11' ORDER BY t.id DESC"
    res_sel = LightweightSqlParser.parse(sql_sel)
    assert "ordersys_dock_task" in res_sel["read_tables"]
    assert "station_no" in res_sel["where_columns"]
    assert "id" in res_sel["order_columns"]

    # 测试 INSERT
    sql_ins = "INSERT INTO ordersys_dock_task (station_no, status) VALUES ('11', 'CREATED')"
    res_ins = LightweightSqlParser.parse(sql_ins)
    assert "ordersys_dock_task" in res_ins["write_tables"]

    # 测试 UPDATE
    sql_upd = "UPDATE ordersys_dock_task SET status = 'COMPLETED' WHERE id = 1"
    res_upd = LightweightSqlParser.parse(sql_upd)
    assert "ordersys_dock_task" in res_upd["write_tables"]
    assert "id" in res_upd["where_columns"]


def test_java_spring_and_mybatis_scanner():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        src_dir = root / "src" / "main" / "java" / "com" / "example"
        src_dir.mkdir(parents=True)
        res_dir = root / "src" / "main" / "resources" / "mapper"
        res_dir.mkdir(parents=True)

        # 写入 Java Controller
        (src_dir / "TaskController.java").write_text(
            """
package com.example;

import org.springframework.web.bind.annotation.*;
import org.springframework.beans.factory.annotation.Autowired;

@RestController
@RequestMapping("/api/tasks")
public class TaskController {

    @Autowired
    private TaskService taskService;

    @GetMapping("/latest")
    public Object getLatest() {
        return taskService.getLatest();
    }
}
""",
            encoding="utf-8",
        )

        # 写入 Java Service
        (src_dir / "TaskService.java").write_text(
            """
package com.example;

import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;

@Service
public class TaskService {

    @Autowired
    private TaskMapper taskMapper;

    public Object getLatest() {
        return taskMapper.selectLatest();
    }
}
""",
            encoding="utf-8",
        )

        # 写入 MyBatis XML
        (res_dir / "TaskMapper.xml").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN" "http://mybatis.org/dtd/mybatis-3-mapper.dtd">
<mapper namespace="com.example.TaskMapper">
    <select id="selectLatest" resultType="map">
        SELECT * FROM wms_agv_mission WHERE status = 'RUNNING' ORDER BY id DESC LIMIT 1
    </select>
</mapper>
""",
            encoding="utf-8",
        )

        # 1. 扫描 Java
        java_scanner = JavaSpringScanner(root)
        assert java_scanner.detect() is True
        java_res = java_scanner.scan()
        assert any(e.entity_type == "controller" for e in java_res.entities)
        assert any(e.entity_type == "api" and "/api/tasks/latest" in e.name for e in java_res.entities)
        assert any(r.relationship_type == "CALLS_SERVICE" for r in java_res.relationships)

        # 2. 扫描 MyBatis
        mb_scanner = MyBatisScanner(root)
        assert mb_scanner.detect() is True
        mb_res = mb_scanner.scan()
        assert any(e.entity_type == "mapper" for e in mb_res.entities)
        assert any(e.entity_type == "sql_statement" and "selectLatest" in e.name for e in mb_res.entities)
        assert any(r.relationship_type == "READS_TABLE" for r in mb_res.relationships)


def test_vue_scanner():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        api_dir = root / "src" / "api"
        api_dir.mkdir(parents=True)
        view_dir = root / "src" / "views"
        view_dir.mkdir(parents=True)

        (root / "package.json").write_text('{"name": "industrial-ui"}', encoding="utf-8")

        # 写入 API 封装
        (api_dir / "task.js").write_text(
            """
import request from '@/utils/request';

export function fetchLatestTask() {
    return request.get('/api/tasks/latest');
}
""",
            encoding="utf-8",
        )

        # 写入 Vue 组件
        (view_dir / "Dashboard.vue").write_text(
            """
<template>
  <div class="dashboard"></div>
</template>
<script>
import { fetchLatestTask } from '@/api/task';
export default {
  name: 'Dashboard',
  mounted() {
    fetchLatestTask();
  }
}
</script>
""",
            encoding="utf-8",
        )

        vue_scanner = VueFrontendScanner(root)
        assert vue_scanner.detect() is True
        res = vue_scanner.scan()
        assert any(e.name == "Dashboard" for e in res.entities)
        assert any("/api/tasks/latest" in e.metadata.get("url", "") for e in res.entities)
