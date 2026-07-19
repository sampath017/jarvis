"""
LangGraph Workflow Builder — Class-Based Node Architecture

Assembles the StateGraph using object-oriented Class-Based Node Handlers
with dependency injection (as described in standard LangGraph patterns).
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .state import JarvisState
from .nodes.verify import VerifyNode
from .nodes.load_context import LoadContextNode
from .nodes.context_gate import ContextGateNode
from .nodes.session_reducer import SessionReducerNode
from .nodes.tier1_resolve import Tier1ResolveNode
from .nodes.intent_router import IntentRouterNode
from .nodes.tier2_orchestrate import Tier2OrchestrateNode
from .nodes.validate_and_execute import ValidateAndExecuteNode
from .nodes.persist import PersistNode
from ..services.firestore_client import FirestoreService
from ..backend.context_resolver import ContextResolver
from ..backend.session_manager import SessionManager
from ..cloud.tier1_reasoner import Tier1Reasoner


def route_request_type(state: JarvisState) -> str:
    """Route conditionally based on request type."""
    req_type = state.get("request_type")
    if req_type == "USER_COMMAND":
        return "intent_router"
    return "context_gate"


def route_tier1_needed(state: JarvisState) -> str:
    """Route conditionally if Tier 1 resolution is needed."""
    if state.get("needs_tier1", False):
        return "tier1_resolve"
    return "session_reducer"


def build_workflow():
    """Build and compile the Jarvis LangGraph StateGraph using Class-Based Node Handlers."""
    workflow = StateGraph(JarvisState)

    # Services for dependency injection
    fs = FirestoreService()
    resolver = ContextResolver()
    session_mgr = SessionManager()
    reasoner = Tier1Reasoner()

    # 1. Instantiate Object-Oriented Node Handlers with Dependency Injection
    workflow.add_node("verify", VerifyNode())
    workflow.add_node("load_context", LoadContextNode(firestore_service=fs))
    workflow.add_node("context_gate", ContextGateNode(resolver=resolver))
    workflow.add_node("session_reducer", SessionReducerNode(session_manager=session_mgr))
    workflow.add_node("tier1_resolve", Tier1ResolveNode(reasoner=reasoner))
    workflow.add_node("intent_router", IntentRouterNode())
    workflow.add_node("tier2_orchestrate", Tier2OrchestrateNode())
    workflow.add_node("validate_and_execute", ValidateAndExecuteNode(firestore_service=fs))
    workflow.add_node("persist", PersistNode(firestore_service=fs))

    # 2. Define StateGraph routing and edges
    workflow.set_entry_point("verify")
    workflow.add_edge("verify", "load_context")

    workflow.add_conditional_edges(
        "load_context",
        route_request_type,
        {
            "context_gate": "context_gate",
            "intent_router": "intent_router",
        }
    )

    workflow.add_conditional_edges(
        "context_gate",
        route_tier1_needed,
        {
            "tier1_resolve": "tier1_resolve",
            "session_reducer": "session_reducer",
        }
    )

    workflow.add_edge("tier1_resolve", "session_reducer")
    workflow.add_edge("session_reducer", "persist")
    workflow.add_edge("intent_router", "tier2_orchestrate")
    workflow.add_edge("tier2_orchestrate", "validate_and_execute")
    workflow.add_edge("validate_and_execute", "persist")
    workflow.add_edge("persist", END)

    return workflow.compile()
