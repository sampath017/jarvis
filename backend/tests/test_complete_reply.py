from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.backend.command_execution import CommandExecution, CommandStopped, execution
from src.graph.nodes import tier2_agent as module


def node(monkeypatch, first, second):
    agent = module.Tier2AgentNode.__new__(module.Tier2AgentNode)
    agent.llm = Mock()
    tools = Mock()
    tools.invoke.return_value = first
    tools.bind.return_value.invoke.return_value = second
    agent.llm.bind.return_value.invoke.return_value = second
    guard = Mock()
    monkeypatch.setattr(module, "TokenBudgetGuard", lambda: guard)
    return agent, tools, guard


def test_truncated_reply_is_regenerated_with_existing_observations_without_tools(monkeypatch):
    first = AIMessage(content="At 11:24 a burst of", response_metadata={"finish_reason": "length"})
    second = AIMessage(content="At 11:24 walking was recorded. The rest of that interval is unknown.", response_metadata={"finish_reason": "stop"})
    agent, tools, guard = node(monkeypatch, first, second)
    messages = [HumanMessage(content="What did I do?"),
                AIMessage(content="", tool_calls=[{"name": "recall_context_history", "args": {}, "id": "read"}]),
                ToolMessage(content="11:24 WALKING; recording gap afterwards", tool_call_id="read")]
    progress = []
    context = CommandExecution(progress.append)
    token = execution.set(context)
    try:
        answer = agent._invoke_complete("u", messages, tools)
    finally:
        execution.reset(token)
    assert answer is second
    tools.invoke.assert_called_once()
    tools.bind.assert_not_called()
    retry_messages = agent.llm.bind.return_value.invoke.call_args.args[0]
    assert retry_messages[:3] == messages
    assert first not in retry_messages
    assert "do not request actions" in retry_messages[-1].content
    assert context.rounds == 2
    assert progress == ["Finishing your reply"]
    assert guard.check_and_reserve_tokens.call_count == 2
    assert guard.record_llm_usage.call_count == 2
    assert agent.llm.bind.call_args.kwargs['max_tokens'] == min(module.TIER2_OUTPUT_TOKENS * 2, 32768)


def test_truncated_tool_generation_is_discarded_before_execution(monkeypatch):
    first = AIMessage(content="", tool_calls=[{"name": "create_note", "args": {"text": "partial"}, "id": "partial"}],
                      response_metadata={"finish_reason": "length"})
    second = AIMessage(content="", tool_calls=[{"name": "create_note", "args": {"text": "complete note"}, "id": "complete"}],
                       response_metadata={"finish_reason": "tool_calls"})
    agent, tools, _ = node(monkeypatch, first, second)
    result = agent._invoke_complete("u", [HumanMessage(content="Save a note")], tools)
    assert result.tool_calls[0]["id"] == "complete"
    agent.llm.bind.assert_not_called()
    tools.bind.assert_called_once()


@pytest.mark.parametrize("reason,content", [("length", "partial"), ("stop", "")])
def test_repeated_incomplete_generation_fails_explicitly_after_one_retry(monkeypatch, reason, content):
    incomplete = AIMessage(content=content, response_metadata={"finish_reason": reason})
    agent, tools, _ = node(monkeypatch, incomplete, incomplete)
    with pytest.raises(CommandStopped, match="after one retry"):
        agent._invoke_complete("u", [HumanMessage(content="Question")], tools)
    assert tools.invoke.call_count == 1
    assert agent.llm.bind.return_value.invoke.call_count == 1


def test_transport_timeout_does_not_restart_the_request(monkeypatch):
    agent, tools, _ = node(monkeypatch, None, None)
    tools.invoke.side_effect = TimeoutError("provider timeout")
    with pytest.raises(TimeoutError):
        agent._invoke_complete("u", [HumanMessage(content="Question")], tools)
    agent.llm.bind.assert_not_called()
    tools.bind.assert_not_called()


def test_missing_finish_reason_still_detects_exhausted_generation_budget(monkeypatch):
    first = AIMessage(content="partial", usage_metadata={"input_tokens": 10, "output_tokens": module.TIER2_OUTPUT_TOKENS, "total_tokens": module.TIER2_OUTPUT_TOKENS + 10})
    second = AIMessage(content="Complete answer.", response_metadata={"finish_reason": "stop"})
    agent, tools, _ = node(monkeypatch, first, second)
    assert agent._invoke_complete("u", [HumanMessage(content="Question")], tools) is second


PROVIDER_ACCOUNT_ERROR = ('Your quota is exhausted.\nAPI key status: exceeded\n'
                          'Name: upstream\nUSDT balance: -1\nUSDT spent: 2\nexp_date: later')


def test_provider_account_error_retries_same_generation_without_replaying_actions(monkeypatch):
    first = AIMessage(content=PROVIDER_ACCOUNT_ERROR, response_metadata={'finish_reason': 'stop'})
    second = AIMessage(content='Your Gym was saved.', response_metadata={'finish_reason': 'stop'})
    agent, tools, guard = node(monkeypatch, first, second)
    tools.invoke.side_effect = [first, second]
    messages = [HumanMessage(content='Save my Gym'),
                ToolMessage(content='Saved. ID: gym-1', tool_call_id='save')]
    context = CommandExecution(lambda _: None, writes={'save_place:{}': 'Saved. ID: gym-1'})
    token = execution.set(context)
    try:
        assert agent._invoke_complete('u', messages, tools) is second
    finally:
        execution.reset(token)
    assert tools.invoke.call_count == 2
    assert all(call.args[0] == messages for call in tools.invoke.call_args_list)
    assert guard.record_llm_usage.call_count == 2
    tools.bind.assert_not_called()
    agent.llm.bind.assert_not_called()
    assert context.writes == {'save_place:{}': 'Saved. ID: gym-1'}


def test_repeated_provider_account_error_is_failure_without_account_details(monkeypatch):
    failure = AIMessage(content=PROVIDER_ACCOUNT_ERROR, response_metadata={'finish_reason': 'stop'})
    agent, tools, _ = node(monkeypatch, failure, failure)
    with pytest.raises(CommandStopped, match='AI provider is temporarily unavailable') as raised:
        agent._invoke_complete('u', [HumanMessage(content='Save Gym')], tools)
    assert tools.invoke.call_count == 2
    assert 'USDT' not in str(raised.value) and 'API key' not in str(raised.value)


def test_quota_explanation_is_not_mistaken_for_upstream_account_error(monkeypatch):
    answer = AIMessage(content='Your quota is exhausted in that provider error. Check the provider account.', response_metadata={'finish_reason': 'stop'})
    agent, tools, _ = node(monkeypatch, answer, answer)
    assert agent._invoke_complete('u', [HumanMessage(content='Explain this error')], tools) is answer
    tools.invoke.assert_called_once()
