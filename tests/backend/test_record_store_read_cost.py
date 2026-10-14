"""Owner/status predicates and bounds execute in indexed SQLite queries."""
from src.services.sqlite_store import SqlStore
from src.services.record_store import RecordStore


def service():
    return RecordStore.from_sql(SqlStore(':memory:'))


def test_chat_reads_filter_owner_and_keep_orphans_out():
    fs = service()
    fs.save_chat_session('a', {'uid': 'alice'})
    fs.save_chat_session('b', {'uid': 'bob'})
    for key, uid, thread in [('m1','alice','a'), ('orphan','alice','deleted'), ('m2','bob','b')]:
        fs.save_chat_message(uid, thread, {'id': key, 'role': 'user', 'content': key})
    statements=[]
    fs.sql.db.set_trace_callback(statements.append)
    rows=fs.get_chat_messages('alice')
    assert [row['id'] for row in rows] == ['m1']
    selects=[sql for sql in statements if sql.startswith('SELECT * FROM')]
    assert len([sql for sql in selects if '"chat_threads"' in sql]) == 1
    assert len([sql for sql in selects if '"chat_messages"' in sql]) == 1
    assert all("uid='alice'" in sql for sql in selects)


def test_no_chat_sessions_skips_message_scan():
    fs=service()
    fs.save_chat_message('alice','deleted',{'id':'orphan','content':'Unavailable thread'})
    statements=[];fs.sql.db.set_trace_callback(statements.append)
    assert fs.get_chat_messages('alice') == []
    assert not any('SELECT * FROM "chat_messages"' in sql for sql in statements)


def test_personal_record_owner_predicates_use_sql_indices():
    fs=service()
    for table, fields in [('notes',{'content':'note'}),('reminders',{'title':'reminder'}),
                          ('places',{'name':'Home','latitude':12.9,'longitude':80.2})]:
        for uid in ('alice','bob'):
            fs.sql.put(table,uid,{**fields,'id':uid},uid=uid)
        rows=fs.sql.list(table,uid='alice')
        assert [row['id'] for row in rows] == ['alice']
        plan=fs.sql.db.execute(f'EXPLAIN QUERY PLAN SELECT * FROM "{table}" WHERE uid=?',('alice',)).fetchall()
        assert any('SEARCH' in row['detail'] and 'INDEX' in row['detail'] for row in plan)


def test_pending_notification_filter_precedes_limit_and_skips_acknowledged_rows():
    fs=service()
    fs.sql.put('notifications','pending',{'status':'PENDING','title':'Pending','trigger_type':'TIME_DUE','created_at':'2026-01-01'},uid='alice')
    for number in range(150):
        fs.sql.put('notifications',str(number),{'status':'DELIVERED','title':'Old','trigger_type':'TIME_DUE','created_at':'2026-10-14'},uid='alice')
    assert [row['id'] for row in fs.get_notifications('alice','PENDING')] == ['pending']
    assert fs.get_notifications('bob','PENDING') == []
    plan=fs.sql.db.execute('EXPLAIN QUERY PLAN SELECT * FROM notifications WHERE uid=? AND status=? ORDER BY created_at DESC LIMIT 100',('alice','PENDING')).fetchall()
    assert any('SEARCH' in row['detail'] for row in plan)


def test_active_context_filters_execute_before_history_bounds():
    fs=service()
    for number in range(101):
        key='open' if number==0 else str(number)
        fs.sql.put('mobility_sessions',key,{'status':'ACTIVE' if number==0 else 'COMPLETED'},uid='alice')
        fs.sql.put('semantic_contexts',key,{'active':number==0},uid='alice')
    assert [row['id'] for row in fs.get_mobility_sessions('alice',active_only=True)] == ['open']
    assert [row['id'] for row in fs.get_semantic_contexts('alice')] == ['open']
