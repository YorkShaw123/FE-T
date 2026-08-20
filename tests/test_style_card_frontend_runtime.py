import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_style_card_runtime():
    script = r"""
class FakeClassList {
    constructor() { this.values = new Set(); }
    toggle(name, force) {
        if (force === true) this.values.add(name);
        else if (force === false) this.values.delete(name);
        else if (this.values.has(name)) this.values.delete(name);
        else this.values.add(name);
        return this.values.has(name);
    }
}
class FakeElement {
    constructor() {
        this.value = '';
        this.textContent = '';
        this.innerHTML = '';
        this.checked = false;
        this.disabled = false;
        this.style = { display: 'none' };
        this.classList = new FakeClassList();
        this.listeners = {};
        this.scrollTop = 0;
    }
    addEventListener(name, handler) { this.listeners[name] = handler; }
    appendChild() {}
    remove() {}
    closest() { return elements.get('.style-card-panel-body'); }
    querySelector(selector) { return getElement(selector); }
    querySelectorAll() { return []; }
}
const elements = new Map();
function getElement(selector) {
    if (!elements.has(selector)) elements.set(selector, new FakeElement());
    return elements.get(selector);
}
globalThis.document = {
    querySelector: getElement,
    querySelectorAll: () => [],
    createElement: () => new FakeElement(),
};
globalThis.localStorage = { getItem: () => null, setItem: () => {} };
globalThis.setTimeout = () => 0;
function jsonResponse(payload) {
    return {
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: async () => payload,
    };
}

let releaseFirst;
const firstResponse = new Promise(resolve => { releaseFirst = resolve; });
let fetchMode = 'race';
let raceCalls = 0;
let releaseAnalysis;
const analysisResponse = new Promise(resolve => { releaseAnalysis = resolve; });
globalThis.fetch = async (url) => {
    if (fetchMode === 'race') {
        raceCalls += 1;
        if (raceCalls === 1) return firstResponse;
        return jsonResponse({ success: true, data: { analysis_status: 'missing', card: null } });
    }
    if (url.endsWith('/analyze')) return analysisResponse;
    return jsonResponse({ success: true, data: [] });
};

const module = await import('./server/static/js/styleCard.js');
getElement('#edit-template-id').value = '1';
getElement('#edit-template-name').value = '模板甲';
getElement('#edit-template-category').value = 'example';
const firstLoad = module.loadStyleProfile();
getElement('#edit-template-id').value = '2';
getElement('#edit-template-name').value = '模板乙';
const secondLoad = module.loadStyleProfile();
await secondLoad;
releaseFirst(jsonResponse({
    success: true,
    data: {
        analysis_status: 'ready',
        card: { summary: '不应渲染的旧卡片' },
    },
}));
await firstLoad;
const raceStatus = getElement('#style-card-status').textContent;
const raceTarget = getElement('#style-card-target').textContent;

fetchMode = 'analysis';
getElement('#edit-template-id').value = '2';
getElement('#api-key-input').value = 'test-key';
getElement('#provider-select').value = 'deepseek';
getElement('#model-select').value = 'deepseek-v4-pro';
getElement('.style-card-panel-body').scrollTop = 88;
const analyzePromise = getElement('#btn-analyze-style-card').listeners.click();
const visibleDuringRequest = getElement('#style-card-analysis-loading').style.display;
const scrollDuringRequest = getElement('.style-card-panel-body').scrollTop;
releaseAnalysis(jsonResponse({
    success: true,
    data: { analysis_status: 'missing', card: null },
}));
await analyzePromise;

process.stdout.write(JSON.stringify({
    raceStatus,
    raceTarget,
    visibleDuringRequest,
    scrollDuringRequest,
    hiddenAfterRequest: getElement('#style-card-analysis-loading').style.display,
    analyzeEnabledAfterRequest: !getElement('#btn-analyze-style-card').disabled,
}));
"""
    result = subprocess.run(
        ['node', '--input-type=module', '-e', script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=True,
        text=True,
        encoding='utf-8',
    )
    return json.loads(result.stdout)


def test_style_card_ignores_stale_response_and_exposes_analysis_progress():
    result = _run_style_card_runtime()

    assert result['raceStatus'] == '尚未分析'
    assert result['raceTarget'] == '分析对象：模板乙（范例文章模板）'
    assert result['visibleDuringRequest'] == 'flex'
    assert result['scrollDuringRequest'] == 0
    assert result['hiddenAfterRequest'] == 'none'
    assert result['analyzeEnabledAfterRequest'] is True
