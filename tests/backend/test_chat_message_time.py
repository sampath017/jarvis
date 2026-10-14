from datetime import datetime, timezone
from unittest.mock import Mock

from src.services.chat_message_time import message_stamp
from src.services.record_store import RecordStore


def test_send_instant_from_phone_id_precedes_reply_even_after_late_sync():
    question = message_stamp('2026-10-15T07:46:58.951708Z',
        message_id='msg_1792050411882631', role='user')
    assert question == '2026-10-15T07:46:51.882631+00:00'
    assert question < message_stamp('2026-10-15T07:46:58.946799Z')
    assert question == message_stamp('2026-10-15T07:47:40Z',
        message_id='msg_1792050411882631', role='user')


def test_legacy_local_phone_time_is_interpreted_independently_of_server_timezone():
    assert message_stamp('2026-10-04T16:12:46.322906') == '2026-10-04T10:42:46.322906+00:00'
    assert message_stamp(datetime(2026,10,4,10,42,46,322906,tzinfo=timezone.utc)) == '2026-10-04T10:42:46.322906+00:00'


def test_real_sqlite_save_path_uses_the_stable_send_timestamp():
    from src.services.sqlite_store import SqlStore
    fs = RecordStore.from_sql(SqlStore(':memory:'))
    assert fs.save_chat_message('u', 'thread', {'id':'msg_1792050411882631', 'role':'user',
        'content':'Number the entries', 'timestamp':'2026-10-15T07:46:58.951708Z'})
    assert fs.get_chat_messages('u', 'thread')[0]['timestamp'] == '2026-10-15T07:46:51.882631+00:00'
