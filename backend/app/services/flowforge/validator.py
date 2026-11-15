from __future__ import annotations

import collections
import logging
from typing import Any

from app.services.flowforge.schemas import (
    WorkflowNodeConnection,
    WorkflowNodeDefinition,
    WorkflowNodeType,
    WorkflowValidationIssue,
    WorkflowValidationResult,
    WorkflowValidationSeverity,
)

logger = logging.getLogger("orchestrix.flowforge.validator")

# Maximum reasonable bounds for safety against denial-of-service/payload bomb
MAX_NODES = 250
MAX_CONNECTIONS = 500
MAX_JSON_SIZE_BYTES = 512 * 1024  # 512 KB


class WorkflowValidationError(Exception):
    """Raised when workflow validation fails strictly."""

    def __init__(self, message: str, issues: list[WorkflowValidationIssue] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.issues = issues or []


class WorkflowValidator:
    """
    Validates FlowForge workflow definitions (nodes, edges/connections, configurations).
    Enforces:
    - Unique node IDs
    - Connection integrity (sources and targets exist)
    - Exactly one TRIGGER node as entry point
    - Reachability of END nodes
    - Cycle detection (DAG requirement for standard workflows, rejecting unsupported cycles)
    - Node-type specific required configuration
    - Payload size & complexity limits
    - Strict avoidance of arbitrary code execution
    """

    SUPPORTED_NODE_TYPES = {t.value for t in WorkflowNodeType}

    def validate_graph(self, definition_json: dict[str, Any]) -> WorkflowValidationResult:
        issues: list[WorkflowValidationIssue] = []

        # 1. Structural / Type Validation
        if not isinstance(definition_json, dict):
            return WorkflowValidationResult(
                is_valid=False,
                issues=[
                    WorkflowValidationIssue(
                        code="INVALID_PAYLOAD",
                        message="Workflow definition must be a valid JSON dictionary.",
                    )
                ],
            )

        nodes_data = definition_json.get("nodes")
        connections_data = definition_json.get("connections")

        if not isinstance(nodes_data, list):
            return WorkflowValidationResult(
                is_valid=False,
                issues=[
                    WorkflowValidationIssue(
                        code="INVALID_NODES_LIST",
                        message="'nodes' field must be a list.",
                    )
                ],
            )

        if not isinstance(connections_data, list):
            return WorkflowValidationResult(
                is_valid=False,
                issues=[
                    WorkflowValidationIssue(
                        code="INVALID_CONNECTIONS_LIST",
                        message="'connections' field must be a list.",
                    )
                ],
            )

        if len(nodes_data) > MAX_NODES:
            issues.append(
                WorkflowValidationIssue(
                    code="EXCESSIVE_NODES",
                    message=f"Node count ({len(nodes_data)}) exceeds maximum permitted ({MAX_NODES}).",
                )
            )

        if len(connections_data) > MAX_CONNECTIONS:
            issues.append(
                WorkflowValidationIssue(
                    code="EXCESSIVE_CONNECTIONS",
                    message=f"Connection count ({len(connections_data)}) exceeds maximum permitted ({MAX_CONNECTIONS}).",
                )
            )

        # Parse nodes and validate uniqueness
        node_map: dict[str, WorkflowNodeDefinition] = {}
        trigger_nodes: list[WorkflowNodeDefinition] = []
        end_nodes: list[WorkflowNodeDefinition] = []

        for idx, n in enumerate(nodes_data):
            if not isinstance(n, dict):
                issues.append(
                    WorkflowValidationIssue(
                        code="INVALID_NODE_FORMAT",
                        message=f"Node at index {idx} is not an object.",
                    )
                )
                continue

            node_id = n.get("id")
            if not node_id or not isinstance(node_id, str) or not node_id.strip():
                issues.append(
                    WorkflowValidationIssue(
                        code="MISSING_NODE_ID",
                        message=f"Node at index {idx} has missing or blank 'id'.",
                    )
                )
                continue

            node_id = node_id.strip()
            if node_id in node_map:
                issues.append(
                    WorkflowValidationIssue(
                        code="DUPLICATE_NODE_ID",
                        message=f"Duplicate node ID detected: '{node_id}'.",
                        node_id=node_id,
                    )
                )
                continue

            node_type_raw = n.get("node_type")
            if not node_type_raw or node_type_raw not in self.SUPPORTED_NODE_TYPES:
                issues.append(
                    WorkflowValidationIssue(
                        code="UNSUPPORTED_NODE_TYPE",
                        message=f"Node '{node_id}' specifies unsupported node_type: '{node_type_raw}'.",
                        node_id=node_id,
                    )
                )
                continue

            config = n.get("config")
            if config is None:
                config = {}
            elif not isinstance(config, dict):
                issues.append(
                    WorkflowValidationIssue(
                        code="INVALID_NODE_CONFIG",
                        message=f"Node '{node_id}' config must be a dictionary.",
                        node_id=node_id,
                    )
                )
                config = {}

            node_def = WorkflowNodeDefinition(
                id=node_id,
                name=n.get("name"),
                node_type=WorkflowNodeType(node_type_raw),
                config=config,
            )
            node_map[node_id] = node_def

            if node_def.node_type == WorkflowNodeType.TRIGGER:
                trigger_nodes.append(node_def)
            elif node_def.node_type == WorkflowNodeType.END:
                end_nodes.append(node_def)

            # Node-specific config validations
            self._validate_node_config(node_def, issues)

        # Trigger check: Exactly one TRIGGER node required
        if len(trigger_nodes) == 0:
            issues.append(
                WorkflowValidationIssue(
                    code="MISSING_TRIGGER",
                    message="Workflow must contain exactly one TRIGGER node as an entry point.",
                )
            )
        elif len(trigger_nodes) > 1:
            issues.append(
                WorkflowValidationIssue(
                    code="MULTIPLE_TRIGGERS",
                    message=f"Workflow contains {len(trigger_nodes)} TRIGGER nodes. Exactly one is permitted.",
                )
            )

        # END check: At least one END node required
        if len(end_nodes) == 0:
            issues.append(
                WorkflowValidationIssue(
                    code="MISSING_END_NODE",
                    message="Workflow must contain at least one END node.",
                )
            )

        # Parse and validate connections
        connections: list[WorkflowNodeConnection] = []
        adj_list: dict[str, list[str]] = collections.defaultdict(list)
        reverse_adj_list: dict[str, list[str]] = collections.defaultdict(list)

        for c_idx, c in enumerate(connections_data):
            if not isinstance(c, dict):
                issues.append(
                    WorkflowValidationIssue(
                        code="INVALID_CONNECTION_FORMAT",
                        message=f"Connection at index {c_idx} is not an object.",
                    )
                )
                continue

            src = c.get("source_node_id")
            tgt = c.get("target_node_id")

            if not src or src not in node_map:
                issues.append(
                    WorkflowValidationIssue(
                        code="INVALID_SOURCE_NODE",
                        message=f"Connection references unknown source node: '{src}'.",
                        node_id=src,
                        target_node_id=tgt,
                    )
                )
                continue

            if not tgt or tgt not in node_map:
                issues.append(
                    WorkflowValidationIssue(
                        code="INVALID_TARGET_NODE",
                        message=f"Connection references unknown target node: '{tgt}'.",
                        node_id=src,
                        target_node_id=tgt,
                    )
                )
                continue

            if src == tgt:
                issues.append(
                    WorkflowValidationIssue(
                        code="SELF_LOOP_DETECTED",
                        message=f"Self-referencing loop detected on node '{src}'.",
                        node_id=src,
                        target_node_id=tgt,
                    )
                )
                continue

            # END nodes cannot have outgoing connections
            if node_map[src].node_type == WorkflowNodeType.END:
                issues.append(
                    WorkflowValidationIssue(
                        code="END_NODE_OUTGOING_CONNECTION",
                        message=f"END node '{src}' cannot have outgoing connections.",
                        node_id=src,
                        target_node_id=tgt,
                    )
                )

            # TRIGGER nodes cannot have incoming connections
            if node_map[tgt].node_type == WorkflowNodeType.TRIGGER:
                issues.append(
                    WorkflowValidationIssue(
                        code="TRIGGER_NODE_INCOMING_CONNECTION",
                        message=f"TRIGGER node '{tgt}' cannot have incoming connections.",
                        node_id=src,
                        target_node_id=tgt,
                    )
                )

            conn = WorkflowNodeConnection(
                source_node_id=src,
                target_node_id=tgt,
                condition_branch=c.get("condition_branch"),
            )
            connections.append(conn)
            adj_list[src].append(tgt)
            reverse_adj_list[tgt].append(src)

        # Graph connectivity & reachability checks (if no fatal structure errors)
        if len(trigger_nodes) == 1 and not any(
            issue.code
            in {
                "MISSING_TRIGGER",
                "DUPLICATE_NODE_ID",
                "INVALID_SOURCE_NODE",
                "INVALID_TARGET_NODE",
            }
            for issue in issues
        ):
            entry_id = trigger_nodes[0].id

            # Cycle detection (DFS with coloring: 0=unvisited, 1=visiting, 2=visited)
            visited_state: dict[str, int] = collections.defaultdict(int)
            has_cycle = False

            def dfs_cycle(curr: str, path: list[str]) -> bool:
                nonlocal has_cycle
                visited_state[curr] = 1
                for neighbor in adj_list.get(curr, []):
                    if visited_state[neighbor] == 1:
                        has_cycle = True
                        cycle_path = " -> ".join(path + [neighbor])
                        issues.append(
                            WorkflowValidationIssue(
                                code="CYCLE_DETECTED",
                                message=f"Unsupported cycle detected in workflow: {cycle_path}",
                                node_id=curr,
                                target_node_id=neighbor,
                            )
                        )
                        return True
                    elif visited_state[neighbor] == 0:
                        if dfs_cycle(neighbor, path + [neighbor]):
                            return True
                visited_state[curr] = 2
                return False

            for node_id in node_map:
                if visited_state[node_id] == 0:
                    dfs_cycle(node_id, [node_id])
                    if has_cycle:
                        break

            # Forward reachability from TRIGGER node
            reachable_from_trigger: set[str] = set()
            queue = collections.deque([entry_id])
            reachable_from_trigger.add(entry_id)

            while queue:
                curr = queue.popleft()
                for nxt in adj_list.get(curr, []):
                    if nxt not in reachable_from_trigger:
                        reachable_from_trigger.add(nxt)
                        queue.append(nxt)

            # Check unreachable nodes
            unreachable_nodes = set(node_map.keys()) - reachable_from_trigger
            if unreachable_nodes:
                for un in sorted(unreachable_nodes):
                    issues.append(
                        WorkflowValidationIssue(
                            code="UNREACHABLE_NODE",
                            message=f"Node '{un}' is unreachable from the trigger entry point.",
                            node_id=un,
                        )
                    )

            # Check reachability to END nodes
            # Every reachable node must have a path leading to an END node
            can_reach_end: set[str] = set()
            end_queue = collections.deque([n.id for n in end_nodes])
            for end_id in end_queue:
                can_reach_end.add(end_id)

            while end_queue:
                curr = end_queue.popleft()
                for prev in reverse_adj_list.get(curr, []):
                    if prev not in can_reach_end:
                        can_reach_end.add(prev)
                        end_queue.append(prev)

            for reach_id in reachable_from_trigger:
                if reach_id not in can_reach_end:
                    issues.append(
                        WorkflowValidationIssue(
                            code="CANNOT_REACH_END",
                            message=f"Reachable node '{reach_id}' has no path to any END node (dead end).",
                            node_id=reach_id,
                        )
                    )

            # CONDITION node validation: should have at least 2 outgoing connections
            for n_id, n_def in node_map.items():
                if n_def.node_type == WorkflowNodeType.CONDITION:
                    outgoings = [c for c in connections if c.source_node_id == n_id]
                    if len(outgoings) < 2:
                        issues.append(
                            WorkflowValidationIssue(
                                code="CONDITION_INSUFFICIENT_BRANCHES",
                                message=f"CONDITION node '{n_id}' must have at least 2 outgoing branches (e.g., true/false).",
                                node_id=n_id,
                            )
                        )

            # MERGE node validation: should have at least 2 incoming connections
            for n_id, n_def in node_map.items():
                if n_def.node_type == WorkflowNodeType.MERGE:
                    incomings = [c for c in connections if c.target_node_id == n_id]
                    if len(incomings) < 2:
                        issues.append(
                            WorkflowValidationIssue(
                                code="MERGE_INSUFFICIENT_INCOMING",
                                message=f"MERGE node '{n_id}' must have at least 2 incoming connections to synchronize.",
                                node_id=n_id,
                            )
                        )

        is_valid = len([i for i in issues if i.severity == WorkflowValidationSeverity.ERROR]) == 0
        entry_node_id = trigger_nodes[0].id if len(trigger_nodes) == 1 else None

        return WorkflowValidationResult(
            is_valid=is_valid,
            issues=issues,
            entry_node_id=entry_node_id,
            node_count=len(node_map),
            connection_count=len(connections),
        )

    def _validate_node_config(
        self, node_def: WorkflowNodeDefinition, issues: list[WorkflowValidationIssue]
    ) -> None:
        """Validate required configuration parameters for each node type."""
        config = node_def.config

        if node_def.node_type == WorkflowNodeType.DEVPILOT:
            # DevPilot requires prompt or action
            prompt = config.get("prompt")
            action = config.get("action")
            if not prompt and not action:
                issues.append(
                    WorkflowValidationIssue(
                        code="DEVPILOT_CONFIG_MISSING",
                        message=f"DevPilot node '{node_def.id}' requires 'prompt' or 'action' in config.",
                        node_id=node_def.id,
                    )
                )

        elif node_def.node_type == WorkflowNodeType.TESTPILOT:
            # TestPilot requires test_type or action
            pass  # defaults to 'run' or 'detect'

        elif node_def.node_type == WorkflowNodeType.SECUREFLOW:
            # SecureFlow scan_type defaults to FULL if omitted
            scan_type = config.get("scan_type", "FULL")
            if scan_type not in {"FULL", "DEPENDENCY", "SECRET", "SAST"}:
                issues.append(
                    WorkflowValidationIssue(
                        code="SECUREFLOW_INVALID_SCAN_TYPE",
                        message=f"SecureFlow node '{node_def.id}' has invalid scan_type '{scan_type}'.",
                        node_id=node_def.id,
                    )
                )

        elif node_def.node_type == WorkflowNodeType.CONDITION:
            # Condition requires expression / field evaluation rule
            field_name = config.get("field")
            operator = config.get("operator")
            if not field_name or not operator:
                issues.append(
                    WorkflowValidationIssue(
                        code="CONDITION_CONFIG_MISSING",
                        message=f"CONDITION node '{node_def.id}' requires 'field' and 'operator' in config.",
                        node_id=node_def.id,
                    )
                )

        elif node_def.node_type == WorkflowNodeType.APPROVAL:
            # Approval optionally defines required role, timeout, or reason
            pass

        elif node_def.node_type == WorkflowNodeType.NOTIFICATION:
            # Notification requires channel or message
            msg = config.get("message")
            if not msg:
                issues.append(
                    WorkflowValidationIssue(
                        code="NOTIFICATION_CONFIG_MISSING",
                        message=f"NOTIFICATION node '{node_def.id}' requires 'message' in config.",
                        node_id=node_def.id,
                    )
                )
