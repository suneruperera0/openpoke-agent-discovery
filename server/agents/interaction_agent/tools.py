"""Tool definitions for interaction agent."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Optional

from ...logging_config import logger
from ...services.conversation import get_conversation_log
from ...services.execution import get_agent_roster, get_execution_agent_logs
from ..execution_agent.batch_manager import ExecutionBatchManager
from ...services.execution.routing_trace import emit


@dataclass
class ToolResult:
    """Standardized payload returned by interaction-agent tools."""

    success: bool
    payload: Any = None
    user_message: Optional[str] = None
    recorded_reply: bool = False

# Tool schemas for OpenRouter
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "send_message_to_agent",
            "description": "Dispatch to an existing owner by agent_ref or exact agent_name. Unknown names return candidates without creating. Use create_agent only for a distinct new responsibility.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "description": "Human-readable agent name describing its purpose (e.g., 'Vercel Job Offer', 'Email to Sharanjeet'). This name will be used to identify and potentially reuse the agent."
                    },
                    "instructions": {"type": "string", "description": "Instructions for the agent to execute."},
                    "agent_ref": {"type": "string", "description": "Opaque ref from directory. Prefer this when a display name is shortened."},
                },
                "required": ["instructions"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message_to_user",
            "description": "Deliver a natural-language response directly to the user. Use this for updates, confirmations, or any assistant response the user should see immediately.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Plain-text message that will be shown to the user and recorded in the conversation log.",
                    },
                },
                "required": ["message"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_draft",
            "description": "Record an email draft so the user can review the exact text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email for the draft.",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject for the draft.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body content (plain text).",
                    },
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Wait silently when a message is already in conversation history to avoid duplicating responses. Adds a <wait> log entry that is not visible to the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why waiting (e.g., 'Message already sent', 'Draft already created').",
                    },
                },
                "required": ["reason"],
                "additionalProperties": False,
            },
        },
    },
]

_EXECUTION_BATCH_MANAGER = ExecutionBatchManager()

TOOL_SCHEMAS.extend([
    {"type": "function", "function": {
        "name": "search_agents",
        "description": "Discover existing owners across the entire directory, including old agents. Rephrase a miss; empty query lists all agents. Pagination is a recovery mechanism.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "cursor": {"type": "string"}},
            "required": ["query"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "create_agent",
        "description": "Deliberately create and dispatch a distinct new responsibility after considering existing owners. Exact existing names are reused. Do not use to duplicate existing work.",
        "parameters": {"type": "object", "properties": {
            k: {"type": "string"} for k in ("name", "purpose", "instructions", "reason")},
            "required": ["name", "purpose", "instructions", "reason"], "additionalProperties": False}}},
])


def _bounded_query(text: str) -> str:
    """Clip a discovery query to the directory byte budget so long instructions can't hard-fail search."""
    return text.encode("utf-8")[:8000].decode("utf-8", "ignore")


def search_agents(query: str, cursor: Optional[str] = None) -> ToolResult:
    page = get_agent_roster().search(query, cursor)
    emit("search", query=query, candidates=page["candidates"], paginated=bool(cursor),
         response_bytes=len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()))
    return ToolResult(success=True, payload=page)


def create_agent(name: str, purpose: str, instructions: str, reason: str) -> ToolResult:
    if not all(isinstance(s, str) and s.strip() for s in (name, purpose, instructions, reason)):
        return ToolResult(success=False, payload={"error": "Creation requires name, purpose, instructions and reason"})
    asyncio.get_running_loop()  # Do not create an owner when dispatch cannot run.
    roster = get_agent_roster()
    candidates = roster.search(_bounded_query(name + " " + instructions))["candidates"]
    record, created = roster.create_or_reuse(name, purpose, instructions)
    emit("creation_decision", selected_ref=record["ref"], created=created,
         candidate_refs=[r["ref"] for r in candidates])
    return _dispatch(record, instructions, created)


# Create or reuse execution agent and dispatch instructions asynchronously
def send_message_to_agent(agent_name: Optional[str] = None, instructions: str = "", agent_ref: Optional[str] = None) -> ToolResult:
    """Send instructions to an execution agent."""
    roster = get_agent_roster()
    if not instructions.strip() or not (agent_name or agent_ref):
        return ToolResult(success=False, payload={"error": "Provide instructions and an existing name or ref"})
    try:
        record = roster.resolve(agent_name, agent_ref)
    except ValueError as exc:
        if "Conflicting" in str(exc):
            return ToolResult(success=False, payload={"error": str(exc)})
        record = None  # unknown/stale ref: fall through to candidate recovery below
    if record is None:
        page = roster.search(_bounded_query((agent_name or "") + " " + instructions))
        emit("unknown_owner", candidate_refs=[r["ref"] for r in page["candidates"]])
        return ToolResult(success=False, payload={"status": "creation_review_required", **page})
    return _dispatch(record, instructions, False)


def _dispatch(record, instructions: str, is_new: bool) -> ToolResult:
    loop = asyncio.get_running_loop()
    agent_name = record["name"]
    get_agent_roster().mark_used(record["ref"], instructions)
    emit("dispatch", selected_ref=record["ref"], created=is_new)

    get_execution_agent_logs().record_request(agent_name, instructions)

    action = "Created" if is_new else "Reused"
    logger.info(f"{action} agent: {agent_name}")

    async def _execute_async() -> None:
        try:
            result = await _EXECUTION_BATCH_MANAGER.execute_agent(agent_name, instructions)
            status = "SUCCESS" if result.success else "FAILED"
            logger.info(f"Agent '{agent_name}' completed: {status}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Agent '{agent_name}' failed: {str(exc)}")

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.error("No running event loop available for async execution")
        return ToolResult(success=False, payload={"error": "No event loop available"})

    loop.create_task(_execute_async())

    return ToolResult(
        success=True,
        payload={
            "status": "submitted",
            "agent_name": agent_name,
            "agent_ref": record["ref"],
            "new_agent_created": is_new,
        },
    )


# Send immediate message to user and record in conversation history
def send_message_to_user(message: str) -> ToolResult:
    """Record a user-visible reply in the conversation log."""
    log = get_conversation_log()
    log.record_reply(message)

    return ToolResult(
        success=True,
        payload={"status": "delivered"},
        user_message=message,
        recorded_reply=True,
    )


# Format and record email draft for user review
def send_draft(
    to: str,
    subject: str,
    body: str,
) -> ToolResult:
    """Record a draft update in the conversation log for the interaction agent."""
    log = get_conversation_log()

    message = f"To: {to}\nSubject: {subject}\n\n{body}"

    log.record_reply(message)
    logger.info(f"Draft recorded for: {to}")

    return ToolResult(
        success=True,
        payload={
            "status": "draft_recorded",
            "to": to,
            "subject": subject,
        },
        recorded_reply=True,
    )


# Record silent wait state to avoid duplicate responses
def wait(reason: str) -> ToolResult:
    """Wait silently and add a wait log entry that is not visible to the user."""
    log = get_conversation_log()
    
    # Record a dedicated wait entry so the UI knows to ignore it
    log.record_wait(reason)
    

    return ToolResult(
        success=True,
        payload={
            "status": "waiting",
            "reason": reason,
        },
        recorded_reply=True,
    )


# Return predefined tool schemas for LLM function calling
def get_tool_schemas():
    """Return OpenAI-compatible tool schemas."""
    return TOOL_SCHEMAS


# Route tool calls to appropriate handlers with argument validation and error handling
def handle_tool_call(name: str, arguments: Any) -> ToolResult:
    """Handle tool calls from interaction agent."""
    try:
        if isinstance(arguments, str):
            args = json.loads(arguments) if arguments.strip() else {}
        elif isinstance(arguments, dict):
            args = arguments
        else:
            return ToolResult(success=False, payload={"error": "Invalid arguments format"})

        if name == "send_message_to_agent":
            return send_message_to_agent(**args)
        if name == "search_agents":
            return search_agents(**args)
        if name == "create_agent":
            return create_agent(**args)
        if name == "send_message_to_user":
            return send_message_to_user(**args)
        if name == "send_draft":
            return send_draft(**args)
        if name == "wait":
            return wait(**args)

        logger.warning("unexpected tool", extra={"tool": name})
        return ToolResult(success=False, payload={"error": f"Unknown tool: {name}"})
    except json.JSONDecodeError:
        return ToolResult(success=False, payload={"error": "Invalid JSON"})
    except (TypeError, ValueError) as exc:
        return ToolResult(success=False, payload={"error": f"Missing required arguments: {exc}"})
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("tool call failed", extra={"tool": name, "error": str(exc)})
        return ToolResult(success=False, payload={"error": "Failed to execute"})
