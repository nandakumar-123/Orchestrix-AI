from __future__ import annotations

import logging
import re

from app.db.models.repository_intelligence import (
    CodeSymbol,
    FileDependency,
    RepositoryFile,
    RepositorySnapshot,
)
from app.services.graph_service import GraphNode, GraphRelationship
from app.services.symbol_resolution import SymbolResolutionEngine

logger = logging.getLogger("orchestrix.relationship_extraction")

# Regular expressions for syntactic heuristics across languages
HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}
API_ROUTE_PATTERN = re.compile(
    r"""(?:@(?:app|router|api)\.(get|post|put|delete|patch)|(?:app|router)\.(get|post|put|delete|patch))\s*\(\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
TABLE_NAME_PATTERN = re.compile(
    r"""__tablename__\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
CALL_PATTERN = re.compile(
    r"""\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(""",
)
BASE_CLASS_PY_PATTERN = re.compile(r"""class\s+[a-zA-Z_][a-zA-Z0-9_]*\s*\(([^)]+)\):""")
EXTENDS_TS_PATTERN = re.compile(r"""class\s+[a-zA-Z_][a-zA-Z0-9_]*\s+extends\s+([a-zA-Z0-9_]+)""")
IMPLEMENTS_PATTERN = re.compile(r"""(?:implements|:\s*public)\s+([a-zA-Z0-9_,\s]+)""")


class MultiLanguageRelationshipExtractor:
    """
    Extracts multi-language graph nodes and relationships across AST symbols,
    file dependencies, call sites, API endpoints, database models, and test cases.
    """

    def __init__(
        self,
        snapshot: RepositorySnapshot,
        files: list[RepositoryFile],
        symbols: list[CodeSymbol],
        dependencies: list[FileDependency],
        file_contents: dict[str, str] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.snapshot_id = str(snapshot.id)
        self.repository_id = str(snapshot.repository_id)
        self.files = files
        self.symbols = symbols
        self.dependencies = dependencies
        self.file_contents = file_contents or {}
        self.resolver = SymbolResolutionEngine(
            snapshot_id=self.snapshot_id,
            files=files,
            symbols=symbols,
            dependencies=dependencies,
        )

    def extract_all(self) -> tuple[list[GraphNode], list[GraphRelationship]]:
        """
        Execute full extraction pipeline:
        1. Repository & Snapshot nodes
        2. File nodes & CONTAINS
        3. Symbol nodes (Function, Method, Class, Interface, Struct, Enum)
        4. Dependency & Import relationships
        5. Inheritance & Implementation relationships (EXTENDS, IMPLEMENTS)
        6. Call graph relationships (CALLS)
        7. API Endpoint nodes & EXPOSES
        8. Database Model & Table nodes (DEFINES, READS_FROM, WRITES_TO)
        9. Test Case nodes & TESTS
        """
        nodes: list[GraphNode] = []
        relationships: list[GraphRelationship] = []

        # 1. Repository & Snapshot Nodes
        repo_node_id = f"repo:{self.repository_id}"
        snap_node_id = f"snap:{self.snapshot_id}"

        nodes.append(
            GraphNode(
                id=repo_node_id,
                label="Repository",
                properties={
                    "repository_id": self.repository_id,
                    "commit_sha": self.snapshot.commit_sha,
                },
            )
        )
        nodes.append(
            GraphNode(
                id=snap_node_id,
                label="RepositorySnapshot",
                properties={
                    "snapshot_id": self.snapshot_id,
                    "repository_id": self.repository_id,
                    "commit_sha": self.snapshot.commit_sha,
                    "branch": self.snapshot.branch,
                },
            )
        )
        relationships.append(
            GraphRelationship(
                source_id=repo_node_id,
                target_id=snap_node_id,
                type="CONTAINS",
                properties={"snapshot_id": self.snapshot_id},
            )
        )

        # 2. File Nodes
        file_node_map: dict[str, str] = {}
        for f in self.files:
            file_node_id = f"file:{self.snapshot_id}:{f.path}"
            file_node_map[f.path] = file_node_id
            nodes.append(
                GraphNode(
                    id=file_node_id,
                    label="File",
                    properties={
                        "snapshot_id": self.snapshot_id,
                        "file_id": str(f.id),
                        "file_path": f.path,
                        "file_name": f.file_name,
                        "language": f.language or "Unknown",
                        "line_count": f.line_count,
                        "size_bytes": f.size_bytes,
                    },
                )
            )
            relationships.append(
                GraphRelationship(
                    source_id=snap_node_id,
                    target_id=file_node_id,
                    type="CONTAINS",
                    properties={"snapshot_id": self.snapshot_id},
                )
            )

        # 3. Symbol Nodes & File CONTAINS
        symbol_node_map: dict[str, str] = {}
        class_node_map: dict[str, str] = {}
        for s in self.symbols:
            label = self._map_symbol_label(s.symbol_type)
            sym_node_id = f"sym:{self.snapshot_id}:{s.file_path}:{s.symbol_type}:{s.name}"
            symbol_node_map[f"{s.file_path}:{s.name}"] = sym_node_id
            if s.symbol_type == "class":
                class_node_map[f"{s.file_path}:{s.name}"] = sym_node_id

            nodes.append(
                GraphNode(
                    id=sym_node_id,
                    label=label,
                    properties={
                        "snapshot_id": self.snapshot_id,
                        "symbol_id": str(s.id),
                        "name": s.name,
                        "file_path": s.file_path,
                        "symbol_type": s.symbol_type,
                        "language": s.language,
                        "start_line": s.start_line,
                        "end_line": s.end_line,
                        "signature": s.signature or "",
                        "parent_symbol_name": s.parent_symbol_name or "",
                    },
                )
            )

            parent_file_id = file_node_map.get(s.file_path)
            if parent_file_id:
                relationships.append(
                    GraphRelationship(
                        source_id=parent_file_id,
                        target_id=sym_node_id,
                        type="CONTAINS",
                        properties={"snapshot_id": self.snapshot_id},
                    )
                )

            # Class CONTAINS Method
            if s.parent_symbol_name:
                parent_sym_key = f"{s.file_path}:{s.parent_symbol_name}"
                parent_class_node_id = symbol_node_map.get(parent_sym_key)
                if parent_class_node_id:
                    relationships.append(
                        GraphRelationship(
                            source_id=parent_class_node_id,
                            target_id=sym_node_id,
                            type="CONTAINS",
                            properties={"snapshot_id": self.snapshot_id},
                        )
                    )

        # 4. Dependency & Import Relationships
        for dep in self.dependencies:
            source_file_id = file_node_map.get(dep.source_file_path)
            if not source_file_id:
                continue

            if dep.dependency_type == "import":
                # Check if internal file or external
                target_file_path = self.resolver._normalize_import_path(
                    dep.source_file_path, dep.name
                )
                if target_file_path and target_file_path in file_node_map:
                    target_file_id = file_node_map[target_file_path]
                    relationships.append(
                        GraphRelationship(
                            source_id=source_file_id,
                            target_id=target_file_id,
                            type="IMPORTS",
                            properties={
                                "snapshot_id": self.snapshot_id,
                                "status": "resolved",
                                "raw_statement": dep.name,
                            },
                        )
                    )
                else:
                    # External dependency node
                    ext_node_id = f"dep:{dep.name}"
                    nodes.append(
                        GraphNode(
                            id=ext_node_id,
                            label="ExternalDependency",
                            properties={
                                "name": dep.name,
                                "is_external": True,
                            },
                        )
                    )
                    relationships.append(
                        GraphRelationship(
                            source_id=source_file_id,
                            target_id=ext_node_id,
                            type="IMPORTS",
                            properties={
                                "snapshot_id": self.snapshot_id,
                                "status": "resolved",
                                "raw_statement": dep.name,
                            },
                        )
                    )
            elif dep.dependency_type in ("package_dependency", "dev_dependency"):
                pkg_node_id = f"pkg:{dep.name}:{dep.version_spec or 'latest'}"
                nodes.append(
                    GraphNode(
                        id=pkg_node_id,
                        label="Package",
                        properties={
                            "name": dep.name,
                            "version": dep.version_spec or "",
                            "package_manager": dep.package_manager or "",
                        },
                    )
                )
                relationships.append(
                    GraphRelationship(
                        source_id=source_file_id,
                        target_id=pkg_node_id,
                        type="DEPENDS_ON",
                        properties={
                            "snapshot_id": self.snapshot_id,
                            "version_spec": dep.version_spec,
                            "dependency_type": dep.dependency_type,
                        },
                    )
                )

        # 5. Inheritance (EXTENDS) & Interface Implementation (IMPLEMENTS)
        for s in self.symbols:
            if s.symbol_type == "class" and s.signature:
                class_node_id = symbol_node_map.get(f"{s.file_path}:{s.name}")
                if not class_node_id:
                    continue

                # Python inheritance: class Foo(Bar, Baz):
                py_match = BASE_CLASS_PY_PATTERN.search(s.signature)
                if py_match:
                    bases_raw = py_match.group(1).split(",")
                    for base in bases_raw:
                        base_name = base.strip().split(".")[-1].strip()
                        if base_name and base_name not in ("object", "BaseModel", "Base"):
                            resolved = self.resolver.resolve_symbol(
                                source_file=s.file_path,
                                symbol_name=base_name,
                                target_type="class",
                            )
                            if resolved.target_id:
                                relationships.append(
                                    GraphRelationship(
                                        source_id=class_node_id,
                                        target_id=resolved.target_id,
                                        type="EXTENDS",
                                        properties={
                                            "snapshot_id": self.snapshot_id,
                                            "status": resolved.status,
                                            "resolution_type": resolved.resolution_type,
                                            "confidence": resolved.confidence,
                                        },
                                    )
                                )

                # TypeScript/Java/C++ extends
                ts_match = EXTENDS_TS_PATTERN.search(s.signature)
                if ts_match:
                    base_name = ts_match.group(1).strip()
                    resolved = self.resolver.resolve_symbol(
                        source_file=s.file_path,
                        symbol_name=base_name,
                        target_type="class",
                    )
                    if resolved.target_id:
                        relationships.append(
                            GraphRelationship(
                                source_id=class_node_id,
                                target_id=resolved.target_id,
                                type="EXTENDS",
                                properties={
                                    "snapshot_id": self.snapshot_id,
                                    "status": resolved.status,
                                    "resolution_type": resolved.resolution_type,
                                    "confidence": resolved.confidence,
                                },
                            )
                        )

                # Implements pattern
                impl_match = IMPLEMENTS_PATTERN.search(s.signature)
                if impl_match:
                    interfaces_raw = impl_match.group(1).split(",")
                    for iface in interfaces_raw:
                        iface_name = iface.strip()
                        if iface_name:
                            resolved = self.resolver.resolve_symbol(
                                source_file=s.file_path,
                                symbol_name=iface_name,
                            )
                            if resolved.target_id:
                                relationships.append(
                                    GraphRelationship(
                                        source_id=class_node_id,
                                        target_id=resolved.target_id,
                                        type="IMPLEMENTS",
                                        properties={
                                            "snapshot_id": self.snapshot_id,
                                            "status": resolved.status,
                                            "resolution_type": resolved.resolution_type,
                                            "confidence": resolved.confidence,
                                        },
                                    )
                                )

        # 6. Call Graph Relationships (CALLS) & Test Case detection (TESTS)
        for s in self.symbols:
            if s.symbol_type not in ("function", "method"):
                continue

            caller_node_id = symbol_node_map.get(f"{s.file_path}:{s.name}")
            if not caller_node_id:
                continue

            # Check if this function is a Test Case
            is_test = (
                s.name.startswith("test_")
                or s.name.endswith("_test")
                or "/tests/" in s.file_path
                or s.file_path.startswith("tests/")
                or s.file_path.endswith((".test.ts", ".test.js", ".spec.ts", ".spec.js"))
            )
            if is_test:
                test_node_id = f"test:{self.snapshot_id}:{s.file_path}:{s.name}"
                nodes.append(
                    GraphNode(
                        id=test_node_id,
                        label="TestCase",
                        properties={
                            "snapshot_id": self.snapshot_id,
                            "name": s.name,
                            "file_path": s.file_path,
                            "start_line": s.start_line,
                            "end_line": s.end_line,
                        },
                    )
                )
                relationships.append(
                    GraphRelationship(
                        source_id=caller_node_id,
                        target_id=test_node_id,
                        type="DEFINES",
                        properties={"snapshot_id": self.snapshot_id},
                    )
                )

                # Heuristic: test_xyz -> tests symbol xyz
                target_sym_candidate = s.name.removeprefix("test_").removesuffix("_test")
                if target_sym_candidate:
                    resolved_test_target = self.resolver.resolve_symbol(
                        source_file=s.file_path,
                        symbol_name=target_sym_candidate,
                    )
                    if resolved_test_target.target_id:
                        relationships.append(
                            GraphRelationship(
                                source_id=test_node_id,
                                target_id=resolved_test_target.target_id,
                                type="TESTS",
                                properties={
                                    "snapshot_id": self.snapshot_id,
                                    "status": resolved_test_target.status,
                                    "confidence": resolved_test_target.confidence,
                                },
                            )
                        )

            # Extract calls from file content if available
            content = self.file_contents.get(s.file_path, "")
            if content:
                lines = content.splitlines()
                # Symbol body lines
                start_idx = max(0, s.start_line - 1)
                end_idx = min(len(lines), s.end_line)
                body_text = "\n".join(lines[start_idx:end_idx])

                called_names = set(CALL_PATTERN.findall(body_text))
                for called_name in called_names:
                    if called_name == s.name:
                        continue  # skip recursion self-call for simplicity or handle as self-loop
                    # Exclude common language keywords/built-ins
                    if called_name in {
                        "print",
                        "len",
                        "range",
                        "str",
                        "int",
                        "dict",
                        "list",
                        "set",
                        "tuple",
                        "isinstance",
                        "super",
                        "console",
                        "log",
                        "require",
                        "import",
                        "if",
                        "while",
                        "for",
                        "return",
                        "assert",
                    }:
                        continue

                    resolved_call = self.resolver.resolve_symbol(
                        source_file=s.file_path,
                        symbol_name=called_name,
                        target_type=None,
                    )
                    if resolved_call.target_id and resolved_call.target_id != caller_node_id:
                        relationships.append(
                            GraphRelationship(
                                source_id=caller_node_id,
                                target_id=resolved_call.target_id,
                                type="CALLS",
                                properties={
                                    "snapshot_id": self.snapshot_id,
                                    "status": resolved_call.status,
                                    "resolution_type": resolved_call.resolution_type,
                                    "confidence": resolved_call.confidence,
                                },
                            )
                        )

        # 7. API Endpoints Detection (EXPOSES)
        for s in self.symbols:
            content = self.file_contents.get(s.file_path, "")
            if content and s.symbol_type in ("function", "method"):
                lines = content.splitlines()
                # Check decorators above function
                start_idx = max(0, s.start_line - 5)
                end_idx = s.start_line
                header_text = "\n".join(lines[start_idx:end_idx])

                api_match = API_ROUTE_PATTERN.search(header_text)
                if api_match:
                    http_method = (api_match.group(1) or api_match.group(2)).upper()
                    route_path = api_match.group(3)
                    endpoint_id = f"api:{self.snapshot_id}:{http_method}:{route_path}"

                    nodes.append(
                        GraphNode(
                            id=endpoint_id,
                            label="APIEndpoint",
                            properties={
                                "snapshot_id": self.snapshot_id,
                                "method": http_method,
                                "path": route_path,
                                "handler_symbol": s.name,
                                "file_path": s.file_path,
                            },
                        )
                    )

                    caller_node_id = symbol_node_map.get(f"{s.file_path}:{s.name}")
                    if caller_node_id:
                        relationships.append(
                            GraphRelationship(
                                source_id=caller_node_id,
                                target_id=endpoint_id,
                                type="EXPOSES",
                                properties={"snapshot_id": self.snapshot_id},
                            )
                        )

        # 8. Database Models & Tables Detection (DEFINES, READS_FROM, WRITES_TO)
        for s in self.symbols:
            if s.symbol_type == "class":
                content = self.file_contents.get(s.file_path, "")
                if content:
                    lines = content.splitlines()
                    start_idx = max(0, s.start_line - 1)
                    end_idx = min(len(lines), s.end_line)
                    class_body = "\n".join(lines[start_idx:end_idx])

                    tbl_match = TABLE_NAME_PATTERN.search(class_body)
                    if tbl_match:
                        tbl_name = tbl_match.group(1)
                        table_id = f"tbl:{self.snapshot_id}:{tbl_name}"
                        nodes.append(
                            GraphNode(
                                id=table_id,
                                label="DatabaseTable",
                                properties={
                                    "snapshot_id": self.snapshot_id,
                                    "table_name": tbl_name,
                                    "model_name": s.name,
                                    "file_path": s.file_path,
                                },
                            )
                        )
                        class_node_id = symbol_node_map.get(f"{s.file_path}:{s.name}")
                        if class_node_id:
                            relationships.append(
                                GraphRelationship(
                                    source_id=class_node_id,
                                    target_id=table_id,
                                    type="DEFINES",
                                    properties={"snapshot_id": self.snapshot_id},
                                )
                            )

        # Deduplicate nodes by id
        dedup_nodes: dict[str, GraphNode] = {}
        for n in nodes:
            if n.id not in dedup_nodes:
                dedup_nodes[n.id] = n
            else:
                dedup_nodes[n.id].properties.update(n.properties)

        # Deduplicate relationships by (source_id, target_id, type)
        dedup_rels: dict[tuple[str, str, str], GraphRelationship] = {}
        for r in relationships:
            key = (r.source_id, r.target_id, r.type)
            if key not in dedup_rels:
                dedup_rels[key] = r
            else:
                dedup_rels[key].properties.update(r.properties)

        return list(dedup_nodes.values()), list(dedup_rels.values())

    def _map_symbol_label(self, symbol_type: str) -> str:
        mapping = {
            "function": "Function",
            "method": "Method",
            "class": "Class",
            "interface": "Interface",
            "struct": "Struct",
            "enum": "Enum",
            "module": "Module",
            "package": "Package",
        }
        return mapping.get(symbol_type.lower(), "Function")
