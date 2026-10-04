from kie_mcp.webhook import create_webhook_signature, verify_webhook_signature


def test_webhook_signature_round_trip() -> None:
    signature = create_webhook_signature("task-123", 1_700_000_000, "secret")
    result = verify_webhook_signature(
        body={"taskId": "task-123"},
        timestamp="1700000000",
        signature=signature,
        secret="secret",
        max_age_seconds=300,
        now=1_700_000_100,
    )
    assert result["valid"] is True


def test_webhook_replay_window() -> None:
    signature = create_webhook_signature("task-123", 1_700_000_000, "secret")
    result = verify_webhook_signature(
        body={"task_id": "task-123"},
        timestamp="1700000000",
        signature=signature,
        secret="secret",
        max_age_seconds=10,
        now=1_700_000_100,
    )
    assert result["valid"] is False
    assert "replay" in result["reason"]
