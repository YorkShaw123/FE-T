import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _connection_states(export_name, options):
    script = f"""
import {{ {export_name} }} from './server/static/js/workflowCanvas.js';
const options = JSON.parse(process.argv[1]);
process.stdout.write(JSON.stringify({export_name}(options)));
"""
    result = subprocess.run(
        ['node', '--input-type=module', '-e', script, json.dumps(options)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_style_reference_connections_remain_visible_when_disabled():
    states = _connection_states('getPostProcessConnectionStates', {
        'deaiEnabled': False,
        'styleReferenceEnabled': False,
        'phase': '',
    })

    assert [(item['from'], item['to']) for item in states] == [
        (4, 5), (4, 6), (5, 7), (6, 7),
    ]
    style_paths = [item for item in states if item['key'] == 'styleReference']
    assert len(style_paths) == 2
    assert all(item['enabled'] is False for item in style_paths)
    assert all(item['flowing'] is False for item in style_paths)


def test_only_enabled_active_stage_connections_flow():
    states = _connection_states('getPostProcessConnectionStates', {
        'deaiEnabled': False,
        'styleReferenceEnabled': True,
        'phase': 'style',
    })

    style_paths = [item for item in states if item['key'] == 'styleReference']
    deai_paths = [item for item in states if item['key'] == 'deai']
    assert all(item['enabled'] is True and item['flowing'] is True for item in style_paths)
    assert all(item['enabled'] is False and item['flowing'] is False for item in deai_paths)


def test_input_connections_use_each_input_control_and_only_active_inputs_flow():
    disabled = _connection_states('getBaseConnectionStates', {
        'promptOrchestrationEnabled': False,
        'styleCardEnabled': False,
        'contextEnabled': False,
        'phase': 'draft',
    })
    mixed = _connection_states('getBaseConnectionStates', {
        'promptOrchestrationEnabled': True,
        'styleCardEnabled': False,
        'contextEnabled': True,
        'phase': 'draft',
    })

    assert [(item['from'], item['to']) for item in disabled] == [(1, 4), (2, 4), (3, 4)]
    assert all(item['enabled'] is False and item['flowing'] is False for item in disabled)
    assert [(item['enabled'], item['flowing']) for item in mixed] == [
        (True, True), (False, False), (True, True),
    ]
