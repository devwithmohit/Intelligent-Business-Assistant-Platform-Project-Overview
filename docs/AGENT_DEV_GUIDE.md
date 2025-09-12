# Agent Development Guide

This guide describes how to add and maintain agents, register tools, and test agent behavior in the IBA codebase.

## Goals
- Provide a simple, consistent agent lifecycle.
- Encourage small, testable steps: plan -> execute_step.
- Enable reuse of tools, LLM helpers, and memory.

## Project layout (relevant paths)
- backend/agents/ — agent implementations and shared base
  - base_agent.py — BaseAgent class (lifecycle, llm/tool/memory helpers)
  - agent_factory.py — dynamic discovery / instantiate agents
  - <agent_type>/agent.py — concrete agent subclasses (e.g. customer_service)
- backend/services/ — helper services (llm_service, memory_service, crm_client, etc.)
- backend/schemas/ — pydantic request/response models
- backend/tests/ — unit tests for agents and services

## Agent structure (recommended)
- Name: subclass BaseAgent
- Implement:
  - async def _plan(self, **kwargs) -> List[Step]: return ordered steps
  - async def _execute_step(self, step: Step, **kwargs) -> Any
- Keep steps small and deterministic; prefer explicit step types: "llm", "tool", "http", "create_ticket", etc.
- Use llm_generate, call_tool, remember, recall helpers from BaseAgent.

## Tooling and services
- Register tools via tool_service (or implement a ToolRegistry with get(name)).
- Use memory_service.store_memory / get_memory for persistence and audit.
- Use services for external calls (crm_client, web_search_client, enrichment_service).
- Use template_manager for reusable prompts/templates.

## Safety, prompts, and templates
- Use utils.llm_utils.apply_prompt_template, sanitize_prompt, is_safe_prompt before sending to providers.
- Keep temperature/limits in agent.config or LLMRequest params.
- Store raw LLM responses in memory for auditing only (avoid logging secrets).

## Registering / discovery
- AgentFactory attempts to discover backend.agents.<agent_type>.agent and registers any BaseAgent subclass automatically.
- Optionally call agents.agent_factory.register_agent(...) in module init to be explicit.

## Testing
- Write unit tests in backend/tests:
  - stub llm_service._call_provider or monkeypatch llm_service.generate
  - stub external services (crm_client, web_search_client, enrichment_service)
  - assert plan shape and outputs for each step, and memory persistence where relevant
- Provide both sync and async tests (pytest + pytest-asyncio).

## Examples
- customer_service:
  - plan: summarize -> create_ticket -> draft_response
  - calls crm_client.create_ticket, llm_service.generate
- content_creation:
  - plan: generate_outline -> generate_draft -> refine
  - uses template_manager.render_template optionally

## Best practices
- Keep prompts concise and sanitized.
- Fail gracefully: agents should return AgentResult with error details but avoid raising for recoverable step failures.
- Persist run/audit records with memory_service for observability.
- Limit concurrency for external enrichments (use semaphores).

## Adding a new agent checklist
1. Create backend/agents/<new_type>/agent.py subclassing BaseAgent.
2. Implement _plan and _execute_step; use Step typed dict.
3. Add any tool wrappers under backend/services or backend/tools.
4. Add unit tests under backend/tests covering happy path and error/fallback behavior.
5. Optionally register agent in a module init or rely on AgentFactory discovery.

## Contact / notes
- For template examples, add files under data/templates and use template_manager.
- For integration keys, set env vars (see