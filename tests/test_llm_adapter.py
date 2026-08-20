import os
import sys
from pathlib import Path

import pytest


SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from config import Config  # noqa: E402
from services.api_client import LLMClient  # noqa: E402
from services.llm_adapter import LLMAdapter  # noqa: E402
from routes.support.generation_request import GenerationRequest  # noqa: E402
from services.token_budget import calculate_token_budget  # noqa: E402


def test_generate_uses_default_max_tokens_without_network(monkeypatch):
    client = LLMClient(provider="deepseek", api_key="test-key")
    captured = {}

    def fake_generate_sync(params):
        captured.update(params)
        return {"content": "正文", "reasoning_content": "", "usage": {}}

    monkeypatch.setattr(client, "_generate_sync", fake_generate_sync)

    result = client.generate(
        model="deepseek-v4-pro",
        messages=[{"role": "user", "content": "写故事"}],
    )

    assert result["content"] == "正文"
    assert captured["max_tokens"] == Config.DEFAULT_MAX_TOKENS


def test_stream_reports_length_finish_reason(monkeypatch):
    client = LLMClient(provider="deepseek", api_key="test-key")
    chunks = [
        {"choices": [{"delta": {"content": "未完"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "length"}]},
    ]
    monkeypatch.setattr(client, "_post_stream", lambda *_args, **_kwargs: iter(chunks))

    events = list(client.generate_stream_aggregated({"model": "deepseek-v4-pro", "messages": []}))

    assert events[-1]["type"] == "done"
    assert events[-1]["result"]["content"] == "未完"
    assert events[-1]["result"]["finish_reason"] == "length"


def test_invalid_sampling_value_is_dropped_instead_of_breaking_request():
    filtered, dropped = LLMAdapter.normalize_sampling(
        {"temperature": 99, "top_p": 0.8, "unknown": 1},
        "deepseek",
    )

    assert filtered == {"top_p": 0.8}
    assert dropped == ["temperature"]


def test_generation_request_forwards_sampling_to_service_layer(monkeypatch):
    monkeypatch.setattr(GenerationRequest, "load_templates", lambda _self: [])
    request = GenerationRequest.from_mapping({
        "sampling": {"temperature": 1.2, "max_tokens": 4096},
    })

    assert request.sampling == {"temperature": 1.2, "max_tokens": 4096}
    assert request.generation_kwargs(stream=True)["sampling"] == request.sampling
    assert request.generation_kwargs(stream=True)["max_tokens"] == 4096


def test_generation_request_rejects_non_object_sampling():
    with pytest.raises(Exception, match="sampling 必须是对象"):
        GenerationRequest.from_mapping({"sampling": ["temperature", 0.7]})


def test_deepseek_capabilities_hide_deprecated_penalties():
    description = LLMAdapter.describe("deepseek", Config.LLM_PROVIDERS["deepseek"])

    assert description["parameters"]["temperature"]["supported"] is True
    assert description["parameters"]["max_tokens"]["supported"] is True
    assert description["parameters"]["frequency_penalty"]["supported"] is False
    assert "思考模式" in description["note"]


def test_provider_specific_range_is_enforced():
    filtered, dropped = LLMAdapter.normalize_sampling(
        {"temperature": 1.5, "top_p": 0.95},
        "zhipu",
        Config.LLM_PROVIDERS["zhipu"],
    )

    assert filtered == {"top_p": 0.95}
    assert dropped == ["temperature"]


def test_deepseek_thinking_removes_ineffective_sampling_parameters():
    client = LLMClient(provider="deepseek", api_key="test-key")
    configured = client.configure_generation_params(
        {
            "model": "deepseek-v4-pro",
            "temperature": 0.8,
            "top_p": 0.9,
            "max_tokens": 4096,
        },
        thinking_enabled=True,
    )

    assert "temperature" not in configured
    assert "top_p" not in configured
    assert configured["max_tokens"] == 4096
    assert configured["extra_body"]["thinking"]["type"] == "enabled"


def test_advanced_max_tokens_changes_token_budget_reservation():
    default = calculate_token_budget("短提示", "openai", "gpt-4o")
    custom = calculate_token_budget(
        "短提示", "openai", "gpt-4o", max_tokens=16384,
    )

    assert custom["phases"]["primary"]["output_reserved_tokens"] > (
        default["phases"]["primary"]["output_reserved_tokens"]
    )


def test_invalid_max_tokens_cannot_break_budget_preflight():
    budget = calculate_token_budget(
        "短提示", "openai", "gpt-4o", max_tokens="not-a-number",
    )

    assert budget["phases"]["primary"]["output_reserved_tokens"] == (
        Config.DEFAULT_MAX_TOKENS
    )
