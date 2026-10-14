from langchain_core.messages import AIMessage
from src.backend.command_execution import CommandExecution, execution
from src.cloud.file_memory_tools import file_memory_tools
from src.graph.nodes.tier2_tools_node import Tier2ToolsNode
from src.services.database import DatabaseService


def test_independent_file_calls_use_one_device_batch_with_stable_tool_results(monkeypatch, tmp_path):
    dispatched=[]
    def device(action):
        dispatched.append(action)
        assert action['operation']=='file_read_batch'
        return {'results':[{'call_id':item['call_id'],'result':{'status':'ok','answer':item['file_id']}} for item in action['actions']]}
    context=CommandExecution(lambda _:None, approval_dispatch=device)
    monkeypatch.setattr('src.graph.nodes.tier2_tools_node.build_tier2_tools',lambda *_:file_memory_tools())
    token=execution.set(context)
    try:
        result=Tier2ToolsNode(DatabaseService(tmp_path/'batch.db'))({'uid':'u','agent_messages':[AIMessage(content='',tool_calls=[
            {'name':'analyze_saved_file','args':{'file_id':'resume','question':'experience'},'id':'a'},
            {'name':'analyze_saved_file','args':{'file_id':'identity','question':'number'},'id':'b'},
        ])]})
    finally:
        execution.reset(token)
    assert len(dispatched)==1 and context.tools==2
    assert [message.tool_call_id for message in result['agent_messages'][-2:]]==['a','b']
