/**
 * Flora Editor - 应用入口
 * 负责全局 UI 初始化（主题、导航、密钥、模型选择器、工作台草稿）与应用启动。
 */
import { $, $$, api } from './utils.js';
import { state, DRAFT_KEY, DRAFT_FIELDS } from './state.js';
import { initZoom } from './zoom.js';
import { initWorkflowCanvas } from './workflowCanvas.js';
import { initOnboarding } from './onboarding.js';
import {
    getWorkspaceStyleMode,
    updateWorkspaceStyleModeHelp,
} from './styleSettings.js';
import { loadWorkspaceTemplates } from './templatePanel.js';
import { loadTemplatesList } from './templateManager.js';
import { loadHistoryList } from './history.js';
// 副作用模块：模块加载时即完成各自的事件绑定，需显式导入以触发执行
import './promptPreview.js';
import './generation.js';
import './resultEditor.js';
import { loadCorporaList } from './styleCorpora.js';

// ==================== 主题切换 ====================

function initTheme() {
    document.documentElement.setAttribute('data-theme', state.theme);
    $('#theme-toggle').textContent = state.theme === 'dark' ? '🌙' : '☀️';

    $('#theme-toggle').addEventListener('click', () => {
        state.theme = state.theme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', state.theme);
        $('#theme-toggle').textContent = state.theme === 'dark' ? '🌙' : '☀️';
        localStorage.setItem('flora_theme', state.theme);
    });
}

// ==================== 导航标签切换 ====================

function initTabs() {
    $$('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            state.currentTab = tabName;

            $$('.nav-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            $$('.tab-content').forEach(c => c.classList.remove('active'));
            $(`#tab-${tabName}`).classList.add('active');

            if (tabName === 'templates') loadTemplatesList();
            if (tabName === 'styles') loadCorporaList();
            if (tabName === 'history') loadHistoryList();
            if (tabName === 'workspace') loadWorkspaceTemplates();
        });
    });
}

// ==================== API密钥 ====================

function initApiKey() {
    const input = $('#api-key-input');
    const toggle = $('#api-key-toggle');

    toggle.addEventListener('click', () => {
        state.showApiKey = !state.showApiKey;
        input.type = state.showApiKey ? 'text' : 'password';
        toggle.textContent = state.showApiKey ? '🙈' : '👁';
    });
}

// ==================== 模型选择器 ====================

function initModelSelector() {
    const providerSelect = $('#provider-select');
    const modelSelect = $('#model-select');

    // 加载模型列表
    api('/api/generation/models').then(data => {
        state.models = data.data;
        updateModelOptions();
    }).catch(e => console.warn('加载模型列表失败:', e));

    providerSelect.addEventListener('change', updateModelOptions);
    modelSelect.addEventListener('change', updateThinkingAvailability);

    function updateModelOptions() {
        const provider = providerSelect.value;
        const models = state.models[provider]?.models || [];

        modelSelect.innerHTML = models.map(m =>
            `<option value="${m.id}">${m.name}${m.supports_thinking ? ' 🧠' : ''}</option>`
        ).join('');
        updateThinkingAvailability();
    }

    function updateThinkingAvailability() {
        const provider = providerSelect.value;
        const selectedModel = state.models[provider]?.models?.find(
            model => model.id === modelSelect.value
        );
        const thinking = $('#thinking-enabled');
        const label = thinking.closest('.thinking-toggle');
        const mode = selectedModel?.thinking_mode;

        if (!selectedModel?.supports_thinking) {
            thinking.checked = false;
            thinking.disabled = true;
            label.title = '当前模型不支持思考模式';
        } else if (mode === 'always') {
            thinking.checked = true;
            thinking.disabled = true;
            label.title = '当前模型固定启用思考模式';
        } else {
            thinking.disabled = false;
            label.title = '启用思考模式';
        }
    }
}

// ==================== 工作台草稿 ====================

/** 保存工作台表单草稿到 localStorage */
function saveWorkspaceDraft() {
    const draft = {};
    DRAFT_FIELDS.forEach(id => {
        const el = $(`#${id}`);
        if (el) draft[id] = el.type === 'checkbox' ? el.checked : el.value;
    });
    draft.styleMode = getWorkspaceStyleMode();
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
}

/** 恢复工作台草稿并绑定自动保存 */
function restoreWorkspaceDraft() {
    try {
        const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}');
        DRAFT_FIELDS.forEach(id => {
            const el = $(`#${id}`);
            if (!el || draft[id] === undefined) return;
            if (el.type === 'checkbox') el.checked = Boolean(draft[id]);
            else el.value = draft[id];
        });
        const styleMode = draft.styleMode || 'legacy';
        // 'off' 模式已移除，历史草稿中若残留则回退默认"原文拼接"
        const modeInput = $(`input[name="workspace-style-mode"][value="${styleMode}"]`)
            || $('input[name="workspace-style-mode"]:checked')
            || $('input[name="workspace-style-mode"]');
        if (modeInput) modeInput.checked = true;
        updateWorkspaceStyleModeHelp();
        $$('input[name="workspace-style-mode"]').forEach(input => {
            input.addEventListener('change', () => {
                updateWorkspaceStyleModeHelp();
                saveWorkspaceDraft();
            });
        });
        document.addEventListener('input', event => {
            if (event.target.matches('input, textarea, select')) saveWorkspaceDraft();
        });
        window.addEventListener('beforeunload', saveWorkspaceDraft);
    } catch (e) {
        console.warn('草稿恢复失败:', e);
    }
}

// ==================== 启动 ====================

function init() {
    initZoom();
    initWorkflowCanvas();
    initOnboarding();
    initTheme();
    initTabs();
    initApiKey();
    initModelSelector();
    restoreWorkspaceDraft();

    // 将样式卡/语料库面板提升到 body 层级：
    // 该面板原本嵌在「模板管理」标签页内的隐藏容器中（display:none），
    // 导致工作台的「管理语料库」按钮打开面板后不可见（fixed 元素被隐藏祖先吞掉）。
    // 面板为 position:fixed，移到 body 下不影响样式，且所有 JS 均按 ID 查找、无父级依赖。
    const styleCardPanel = document.getElementById('style-card-panel');
    if (styleCardPanel) document.body.appendChild(styleCardPanel);

    // 初始加载工作台模板
    loadWorkspaceTemplates();
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', init);
