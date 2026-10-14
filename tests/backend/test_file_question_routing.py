import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.backend.command_execution import CommandExecution, execution
from src.cloud.file_memory_tools import complete_file_answer
from src.graph.nodes import agent as module
from src.services.database import DatabaseService


QUESTION = 'How many years of experience and role'
ANSWER = 'The resume lists 3 years as a software engineer (page 1).'


def evidence(question=QUESTION, file_id='new-resume', result=None, calls=None):
    call = {'name': 'analyze_saved_file', 'args': {'file_id': file_id, 'question': question}, 'id': 'read'}
    return [HumanMessage(content=QUESTION),
            AIMessage(content='', tool_calls=calls or [call]),
            ToolMessage(content=json.dumps(result or {
                'status': 'ok', 'file_id': file_id, 'answer': ANSWER}), tool_call_id='read', name='analyze_saved_file')]


def test_file_evidence_returns_to_model_for_requested_format(monkeypatch, tmp_path):
    agent = module.AgentNode.__new__(module.AgentNode)
    agent.db = DatabaseService(tmp_path / 'answer.db')
    agent.llm = Mock()
    agent._invoke_complete = Mock(return_value=AIMessage(content=ANSWER))
    monkeypatch.setattr(module, 'build_agent_tools', lambda *_: [])
    result = agent({'uid': 'u', 'agent_step_count': 1, 'agent_messages': evidence(),
                    'raw_request': {'text': QUESTION, 'attached_file_ids': ['new-resume']}})
    assert result['user_response'] == ANSWER
    assert result['agent_messages'][-1].tool_calls == []
    agent._invoke_complete.assert_called_once()
    assert isinstance(agent._invoke_complete.call_args.args[1][-1], ToolMessage)


@pytest.mark.parametrize('changes', [
    {'question': 'List the job titles'},
    {'result': {'status': 'error', 'file_id': 'new-resume', 'answer': 'Unverified'}},
    {'result': {'status': 'cancelled', 'file_id': 'new-resume', 'answer': ANSWER}},
    {'result': {'status': 'ok', 'file_id': 'older-resume', 'answer': ANSWER}},
    {'result': {'status': 'ok', 'file_id': 'new-resume', 'answer': ''}},
    {'calls': [{'name': 'analyze_saved_file', 'args': {'file_id': 'new-resume', 'question': QUESTION}, 'id': 'read'},
               {'name': 'create_reminder', 'args': {'title': 'Interview'}, 'id': 'write'}]},
])
def test_partial_wrong_file_failed_or_mixed_analysis_cannot_end_request(changes):
    assert complete_file_answer(QUESTION, evidence(**changes)) is None


def test_unmatched_tool_result_cannot_supply_answer():
    messages = evidence()
    messages[-1].tool_call_id = 'different-call'
    assert complete_file_answer(QUESTION, messages) is None


def test_retrieved_passages_require_synthesis_instead_of_being_returned_as_final_answer():
    messages = evidence(result={'status':'ok','file_id':'new-resume','source_kind':'retrieved_passages','answer':'Untrusted selected source excerpts'})
    assert complete_file_answer(QUESTION, messages) is None
    messages[-1].content = 'Error executing analysis'
    assert complete_file_answer(QUESTION, messages) is None


def routing_agent(monkeypatch, tmp_path):
    agent = module.AgentNode.__new__(module.AgentNode)
    agent.db = DatabaseService(tmp_path / 'route.db')
    agent.llm = Mock()
    monkeypatch.setattr(module, 'build_agent_tools', lambda *_: [
        SimpleNamespace(name=name) for name in
        ['analyze_saved_file', 'save_file_to_drive', 'respond_to_user', 'get_current_location', 'create_calendar_event']])
    return agent


def test_client_preserves_reasoning_effort_and_completion_budget(tmp_path):
    agent = module.AgentNode(DatabaseService(tmp_path / 'defaults.db'))
    assert not agent.llm.extra_body or 'reasoning' not in agent.llm.extra_body
    assert agent.llm.max_tokens == module.LLM_OUTPUT_TOKENS


def test_new_attachment_keeps_full_chat_with_new_file_attribution(monkeypatch, tmp_path):
    agent = routing_agent(monkeypatch, tmp_path)
    candidate = evidence()[1]
    agent._invoke_complete = Mock(return_value=candidate)
    result = agent({'uid': 'u', 'context_scope': 'on_demand', 'raw_request': {
        'text': QUESTION, 'attached_file_ids': ['new-resume'],
        'file_memories': [{'id': 'new-resume', 'name': 'resume.pdf'}],
        'history': [{'role': 'assistant', 'content': 'OLDER RESUME has 10 years.'}]}})
    assert result['agent_messages'][-1].tool_calls[0]['args']['file_id'] == 'new-resume'
    used_prompt = agent._invoke_complete.call_args.args[1]
    assert len(used_prompt) == 3 and 'OLDER RESUME' in str(used_prompt)
    assert used_prompt[0].content == module.ATTACHMENT_ROUTING_PROMPT
    assert 'Never answer its contents from an older file' in used_prompt[0].content
    route_tools = agent.llm.bind_tools.call_args_list[-1].args[0]
    assert {t.name for t in route_tools} == {
        'analyze_saved_file', 'save_file_to_drive', 'respond_to_user', 'continue_with_assistant'}
    agent.llm.bind.assert_not_called()


def test_mixed_attachment_request_hands_off_without_dropping_calendar_task(monkeypatch, tmp_path):
    agent = routing_agent(monkeypatch, tmp_path)
    handoff = AIMessage(content='', tool_calls=[{'name': 'continue_with_assistant', 'args': {}, 'id': 'route'}])
    calendar = AIMessage(content='', tool_calls=[{'name': 'create_calendar_event', 'args': {}, 'id': 'calendar'}])
    agent._invoke_complete = Mock(side_effect=[handoff, calendar])
    result = agent({'uid': 'u', 'context_scope': 'on_demand', 'raw_request': {
        'text': 'Read my resume and schedule an interview tomorrow', 'attached_file_ids': ['new-resume'],
        'history': [{'role': 'user', 'content': 'Use my work calendar'}]}})
    assert agent._invoke_complete.call_count == 2
    assert result['agent_messages'][-1].tool_calls[0]['name'] == 'create_calendar_event'
    full_messages = agent._invoke_complete.call_args.args[1]
    assert full_messages[0].content == module.SYSTEM_PROMPT_CHAT
    assert 'Use my work calendar' in str(full_messages)


def test_completed_write_prevents_early_file_answer(monkeypatch, tmp_path):
    agent = routing_agent(monkeypatch, tmp_path)
    agent._invoke_complete = Mock(return_value=AIMessage(content='File answered and event created.'))
    context = CommandExecution(lambda _: None)
    context.writes['calendar'] = 'created'
    token = execution.set(context)
    try:
        result = agent({'uid': 'u', 'agent_step_count': 1, 'agent_messages': evidence(),
                        'raw_request': {'text': QUESTION}})
    finally:
        execution.reset(token)
    agent._invoke_complete.assert_called_once()
    assert result['user_response'] == 'File answered and event created.'
