import json
from types import SimpleNamespace
from src.cloud.clock_tools import clock_tools
from src.backend.command_execution import execution


def tools():
    return {t.name:t for t in clock_tools()}


def test_clock_requires_a_live_phone_and_does_not_claim_creation():
    token=execution.set(None)
    try:
        assert json.loads(tools()['create_clock_timer'].invoke({'seconds':60}))['status']=='unavailable'
    finally:
        execution.reset(token)


def test_timer_uses_phone_receipt_and_rejects_invalid_durations():
    sent=[]
    context=SimpleNamespace(check=lambda:None,approval_dispatch=lambda action:(sent.append(action) or {'status':'ok'}))
    token=execution.set(context)
    try:
        tool=tools()['create_clock_timer']
        assert json.loads(tool.invoke({'seconds':600,'label':'Cooking'}))['status']=='ok'
        assert sent==[{'operation':'clock_action','clock_action':'timer.start','arguments':{'seconds':600,'label':'Cooking'}}]
        assert json.loads(tool.invoke({'seconds':0}))['status']=='invalid_arguments'
        assert len(sent)==1
    finally:
        execution.reset(token)


def test_clock_edits_only_dispatch_allowlisted_actions_and_preserve_ids():
    sent=[]
    token=execution.set(SimpleNamespace(check=lambda:None,approval_dispatch=lambda a:(sent.append(a) or {'status':'ok'})))
    try:
        tool=tools()['update_clock']
        assert json.loads(tool.invoke({'action':'timer.pause','arguments':{'id':'timer_verified'}}))['status']=='ok'
        assert sent[-1]['arguments']=={'id':'timer_verified'}
        assert json.loads(tool.invoke({'action':'shell.execute','arguments':{}}))['status']=='invalid_arguments'
        assert json.loads(tool.invoke({'action':'timer.pause','arguments':{'__requestId':'forged'}}))['status']=='invalid_arguments'
        assert len(sent)==1
    finally:
        execution.reset(token)
