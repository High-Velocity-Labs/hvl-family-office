"""Unit tests for cryptographic Cold-Eyes subagent transcript verification in export_public_repo.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest

from scripts.export_public_repo import _verify_cold_eyes_subagent_transcript

SAMPLE_HASH = "a1b2c3d4e5f60718"
SUBAGENT_ID = "9f8e7d6c-5b4a-4321-8765-123456789abc"


def _write_subagent_transcript(
    brain_root: Path,
    sub_id: str,
    steps: list[dict],
    *,
    invoke_model: str | None = "inherit",
    full_steps: list[dict] | None = None,
) -> Path:
    sub_dir = brain_root / sub_id
    logs_dir = sub_dir / ".system_generated" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = logs_dir / "transcript.jsonl"
    transcript_path.write_text("\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8")
    if full_steps is not None:
        (logs_dir / "transcript_full.jsonl").write_text(
            "\n".join(json.dumps(s) for s in full_steps) + "\n", encoding="utf-8"
        )
    if invoke_model is not None:
        msg_dir = sub_dir / ".system_generated" / "messages"
        msg_dir.mkdir(parents=True, exist_ok=True)
        msg_payload = {
            "id": "msg-001",
            "recipient": sub_id,
            "sender": "parent-conv-12345678",
            "sourceMetadata": {
                "tool": {
                    "conversationId": "parent-conv-12345678",
                    "toolCall": {
                        "name": "invoke_subagent",
                        "argumentsJson": json.dumps(
                            {"Model": invoke_model, "TypeName": "research", "Role": "Cold-Eyes Auditor"}
                        ),
                    },
                }
            },
        }
        (msg_dir / "msg-001.json").write_text(json.dumps(msg_payload), encoding="utf-8")
    return transcript_path


def _valid_steps(now_iso: str, tree_hash: str = SAMPLE_HASH, *, model_tier: str | None = None) -> list[dict]:
    step0: dict[str, object] = {
        "step_index": 0,
        "source": "SYSTEM",
        "type": "SYSTEM_MESSAGE",
        "status": "DONE",
        "created_at": now_iso,
        "content": "<SYSTEM_MESSAGE>[Message] sender=parent-conv-12345678 content=Audit staging tree</SYSTEM_MESSAGE>",
    }
    if model_tier:
        step0["model_tier"] = model_tier
    return [
        step0,
        {
            "step_index": 1,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": now_iso,
            "tool_calls": [{"name": "run_command", "args": {"CommandLine": "ls -la"}}],
        },
        {
            "step_index": 2,
            "source": "MODEL",
            "type": "GENERIC",
            "status": "DONE",
            "created_at": now_iso,
            "content": "Command exited with code 0.",
        },
        {
            "step_index": 3,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": now_iso,
            "content": f"Audit complete. Zero PII or secret leaks found.\nCOLD_EYES_VERIFIED:{tree_hash}",
        },
    ]


def test_never_leaks_expected_tree_hash_in_error_messages(tmp_path: Path):
    """Error messages must NEVER contain the expected tree_hash token (prevents copy-paste bypass)."""
    with pytest.raises(RuntimeError) as exc_info:
        _verify_cold_eyes_subagent_transcript(None, None, SAMPLE_HASH, brain_root=tmp_path)
    assert SAMPLE_HASH not in str(exc_info.value)

    with pytest.raises(RuntimeError) as exc_info2:
        _verify_cold_eyes_subagent_transcript("missing-subagent-id", SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)
    assert SAMPLE_HASH not in str(exc_info2.value)


def test_rejects_missing_or_fake_subagent_transcript(tmp_path: Path):
    with pytest.raises(RuntimeError, match="Missing or invalid --cold-eyes-subagent"):
        _verify_cold_eyes_subagent_transcript("", SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)

    with pytest.raises(RuntimeError, match="Missing or invalid --cold-eyes-subagent"):
        _verify_cold_eyes_subagent_transcript("../traversal", SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)

    with pytest.raises(RuntimeError, match="Subagent transcript not found on disk"):
        _verify_cold_eyes_subagent_transcript(SUBAGENT_ID, SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)


def test_rejects_user_conversation_and_stale_subagents(tmp_path: Path):
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    user_steps = _valid_steps(now_iso)
    user_steps[0] = {
        "step_index": 0,
        "source": "USER_EXPLICIT",
        "type": "USER_INPUT",
        "created_at": now_iso,
        "content": "Hello",
    }
    _write_subagent_transcript(tmp_path, SUBAGENT_ID, user_steps)
    with pytest.raises(RuntimeError, match="user session, not a spawned subagent"):
        _verify_cold_eyes_subagent_transcript(SUBAGENT_ID, SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)

    stale_iso = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat().replace("+00:00", "Z")
    _write_subagent_transcript(tmp_path, SUBAGENT_ID, _valid_steps(stale_iso))
    with pytest.raises(RuntimeError, match="transcript is stale"):
        _verify_cold_eyes_subagent_transcript(SUBAGENT_ID, SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)


def test_rejects_flash_and_flash_lite_subagents(tmp_path: Path):
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for bad_model in ("flash", "flash_lite", "MODEL_TIER_FLASH"):
        _write_subagent_transcript(
            tmp_path,
            SUBAGENT_ID,
            _valid_steps(now_iso, model_tier=bad_model),
            invoke_model=bad_model,
        )
        with pytest.raises(RuntimeError, match="must run with MODEL_TIER_INHERIT or 'pro'"):
            _verify_cold_eyes_subagent_transcript(SUBAGENT_ID, SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)


def test_rejects_subagent_without_inspection_tools_or_attestation(tmp_path: Path):
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    no_tool_steps = [
        _valid_steps(now_iso)[0],
        {
            "step_index": 1,
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "created_at": now_iso,
            "tool_calls": [],
            "content": f"COLD_EYES_VERIFIED:{SAMPLE_HASH}",
        },
    ]
    _write_subagent_transcript(tmp_path, SUBAGENT_ID, no_tool_steps)
    with pytest.raises(RuntimeError, match="did not execute any 'read_file' or 'run_command'"):
        _verify_cold_eyes_subagent_transcript(SUBAGENT_ID, SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)

    wrong_hash_steps = _valid_steps(now_iso, tree_hash="0000000000000000")
    _write_subagent_transcript(tmp_path, SUBAGENT_ID, wrong_hash_steps)
    with pytest.raises(RuntimeError, match="missing the matching COLD_EYES_VERIFIED:<tree_hash> attestation") as exc_info:
        _verify_cold_eyes_subagent_transcript(SUBAGENT_ID, SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)
    assert SAMPLE_HASH not in str(exc_info.value)


def test_accepts_valid_inherit_or_pro_subagent_and_truncated_full_fallback(tmp_path: Path):
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for good_model in ("inherit", "MODEL_TIER_INHERIT", "pro"):
        _write_subagent_transcript(
            tmp_path,
            SUBAGENT_ID,
            _valid_steps(now_iso, model_tier=good_model),
            invoke_model=good_model,
        )
        _verify_cold_eyes_subagent_transcript(SUBAGENT_ID, SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)

    # Verify fallback to transcript_full.jsonl when final PLANNER_RESPONSE content is truncated
    compact_steps = _valid_steps(now_iso)
    full_steps = _valid_steps(now_iso)
    compact_steps[-1] = {
        **compact_steps[-1],
        "content": "Audit complete...",
        "truncated_fields": ["content"],
    }
    _write_subagent_transcript(tmp_path, SUBAGENT_ID, compact_steps, full_steps=full_steps)
    _verify_cold_eyes_subagent_transcript(SUBAGENT_ID, SAMPLE_HASH, SAMPLE_HASH, brain_root=tmp_path)
