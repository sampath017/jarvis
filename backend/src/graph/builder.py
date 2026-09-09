"""
LangGraph Workflow Builder — Autonomous Multi-Agent StateGraph Architecture.

Implements true LangGraph ReAct Agents for both Tier 1 (Context Reasoner)
and Tier 2 (Conversational & Task Orchestrator) with tool loops, feedback observations,
and budget-constrained iteration limits.
"""

from __future__ import annotations

import logging
from langgraph.graph import END, StateGraph

from .state import JarvisState
from .nodes.verify import VerifyNode
from .nodes.load_context import LoadContextNode
from .nodes.context_gate import ContextGateNode
from .nodes.session_reducer import SessionReducerNode
from .nodes.intent_router import IntentRouterNode
from .nodes.tier1_agent import Tier1AgentNode
from .nodes.tier1_tools_node import Tier1ToolsNode
from .nodes.tier2_agent import Tier2AgentNode
from .nodes.tier2_tools_node import Tier2ToolsNode
from .nodes.persist import PersistNode
from ..services.database import DatabaseService
from ..backend.context_resolver import ContextResolver
from ..backend.session_manager import SessionManager
from ..settings import AGENT_MAX_ITERATIONS

logger = logging.getLogger(__name__)


def route_request_type(state: JarvisState) -> str:
    """Route conditionally based on incoming request type."""
    req_type = state.get("request_type")
    if req_type == "USER_COMMAND":
        return "intent_router"
    return "context_gate"


def route_intent(state: JarvisState) -> str:
    """Route from intent_router: fast-path for greetings vs Tier 2 ReAct agent."""
    if state.get("is_greeting", False):
        return "persist"
    return "tier2_agent"


def route_tier2_agent_loop(state: JarvisState) -> str:
    """Check if Tier 2 agent requested tool calls or produced a final answer."""
    step_count = state.get("agent_step_count", 0)
    messages = state.get("agent_messages", [])

    if not messages or step_count >= AGENT_MAX_ITERATIONS:
        return "persist"

    last_msg = messages[-1]
    tool_calls = getattr(last_msg, "tool_calls", [])
    if tool_calls:
        return "tier2_tools"

    return "persist"


def route_tier1_needed(state: JarvisState) -> str:
    """Route conditionally if Tier 1 context reasoner agent is needed."""
    if state.get("needs_tier1", False):
        return "tier1_agent"
    return "session_reducer"


def route_tier1_agent_loop(state: JarvisState) -> str:
    """Check if Tier 1 agent requested context tools or finalized resolution."""
    step_count = state.get("tier1_step_count", 0)
    messages = state.get("tier1_messages", [])

    if not messages or step_count >= AGENT_MAX_ITERATIONS:
        return "session_reducer"

    last_msg = messages[-1]
    tool_calls = getattr(last_msg, "tool_calls", [])
    if tool_calls:
        return "tier1_tools"

    return "session_reducer"


def build_workflow(db: DatabaseService | None = None):
    """Build and compile the autonomous Jarvis multi-agent LangGraph StateGraph."""
    workflow = StateGraph(JarvisState)

    db_instance = db or DatabaseService()
    resolver = ContextResolver()
    session_mgr = SessionManager()

    # 1. Instantiate Node Handlers with Dependency Injection
    workflow.add_node("verify", VerifyNode(db=db_instance))
    workflow.add_node("load_context", LoadContextNode(db=db_instance))
    workflow.add_node("context_gate", ContextGateNode(resolver=resolver, db=db_instance))
    workflow.add_node("session_reducer", SessionReducerNode(session_manager=session_mgr, db=db_instance))
    workflow.add_node("intent_router", IntentRouterNode(db=db_instance))

    # Tier 1 Context Agent & Tools
    workflow.add_node("tier1_agent", Tier1AgentNode(db=db_instance))
    workflow.add_node("tier1_tools", Tier1ToolsNode(db=db_instance))

    # Tier 2 ReAct Agent & Tools
    workflow.add_node("tier2_agent", Tier2AgentNode(db=db_instance))
    workflow.add_node("tier2_tools", Tier2ToolsNode(db=db_instance))

    # Persistence
    workflow.add_node("persist", PersistNode(db=db_instance))

    # 2. Entry and Context Branching
    workflow.set_entry_point("verify")
    workflow.add_edge("verify", "load_context")

    workflow.add_conditional_edges(
        "load_context",
        route_request_type,
        {
            "context_gate": "context_gate",
            "intent_router": "intent_router",
        },
    )

    # 3. User Command Intent Branching
    workflow.add_conditional_edges(
        "intent_router",
        route_intent,
        {
            "persist": "persist",       # Fast path for greetings (<15ms)
            "tier2_agent": "tier2_agent", # Action / conversation agent
        },
    )

    # 4. Tier 2 ReAct Multi-Turn Loop (agent ⇄ tools)
    workflow.add_conditional_edges(
        "tier2_agent",
        route_tier2_agent_loop,
        {
            "tier2_tools": "tier2_tools",
            "persist": "persist",
        },
    )
    workflow.add_edge("tier2_tools", "tier2_agent")  # Tool output feeds back into agent!

    # 5. Context Telemetry Branching & Tier 1 Agent Loop
    workflow.add_conditional_edges(
        "context_gate",
        route_tier1_needed,
        {
            "tier1_agent": "tier1_agent",
            "session_reducer": "session_reducer",
        },
    )

    workflow.add_conditional_edges(
        "tier1_agent",
        route_tier1_agent_loop,
        {
            "tier1_tools": "tier1_tools",
            "session_reducer": "session_reducer",
        },
    )
    workflow.add_edge("tier1_tools", "tier1_agent")  # Feedback loop for Tier 1!
    workflow.add_edge("session_reducer", "persist")

    # 6. Terminal Edge
    workflow.add_edge("persist", END)

    return workflow.compile()
