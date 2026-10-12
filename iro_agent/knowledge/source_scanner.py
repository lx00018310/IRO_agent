"""Collect all registered source roots into one project's bootstrap evidence."""

from pathlib import Path

from iro_agent.knowledge.code_scanner import TargetedCodeScanner, CodeScanResult
from iro_agent.knowledge.config_catalog import ConfigCatalogScanner
from iro_agent.knowledge.schema_scanner import SchemaScanner, SchemaScanResult
from iro_agent.knowledge.tree_scanner import TreeScanner, TreeScanResult
from iro_agent.readers.sources import SourceReaders


def collect_source_evidence(config):
    tree = TreeScanResult(project_root=config.project_root)
    schema = SchemaScanResult()
    code = CodeScanResult(code_graph={"entities": [], "edges": []})
    items, rules, statuses = [], [], []
    readers = SourceReaders(config)
    for source in config.sources.code:
        root = Path(source.path)
        try:
            readers._require_directory(root)
            scanned_tree = TreeScanner(root).scan()
            tree.total_files += scanned_tree.total_files
            for extension, count in scanned_tree.extension_counts.items():
                tree.extension_counts[extension] = tree.extension_counts.get(extension, 0) + count
            tree.frameworks = sorted(set(tree.frameworks + scanned_tree.frameworks))
            tree.top_level_modules.append(source.id)
            for field in ("key_directories", "startup_scripts", "deployment_scripts", "entry_points"):
                getattr(tree, field).extend(f"{source.id}/{p}" for p in getattr(scanned_tree, field))
            source_items, source_rules = ConfigCatalogScanner(root).scan()
            for item in source_items:
                item.config_id = f"{source.id}:{item.config_id}"
                item.relative_path = f"{source.id}/{item.relative_path}"
                item.source_id = source.id
            items.extend(source_items)
            rules.extend(source_rules)
            scanned_code = TargetedCodeScanner(root).scan()
            for entity in scanned_code.entities:
                entity.file_path = str((root / entity.file_path).resolve())
                entity.source_id = source.id
                code.entities.append(entity)
            for enum in scanned_code.enums:
                code.enums.append({**enum, "file_path": str((root / enum["file_path"]).resolve()), "source_id": source.id})
            code.detected_models_count += scanned_code.detected_models_count
            code.scanned_files_count += scanned_code.scanned_files_count
            graph = scanned_code.code_graph or {}
            from iro_agent.knowledge.code_graph import CodeRelationshipGraph
            local_graph = CodeRelationshipGraph.from_dict(graph)
            for node in graph.get("entities", []):
                node["entity_id"] = f"{source.id}::{node['entity_id']}"
                if node.get("file_path"):
                    node["file_path"] = str((root / node["file_path"]).resolve())
                node.setdefault("metadata", {})["source_id"] = source.id
                code.code_graph["entities"].append(node)
            for edge in graph.get("edges", []):
                for field in ("source_entity_id", "target_entity_id"):
                    edge[field] = f"{source.id}::{local_graph.resolve_entity_id(edge[field])}"
                evidence = edge.get("evidence")
                if evidence and evidence.get("file_path"):
                    evidence["file_path"] = str((root / evidence["file_path"]).resolve())
                edge.setdefault("metadata", {})["source_id"] = source.id
                code.code_graph["edges"].append(edge)
            statuses.append({"source_id": source.id, "status": "OK"})
        except Exception as exc:
            statuses.append({"source_id": source.id, "status": "UNAVAILABLE", "error": str(exc)})
    languages = {"Python": tree.extension_counts.get(".py", 0),
                 "Java": tree.extension_counts.get(".java", 0),
                 "JavaScript/TypeScript": sum(tree.extension_counts.get(ext, 0) for ext in (".js", ".ts", ".vue"))}
    tree.primary_language = max(languages, key=languages.get) if any(languages.values()) else "unknown"
    schema.database_name = ", ".join(s.id for s in config.sources.databases)
    for source in config.sources.databases:
        try:
            result = SchemaScanner(db_config=source.connection_config()).scan()
            if not result.connected:
                raise RuntimeError(result.error or "数据库 schema 不可用")
            for table in result.tables:
                table.source_id = source.id
                schema.tables.append(table)
            schema.source_status[source.id] = "OK"
            statuses.append({"source_id": source.id, "status": "OK"})
        except Exception as exc:
            schema.source_status[source.id] = "UNAVAILABLE"
            statuses.append({"source_id": source.id, "status": "UNAVAILABLE", "error": str(exc)})
    schema.connected = bool(schema.source_status) and all(s == "OK" for s in schema.source_status.values())
    return tree, schema, code, items, rules, readers._clean(statuses)
