from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set


class GraphValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ExecutionNode:
    id: str
    agent: str
    task: str
    depends_on: List[str] = field(default_factory=list)
    expected_artifacts: List[str] = field(default_factory=list)
    risk: str = "low"


@dataclass(frozen=True)
class ExecutionGraph:
    run_id: str
    nodes: List[ExecutionNode]

    def validate(self, known_agents: Set[str]) -> None:
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise GraphValidationError("Execution graph contains duplicate node IDs.")

        id_set = set(ids)
        for node in self.nodes:
            if node.agent not in known_agents:
                raise GraphValidationError(f"Unknown agent for node {node.id}: {node.agent}")
            missing = set(node.depends_on) - id_set
            if missing:
                missing_list = ", ".join(sorted(missing))
                raise GraphValidationError(f"Node {node.id} depends on missing nodes: {missing_list}")

        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        nodes_by_id: Dict[str, ExecutionNode] = {node.id: node for node in self.nodes}
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            if node_id in visiting:
                raise GraphValidationError("Execution graph contains a dependency cycle.")

            visiting.add(node_id)
            for dependency_id in nodes_by_id[node_id].depends_on:
                visit(dependency_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in nodes_by_id:
            visit(node_id)

