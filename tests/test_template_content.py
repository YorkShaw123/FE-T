import inspect
import sys
from pathlib import Path
from types import SimpleNamespace


SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_DIR))

from services.prompt_assembler import assemble_prompt  # noqa: E402
from routes.support.generation_request import GenerationRequest  # noqa: E402
from config import Config  # noqa: E402


def test_double_braces_are_plain_template_text():
    """移除变量功能后，旧模板中的双大括号必须按普通文字原样保留。"""
    template = SimpleNamespace(
        is_active=True,
        category="plot",
        content="主角看到纸条上写着：{{不要替换我}}。",
    )

    assembled = assemble_prompt([template])

    assert "{{不要替换我}}" in assembled


def test_prompt_assembler_no_longer_accepts_variable_values():
    assert "variable_values" not in inspect.signature(assemble_prompt).parameters


def test_legacy_variable_payload_is_ignored_by_generation_request():
    request = GenerationRequest.from_mapping({"variable_values": {"姓名": "林舟"}})

    assert not hasattr(request, "variable_values")


def test_generation_system_prompt_no_longer_mentions_placeholders():
    assert "占位符" not in Config.GENERATION_SYSTEM_PROMPT
    assert "只输出成稿" in Config.GENERATION_SYSTEM_PROMPT
