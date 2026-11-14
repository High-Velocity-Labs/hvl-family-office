"""Advisor conversation list: counts and latest message come from SQL, not from loading every body."""

import db
import security
from hvl_common.db import get_db_connection
from services.request_context import DB_PATH

FAM_ID = 96


def _clear(db_path):
    with get_db_connection(db_path) as raw_conn:
        raw_conn.execute("DELETE FROM advisor_messages WHERE family_id = ?", (FAM_ID,))
        raw_conn.execute("DELETE FROM advisor_conversations WHERE family_id = ?", (FAM_ID,))
        raw_conn.commit()


def test_list_conversations_counts_and_latest_message_per_thread():
    db_path = DB_PATH.for_family(FAM_ID)
    security.init_db(db_path)
    _clear(db_path)
    try:
        convs = db.conversations
        busy = convs.create_conversation("conv_list_busy", family_id=FAM_ID, title="Busy", db_path=db_path)
        quiet = convs.create_conversation("conv_list_quiet", family_id=FAM_ID, title="Quiet", db_path=db_path)
        empty = convs.create_conversation("conv_list_empty", family_id=FAM_ID, title="Empty", db_path=db_path)
        for role, content in (("user", "first"), ("assistant", "second"), ("user", "third")):
            convs.add_message(busy, family_id=FAM_ID, role=role, content=content, db_path=db_path)
        convs.add_message(quiet, family_id=FAM_ID, role="user", content="only one", db_path=db_path)

        rows = {r["conversation_id"]: r for r in convs.list_conversations(family_id=FAM_ID, db_path=db_path)}

        assert (rows[busy]["message_count"], rows[busy]["last_message"]) == (3, "third")
        assert (rows[quiet]["message_count"], rows[quiet]["last_message"]) == (1, "only one")
        assert (rows[empty]["message_count"], rows[empty]["last_message"]) == (0, "")

        opened = convs.get_conversation(busy, family_id=FAM_ID, db_path=db_path)
        assert [m["content"] for m in opened["messages"]] == ["first", "second", "third"]
    finally:
        _clear(db_path)
