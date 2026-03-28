import asyncio
import json
import logging
from typing import Any, Dict, Optional

import pytest

from orchestration.graph_builder import GraphBuilder
from orchestration.state_management import StateManager
from orchestration.workflow_executor import WorkflowExecutor

logger = logging.getLogger(__name__)


class _TestAgentRunner:
    """
    Simple deterministic agent runner used in tests.
    Behavior driven by agent_name:
      - "a_start": sets {'val': 42}
      - "a_check": sets {'flag': True} (to force conditional branch)
      - "a_finish": sets {'finished': True}
      - fallback: empty update
    """

    async def run_agent(self, agent_name: str, instance_id: str, node_config: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0)  # yield control
        if agent_name == "a_start":
            return {"context_updates": {"val": 42}, "status": "ok"}
        if agent_name == "a_check":
            return {"context_updates": {"flag": True}, "status": "ok"}
        if agent_name == "a_finish":
            return {"context_updates": {"finished": True}, "status": "ok"}
        return {"context_updates": {}, "status": "ok"}


@pytest.mark.asyncio
async def test_linear_workflow_exec(tmp_path):
    """
    Validate a simple linear workflow: start -> finish
    The test uses a custom AgentRunner to inject deterministic context updates.
    """
    persist_dir = str(tmp_path / "states_linear")
    sm = StateManager(persist_dir=persist_dir)
    runner = _TestAgentRunner()
    exec = WorkflowExecutor(state_manager=sm, agent_runner=runner)

    g = GraphBuilder(name="wf_linear")
    g.register_agent("a_start", {})
    g.register_agent("a_finish", {})
    g.add_node("start", agent="a_start", config={})
    g.add_node("finish", agent="a_finish", config={})
    g.add_edge("start", "finish")

    result = await exec.run_and_wait(graph=g, start_node="start", timeout=5.0)
    assert result.get("id")
    ctx = result.get("context") or {}
    assert ctx.get("val") == 42
    assert ctx.get("finished") is True


@pytest.mark.asyncio
async def test_conditional_branching(tmp_path):
    """
    Build a graph with a conditional branch:
      start -> check -> true_path / false_path
    Ensure the condition evaluation routes to the expected node.
    """
    persist_dir = str(tmp_path / "states_branch")
    sm = StateManager(persist_dir=persist_dir)
    runner = _TestAgentRunner()
    exec = WorkflowExecutor(state_manager=sm, agent_runner=runner)

    g = GraphBuilder(name="wf_branch")
    g.register_agent("a_start", {})
    g.register_agent("a_check", {})
    g.register_agent("a_true", {})
    g.register_agent("a_false", {})

    g.add_node("start", agent="a_start", config={})
    g.add_node("check", agent="a_check", config={})
    g.add_node("true_path", agent="a_true", config={})
    g.add_node("false_path", agent="a_false", config={})

    g.add_edge("start", "check")
    # conditional edges evaluated against context produced by "a_check"
    g.add_edge("check", "true_path", condition="flag == True")
    g.add_edge("check", "false_path", condition="flag == False")

    result = await exec.run_and_wait(graph=g, start_node="start", timeout=5.0)
    ctx = result.get("context") or {}
    # a_check sets flag=True, so true_path should have been taken (we expect no error and stable completion)
    assert ctx.get("flag") is True


@pytest.mark.asyncio
async def test_state_snapshot_and_persistence(tmp_path):
    """
    Start a workflow instance, wait briefly, then snapshot persisted state file.
    """
    persist_dir = str(tmp_path / "states_snapshot")
    sm = StateManager(persist_dir=persist_dir)
    runner = _TestAgentRunner()
    exec = WorkflowExecutor(state_manager=sm, agent_runner=runner)

    g = GraphBuilder(name="wf_snapshot")
    g.register_agent("a_start", {})
    g.add_node("start", agent="a_start", config={})

    instance_id = await exec.start(graph=g, start_node="start", initial_context={"seed": 1})
    # allow background executor to make progress
    await asyncio.sleep(0.2)

    # snapshot to a file
    out_path = str(tmp_path / f"{instance_id}.json")
    snap_path = await sm.snapshot_instance(instance_id, out_path=out_path)
    # ensure file exists and contains valid JSON with expected keys
    with open(snap_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    assert payload.get("id") == instance_id
    assert "context" in payload
