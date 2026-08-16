/**
 * Flora Editor - 提示词预览抽屉
 * 负责提示词预览的展开/收起、Token 预算渲染、风格片段选择渲染与预览请求。
 */
import { $, api, toast, escapeHtml, safeBind } from './utils.js';
import { getActiveTemplateIds } from './state.js';
import { getWorkspaceStyleMode } from './styleSettings.js';
import { getSelectedCorpusIds, getEmbeddingApiKey } from './styleCorpora.js';
import { getWorkspaceVariableValues } from './templatePanel.js';

/** 展开/收起提示词预览抽屉 */
export function setPromptPreviewDrawer(open) {
    const drawer = $('#prompt-preview-drawer');
    const toggle = $('#btn-toggle-preview-drawer');
    if (!drawer || !toggle) return;
    drawer.classList.toggle('is-open', open);
    drawer.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-expanded', String(open));
    toggle.title = open ? '收起提示词预览' : '展开提示词预览';
}

safeBind('#btn-toggle-preview-drawer', 'click', () => {
    setPromptPreviewDrawer(!$('#prompt-preview-drawer').classList.contains('is-open'));
});
safeBind('#btn-collapse-preview-drawer', 'click', () => setPromptPreviewDrawer(false));
document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && $('#prompt-preview-drawer')?.classList.contains('is-open')) {
        setPromptPreviewDrawer(false);
    }
});

/** 展示/隐藏智能风格链回退告警横幅（预览与生成共用） */
export function renderStyleFallbackWarning(styleMode, styleMetadata) {
    const banner = $('#prompt-preview-fallback');
    if (!banner) return;
    if (styleMode !== 'smart_fallback_legacy') {
        banner.style.display = 'none';
        banner.innerHTML = '';
        return;
    }
    const reason = styleMetadata?.fallback_reason || '没有可用的 Style Card';
    banner.innerHTML = `<strong>⚠️ 智能风格链未生效，已回退为普通提示词</strong>` +
        `${escapeHtml(reason)}。本次生成不会使用参考风格，` +
        `可前往「模板管理 → 范例文章」分析 Style Card 后重新生成。`;
    banner.style.display = '';
}

/** 组装提示词预览请求负载 */
export function buildPromptPreviewPayload() {
    return {
        variable_values: getWorkspaceVariableValues(),
        previous_article: $('#previous-article').value,
        template_ids: getActiveTemplateIds(),
        provider: $('#provider-select').value,
        model: $('#model-select').value,
        deai_enabled: $('#deai-enabled').checked,
        deai_prompt: $('#deai-prompt').value,
        strict_style_rewrite_enabled: $('#strict-style-rewrite-enabled')?.checked || false,
        thinking_enabled: $('#thinking-enabled').checked,
        reasoning_effort: 'high',
        structured_prompt_enabled: $('#structured-prompt-enabled').checked,
        style_mode: getWorkspaceStyleMode(),
        scene_type: 'auto',
        // Style RAG：已勾选的语料库 + Embedding 密钥（缺省回退顶部 LLM 密钥）
        style_corpus_ids: getSelectedCorpusIds(),
        embedding_api_key: getEmbeddingApiKey() || $('#api-key-input')?.value.trim() || '',
    };
}

/** 渲染 Token 预算面板 */
export function renderTokenBudget(budget) {
    const panel = $('#token-budget-panel');
    const summary = $('#workspace-token-summary');
    if (!budget) return;
    const labels = { safe: '预算充足', warning: '接近上限', over: '已超限' };
    const phaseLabels = { primary: '正文生成', deai: '去 AI 味', style_rewrite: '严格文风重写' };
    const rows = Object.entries(budget.phases).map(([key, phase]) => {
        const percent = Math.max(0, Math.round(phase.usage_ratio * 100));
        const width = Math.min(100, percent);
        const remaining = phase.remaining_tokens >= 0
            ? `剩余 ${phase.remaining_tokens.toLocaleString()}`
            : `超出 ${Math.abs(phase.remaining_tokens).toLocaleString()}`;
        return `<div class="token-budget-phase ${phase.status}">
            <div class="token-budget-row"><strong>${phaseLabels[key] || key}</strong>
                <span>${phase.input_tokens.toLocaleString()} / ${phase.usable_input_tokens.toLocaleString()} Token · ${remaining}</span></div>
            <div class="token-budget-track"><span style="width:${width}%"></span></div>
            <small>模型窗口 ${phase.context_window.toLocaleString()} · 输出预留 ${phase.output_reserved_tokens.toLocaleString()} · 安全余量 ${phase.safety_reserved_tokens.toLocaleString()}</small>
        </div>`;
    }).join('');
    if (panel) {
        panel.className = `token-budget-panel ${budget.status}`;
        panel.innerHTML = `<div class="token-budget-heading"><span>Token 预算（估算）</span><strong>${labels[budget.status] || budget.status}</strong></div>${rows}`;
        panel.style.display = '';
    }
    if (summary) {
        const primary = budget.phases?.primary;
        summary.className = `workspace-token-summary ${budget.status}`;
        summary.innerHTML = primary
            ? `<span>预计输入</span><strong>${primary.input_tokens.toLocaleString()} Token</strong><small>${labels[budget.status] || budget.status} · 生成前估算</small>`
            : `<span>Token 预算</span><strong>${labels[budget.status] || budget.status}</strong><small>生成前估算</small>`;
    }
}

/** 渲染智能风格链本次选中的风格片段 */
function renderStyleSelection(metadata, styleMode) {
    const panel = $('#style-selection-panel');
    if (!panel) return;
    if (!metadata || !String(styleMode || '').startsWith('smart')) {
        panel.style.display = 'none';
        return;
    }
    const sceneLabels = {
        dialogue: '对话', action: '动作', psychology: '心理', environment: '环境',
        transition: '转场', narration: '叙事', mixed: '综合',
    };
    const excerpts = metadata.selected_excerpts || [];
    let modeText;
    if (metadata.selection_mode === 'style_rag') {
        modeText = `已从 ${excerpts.length} 个风格语料库片段中混合检索（场景 ${
            sceneLabels[metadata.resolved_scene_type] || metadata.resolved_scene_type || '自动'
        }）`;
    } else if (metadata.selection_mode === 'scene_retrieval') {
        modeText = `已按“${sceneLabels[metadata.resolved_scene_type] || '综合'}”场景检索`;
    } else {
        modeText = '片段库尚未建立，暂用代表性开头';
    }
    const cards = excerpts.map(item => `
        <div class="style-selection-item">
            <div><strong>${escapeHtml(item.template_name || item.source || '风格片段')}</strong><span>${sceneLabels[item.scene_type] || item.scene_type} · ${item.pace || item.pacing || ''} · ${item.char_count} 字</span></div>
            <small>评分 ${item.score} · ${escapeHtml((item.reasons || []).join('、') || '综合匹配')}</small>
        </div>
    `).join('');
    panel.innerHTML = `<div class="style-selection-heading"><strong>本次风格片段</strong><span>${modeText}</span></div>${cards}`;
    panel.style.display = '';
}

/** 请求提示词预览 */
export async function fetchPromptPreview() {
    return api('/api/generation/preview-prompt', {
        method: 'POST',
        body: JSON.stringify(buildPromptPreviewPayload()),
    });
}

safeBind('#btn-preview-prompt', 'click', async () => {
    try {
        const previewData = await fetchPromptPreview();

        const section = $('#prompt-preview-section');
        if (!section) return;
        $('#prompt-preview-empty').style.display = 'none';
        $('#prompt-preview-content').textContent = previewData.data.assembled_prompt;
        $('#prompt-preview-content').style.display = '';
        $('#prompt-preview-meta').style.display = '';
        const promptModeLabels = {
            legacy: '兼容字符串', structured: '结构化消息', 'smart-style': '智能风格链',
        };
        const fallback = previewData.data.style_mode === 'smart_fallback_legacy'
            ? ` · 已回退：${previewData.data.style_metadata?.fallback_reason || 'Style Card 不可用'}`
            : '';
        $('#prompt-preview-meta').textContent =
            `${promptModeLabels[previewData.data.prompt_mode] || previewData.data.prompt_mode} · ${previewData.data.message_count} 条消息 · ${previewData.data.template_count} 个模板 · ${previewData.data.char_count.toLocaleString()} 字符${fallback} · Token 为保守估算`;
        renderTokenBudget(previewData.data.token_budget);
        renderStyleSelection(previewData.data.style_metadata, previewData.data.style_mode);
        renderStyleFallbackWarning(previewData.data.style_mode, previewData.data.style_metadata);
        if (previewData.data.style_mode === 'smart_fallback_legacy') {
            toast('智能风格链未生效：' + (previewData.data.style_metadata?.fallback_reason || '缺少有效的 Style Card'), 'warning', 5000);
        }
        $('#btn-close-preview').style.display = '';
        toast(`提示词共 ${previewData.data.char_count} 字符，使用 ${previewData.data.template_count} 个模板`);
    } catch (e) {
        toast('预览失败: ' + e.message, 'error');
    }
});

safeBind('#btn-close-preview', 'click', () => {
    $('#prompt-preview-content').textContent = '';
    $('#prompt-preview-content').style.display = 'none';
    $('#prompt-preview-fallback').style.display = 'none';
    $('#prompt-preview-meta').style.display = 'none';
    $('#token-budget-panel').style.display = 'none';
    const summary = $('#workspace-token-summary');
    if (summary) {
        summary.className = 'workspace-token-summary idle';
        summary.innerHTML = '<span>Token 预算</span><strong>等待预检</strong><small>点击生成或提示词预览后显示</small>';
    }
    $('#style-selection-panel').style.display = 'none';
    $('#prompt-preview-empty').style.display = '';
    $('#btn-close-preview').style.display = 'none';
});
