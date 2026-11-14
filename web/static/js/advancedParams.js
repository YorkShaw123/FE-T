/** Flora Editor - 高级模型采样参数面板。 */
import { $, api, toast, escapeHtml, safeBind } from './utils.js';

const PARAM_ORDER = ['temperature', 'top_p', 'max_tokens', 'frequency_penalty', 'presence_penalty'];
const STORAGE_KEY = 'flora_sampling_params_v1';
let metaByProvider = {};
let noteByProvider = {};
let currentProvider = '';
let metaLoaded = false;

function loadSaved() {
    try {
        return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    } catch (_error) {
        return {};
    }
}

function saveValue(key, value) {
    const saved = loadSaved();
    if (value === null || Number.isNaN(value)) delete saved[key];
    else saved[key] = value;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
}

function renderPanel() {
    const list = $('#advanced-params-list');
    if (!list) return;
    const meta = metaByProvider[currentProvider] || {};
    const providerNote = $('#advanced-provider-note');
    if (providerNote) {
        providerNote.textContent = noteByProvider[currentProvider]
            || '当前服务商未声明额外限制；参数仍以所选模型的实际上游能力为准。';
    }
    const thinkingDisablesSampling = currentProvider === 'deepseek'
        && ($('#thinking-enabled')?.checked || false);
    const saved = loadSaved();
    list.innerHTML = PARAM_ORDER.map(key => {
        const info = meta[key] || {};
        const conditionallyDisabled = thinkingDisablesSampling && ['temperature', 'top_p'].includes(key);
        const supported = info.supported !== false && !conditionallyDisabled;
        const min = info.min ?? 0;
        const max = info.max ?? 1;
        const step = info.step ?? 0.1;
        const value = saved[key] ?? info.default ?? '';
        const description = escapeHtml(info.description || '暂无说明');
        return `<div class="advanced-param-row${supported ? '' : ' is-unsupported'}">
            <div class="advanced-param-label"><span>${escapeHtml(key)}</span>
                <span class="param-help-badge" tabindex="0" aria-label="${description}">?<span class="param-help-popover">${description}</span></span>
            </div>
            <div class="advanced-param-input">
                <input type="number" data-param="${escapeHtml(key)}" value="${value}"
                    ${supported ? `min="${min}" max="${max}" step="${step}"` : 'disabled'}>
                ${supported ? `<span class="advanced-param-range">${min} ~ ${max}</span>`
                    : `<span class="advanced-param-unsupported">${conditionallyDisabled
                        ? 'DeepSeek 思考模式下不生效' : '当前服务商不支持该参数'}</span>`}
            </div>
        </div>`;
    }).join('');
}

async function ensureMeta() {
    if (metaLoaded) return;
    try {
        const response = await api('/api/generation/models');
        const entries = Object.entries(response.data || {});
        metaByProvider = Object.fromEntries(entries.map(([key, config]) => [
            key, config.sampling?.parameters || config.sampling || {},
        ]));
        noteByProvider = Object.fromEntries(entries.map(([key, config]) => [
            key, config.sampling?.note || '',
        ]));
        metaLoaded = true;
        renderPanel();
    } catch (error) {
        console.warn('[Flora] 加载采样参数说明失败:', error);
    }
}

export function getAdvancedParams() {
    const meta = metaByProvider[currentProvider] || {};
    const saved = loadSaved();
    return Object.fromEntries(PARAM_ORDER.flatMap(key => {
        const value = saved[key];
        const deepseekThinkingDisabled = currentProvider === 'deepseek'
            && ($('#thinking-enabled')?.checked || false)
            && ['temperature', 'top_p'].includes(key);
        if (value === undefined || value === null || Number.isNaN(value)
            || meta[key]?.supported === false || deepseekThinkingDisabled) return [];
        return [[key, value]];
    }));
}

function initAdvancedParams() {
    const backdrop = $('#advanced-params-backdrop');
    const dialog = $('#advanced-params-dialog');
    const openButton = $('#btn-open-advanced');
    if (!backdrop || !dialog || !openButton) return;
    const provider = $('#provider-select');
    currentProvider = provider?.value || '';

    const open = () => {
        ensureMeta();
        renderPanel();
        backdrop.hidden = false;
        document.body.classList.add('onboarding-open');
        requestAnimationFrame(() => backdrop.classList.add('is-open'));
    };
    const close = () => {
        backdrop.classList.remove('is-open');
        backdrop.hidden = true;
        document.body.classList.remove('onboarding-open');
        openButton.focus();
    };

    openButton.addEventListener('click', open);
    safeBind('#btn-close-advanced', 'click', close);
    safeBind('#btn-close-advanced-confirm', 'click', close);
    safeBind('#btn-reset-advanced', 'click', () => {
        localStorage.removeItem(STORAGE_KEY);
        renderPanel();
        toast('已恢复默认采样参数', 'info');
    });
    backdrop.addEventListener('click', event => { if (event.target === backdrop) close(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && !backdrop.hidden) close(); });
    document.addEventListener('input', event => {
        if (event.target.matches('#advanced-params-list input[type="number"]')) {
            saveValue(event.target.dataset.param, parseFloat(event.target.value));
        }
    });
    provider?.addEventListener('change', () => {
        currentProvider = provider.value;
        renderPanel();
    });
    $('#thinking-enabled')?.addEventListener('change', renderPanel);
    ensureMeta();
}

initAdvancedParams();
