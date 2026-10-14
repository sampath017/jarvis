import pytest
from langchain_core.messages import AIMessage

from src.graph.nodes.agent import AgentNode
from src.services.database import DatabaseService


@pytest.mark.parametrize('structured', [False, True])
def test_headings_tables_links_code_and_chart_data_survive_reply_delivery(monkeypatch, tmp_path, structured):
    reply = ('## Comparison\n\n**Verified values** with a [source](https://example.com).\n\n'
             '| Item | Value |\n|---|---:|\n| A | 20 |\n| B | 35 |\n\n'
             '```chart\n{"type":"bar","title":"Comparison","unit":"minutes",'
             '"labels":["A","B"],"series":[{"name":"Walking","values":[20,35]}]}\n```\n\n'
             '```python\nprint("**literal**")\n```')
    answer = AIMessage(content='' if structured else reply, tool_calls=[
        {'name': 'respond_to_user', 'id': 'final', 'args': {'message': reply, 'intent': 'general'}},
    ] if structured else [], response_metadata={'finish_reason': 'stop'})
    node = AgentNode(DatabaseService(tmp_path / 'rich.db'))
    monkeypatch.setattr(node, '_invoke_complete', lambda *args, **kwargs: answer)
    result = node({'uid': 'u', 'raw_request': {'text': 'Compare these values'}})
    assert result['user_response'] == reply
