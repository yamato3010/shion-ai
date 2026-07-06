from shion.config import _expand_env


def test_expand_env(monkeypatch):
    monkeypatch.setenv("TEST_SHION_KEY", "secret123")
    config = {
        "llm": {
            "providers": {
                "openai": {"api_key": "${TEST_SHION_KEY}", "base_url": "https://api.openai.com/v1"},
                "missing": {"api_key": "${TEST_SHION_UNDEFINED}"},
            }
        },
        "list": ["${TEST_SHION_KEY}", 42],
    }
    expanded = _expand_env(config)
    assert expanded["llm"]["providers"]["openai"]["api_key"] == "secret123"
    assert expanded["llm"]["providers"]["missing"]["api_key"] == ""
    assert expanded["list"] == ["secret123", 42]
