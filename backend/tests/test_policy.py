from app.integrations import extract_json
from app.main import _action_is_safe, _redact, _resolve_secrets


def test_secrets_are_resolved_only_at_execution_and_redacted_afterward():
    secrets = {"username": "qa@example.test", "password": "sensitive-value"}
    args = _resolve_secrets({"fields": [{"value": "$USERNAME"}, {"value": "$PASSWORD"}]}, secrets)
    assert args["fields"][1]["value"] == "sensitive-value"
    assert _redact(str(args), secrets) == "{'fields': [{'value': '$USERNAME'}, {'value': '$PASSWORD'}]}"


def test_policy_enforces_same_origin_and_blocks_irreversible_clicks():
    base = "https://legacy.example.test"
    assert _action_is_safe("browser_navigate", {"url": f"{base}/orders"}, base, False)
    assert not _action_is_safe("browser_navigate", {"url": "https://evil.test"}, base, False)
    assert not _action_is_safe("browser_click", {"element": "Delete account"}, base, False)
    assert _action_is_safe("browser_click", {"element": "Delete account"}, base, True)


def test_json_extractor_accepts_fenced_results():
    assert extract_json('```json\n{"stop": true}\n```') == {"stop": True}
