"""One agent/tool runtime with independent chat and background invocations."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .state import JarvisState
from .nodes.verify import VerifyNode
from .nodes.load_context import LoadContextNode
from .nodes.context_gate import ContextGateNode
from .nodes.session_reducer import SessionReducerNode
from .nodes.semantic_context import SemanticContextNode
from .nodes.intent_router import IntentRouterNode
from .nodes.agent import AgentNode
from .nodes.agent_tools import AgentToolsNode
from .nodes.persist import PersistNode
from ..services.database import DatabaseService
from ..backend.context_resolver import ContextResolver
from ..backend.session_manager import SessionManager
from ..settings import AGENT_MAX_ITERATIONS
from ..backend.agent_policy import BACKGROUND_MAX_ITERATIONS
from ..backend.command_execution import observed_node


def route_request_type(state: JarvisState) -> str:
    return "intent_router" if state.get("request_type") == "USER_COMMAND" else "context_gate"


def route_intent(state: JarvisState) -> str:
    """Every conversational request reaches the shared tool-capable runtime."""
    return "agent"


def route_context_assessment_needed(state: JarvisState) -> str:
    return "agent" if state.get("needs_context_assessment", False) else "session_reducer"


def route_agent_loop(state: JarvisState) -> str:
    """Continue one tool loop; return each invocation to its own workflow."""
    background = state.get("request_type") == "CONTEXT_EVENT"
    destination = "session_reducer" if background else "persist"
    if background and state.get("context_assessment") is not None:
        return destination
    messages = state.get("agent_messages", [])
    limit = BACKGROUND_MAX_ITERATIONS if background else AGENT_MAX_ITERATIONS
    if not messages or state.get("agent_step_count", 0) >= limit:
        return destination
    if getattr(messages[-1], "tool_calls", []):
        return "agent_tools"
    return destination


def build_workflow(db: DatabaseService | None = None):
    """Build a fresh invocation; background assessments never join chat history."""
    workflow = StateGraph(JarvisState)
    db_instance = db or DatabaseService()
    workflow.add_node("verify", observed_node("verify", VerifyNode(db=db_instance)))
    workflow.add_node("load_context", observed_node("load_context", LoadContextNode(db=db_instance)))
    workflow.add_node("intent_router", observed_node("intent_router", IntentRouterNode(db=db_instance)))
    workflow.add_node("context_gate", ContextGateNode(resolver=ContextResolver(), db=db_instance))
    workflow.add_node("agent", observed_node("agent", AgentNode(db=db_instance)))
    workflow.add_node("agent_tools", AgentToolsNode(db=db_instance))
    workflow.add_node("session_reducer", SessionReducerNode(session_manager=SessionManager(), db=db_instance))
    workflow.add_node("semantic_context", SemanticContextNode())
    workflow.add_node("persist", observed_node("persist", PersistNode(db=db_instance)))
    workflow.set_entry_point("verify")
    workflow.add_edge("verify", "load_context")
    workflow.add_conditional_edges("load_context", route_request_type,
                                   {"context_gate": "context_gate", "intent_router": "intent_router"})
    workflow.add_conditional_edges("intent_router", route_intent, {"agent": "agent"})
    workflow.add_conditional_edges("context_gate", route_context_assessment_needed,
                                   {"agent": "agent", "session_reducer": "session_reducer"})
    workflow.add_conditional_edges("agent", route_agent_loop,
                                   {"agent_tools": "agent_tools", "session_reducer": "session_reducer", "persist": "persist"})
    workflow.add_edge("agent_tools", "agent")
    workflow.add_edge("session_reducer", "semantic_context")
    workflow.add_edge("semantic_context", "persist")
    workflow.add_edge("persist", END)
    return workflow.compile()
