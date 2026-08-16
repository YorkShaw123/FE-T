/**
 * Flora Editor - 文章生成与结果展示
 * 负责去AI味开关、流式生成流程、结果渲染、复制与下载。
 */
import { $, api, toast, safeBind, formatArticle, getArticleText } from './utils.js';
import { state, getActiveTemplateIds } from './state.js';
import { getWorkspaceStyleMode } from './styleSettings.js';
import { getSelectedCorpusIds, getEmbeddingApiKey } from './styleCorpora.js';
import { fetchPromptPreview, renderTokenBudget, renderStyleFallbackWarning } from './promptPreview.js';
import { getWorkspaceVariableValues } from './templatePanel.js';

// ==================== 去AI味开关 ====================

safeBind('#deai-enabled', 'change', function () {
    const textarea = $('#deai-prompt');
    if (!textarea) return;
    textarea.style.display = this.checked ? '' : 'none';

    if (this.checked && !textarea.value) {
        api('/api/generation/default-deai-prompt').then(data => {
            textarea.value = data.data;
        }).catch(() => {});
    }
});

// ==================== 文章生成 ====================

safeBind('#btn-generate', 'click', async () => {
    if (state.isGenerating) return;

    const apiKey = $('#api-key-input').value.trim();
    if (!apiKey) {
        toast('请先在顶部输入API密钥', 'warning');
        $('#api-key-input').focus();
        return;
    }

    const templateIds = getActiveTemplateIds();
    if (templateIds.length === 0) {
        toast('请至少启用一个提示词模板', 'warning');
        return;
    }

    const deaiEnabled = $('#deai-enabled').checked;
    const strictStyleRewriteEnabled = $('#strict-style-rewrite-enabled')?.checked || false;

    try {
        const previewData = await fetchPromptPreview();
        renderTokenBudget(previewData.data.token_budget);
        if (previewData.data.token_budget.status === 'over') {
            $('#prompt-preview-empty').style.display = 'none';
            $('#prompt-preview-meta').style.display = '';
            $('#prompt-preview-meta').textContent = '生成已暂停：请先降低 Token 占用';
            toast('当前提示词预计超过模型上下文预算，请减少内容后重试', 'error');
            return;
        }
        if (previewData.data.token_budget.status === 'warning') {
            toast('Token 预算已接近上限，生成结果可能受上下文长度影响', 'warning');
        }
        if (previewData.data.style_mode === 'smart_fallback_legacy') {
            renderStyleFallbackWarning(previewData.data.style_mode, previewData.data.style_metadata);
            toast('智能风格链未生效，本次将按普通提示词生成：'
                + (previewData.data.style_metadata?.fallback_reason || '缺少有效的 Style Card'), 'warning', 5000);
        }
    } catch (e) {
        toast('Token 预算检查失败: ' + e.message, 'error');
        return;
    }

    state.isGenerating = true;
    state.resultReady = false;
    state.generationController = new AbortController();
    $('#btn-open-result-editor').disabled = true;
    $('#btn-open-result-editor').title = '文章完整生成后才可编辑';

    // 重置显示区域，准备接收流式内容
    $('#result-section').style.display = '';
    $('#result-section').classList.add('is-running');
    $('#first-content').innerHTML = '';
    $('#deai-content').innerHTML = '';
    $('#style-rewrite-content').innerHTML = '';
    $('#reasoning-section').style.display = 'none';
    $('#reasoning-content').textContent = '';
    $('#deai-content-section').style.display = 'none';
    $('#style-rewrite-content-section').style.display = 'none';
    $('#first-content-section').querySelector('.section-header h4').textContent = '第一版（生成中...）';

    // 显示加载指示器
    $('#loading-overlay').style.display = '';
    $('#loading-text').textContent = deaiEnabled ? '正在连接API，准备生成...' : '正在连接API，准备生成...';
    $('#btn-generate').disabled = true;
    $('#btn-generate').style.display = 'none';
    $('#btn-stop-generate').style.display = '';
    $('#btn-stop-generate').disabled = false;
    $('#btn-stop-generate').textContent = '停止生成';

    try {
        await generateStream(
            apiKey, templateIds, deaiEnabled, strictStyleRewriteEnabled,
            state.generationController.signal
        );
        state.resultReady = true;
        $('#btn-open-result-editor').disabled = false;
        $('#btn-open-result-editor').title = '进入全屏编辑';
    } catch (e) {
        $('#loading-overlay').style.display = 'none';
        if (e.name === 'AbortError') {
            $('#first-content-section').querySelector('.section-header h4').textContent = '第一版（已停止）';
            toast('已停止生成，当前已生成的内容已保留', 'warning');
        } else {
            toast('生成失败: ' + e.message, 'error');
        }
    } finally {
        $('#result-section').classList.remove('is-running');
        state.isGenerating = false;
        state.generationController = null;
        $('#btn-generate').disabled = false;
        $('#btn-generate').style.display = '';
        $('#btn-stop-generate').style.display = 'none';
    }
});

safeBind('#btn-stop-generate', 'click', () => {
    if (!state.isGenerating || !state.generationController) return;
    const button = $('#btn-stop-generate');
    button.disabled = true;
    button.textContent = '正在停止…';
    $('#loading-text').textContent = '正在停止生成…';
    state.generationController.abort();
});

/** 流式生成：通过 SSE 逐块接收并渲染第一版/思考链/去AI味内容 */
async function generateStream(apiKey, templateIds, deaiEnabled, strictStyleRewriteEnabled, signal) {
    // 使用 fetch + ReadableStream 读取 SSE 流
    const response = await fetch('/api/generation/generate-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal,
        body: JSON.stringify({
            api_key: apiKey,
            provider: $('#provider-select').value,
            model: $('#model-select').value,
            thinking_enabled: $('#thinking-enabled').checked,
            reasoning_effort: 'high',
            deai_enabled: deaiEnabled,
            deai_prompt: $('#deai-prompt').value,
            strict_style_rewrite_enabled: strictStyleRewriteEnabled,
            title: $('#article-title').value || '未命名',
            previous_article: $('#previous-article').value,
            variable_values: getWorkspaceVariableValues(),
            template_ids: templateIds,
            structured_prompt_enabled: $('#structured-prompt-enabled').checked,
            style_mode: getWorkspaceStyleMode(),
            scene_type: 'auto',
            // Style RAG：远程索引仅使用独立 Embedding 密钥；本地/纯 Style 无需密钥。
            style_corpus_ids: getSelectedCorpusIds(),
            embedding_api_key: getEmbeddingApiKey(),
        }),
    });

    if (!response.ok) {
        const err = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
        throw new Error(err.error || '请求失败');
    }

    $('#loading-overlay').style.display = 'none';

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    let firstContent = '';
    let deaiContent = '';
    let styleRewriteContent = '';
    let reasoningContent = '';
    let currentRecordId = null;
    let isDeaiPhase = false;
    let isStyleRewritePhase = false;

    // 状态更新
    function updateStatus() {
        if (isStyleRewritePhase) {
            $('#loading-overlay').style.display = '';
            $('#loading-text').textContent = '正在执行严格文风重写...';
            $('#style-rewrite-content-section').style.display = '';
        } else if (isDeaiPhase) {
            $('#loading-overlay').style.display = '';
            $('#loading-text').textContent = '正在去AI味处理...';
            $('#deai-content-section').style.display = '';
        } else {
            $('#loading-overlay').style.display = 'none';
            $('#loading-text').textContent = '';
            $('#first-content-section').querySelector('.section-header h4').textContent = '第一版（原始）';
        }
    }

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const jsonStr = line.slice(6);
            let eventData;
            try {
                eventData = JSON.parse(jsonStr);
            } catch {
                continue;
            }

            const type = eventData.type;
            const data = eventData.data;

            if (type === 'content') {
                if (isStyleRewritePhase) {
                    styleRewriteContent += data;
                    $('#style-rewrite-content').innerHTML = formatArticle(styleRewriteContent);
                } else if (isDeaiPhase) {
                    deaiContent += data;
                    $('#deai-content').innerHTML = formatArticle(deaiContent);
                } else {
                    firstContent += data;
                    $('#first-content').innerHTML = formatArticle(firstContent);
                }
            } else if (type === 'reasoning') {
                reasoningContent += data;
                $('#reasoning-section').style.display = '';
                $('#reasoning-content').textContent = reasoningContent;
            } else if (type === 'status' && data === 'deai_start') {
                isDeaiPhase = true;
                updateStatus();
            } else if (type === 'status' && data === 'deai_done') {
                isDeaiPhase = false;
                updateStatus();
                $('#deai-content-section').style.display = '';
                $('#deai-content-section').querySelector('.section-header h4').textContent = '✅ 去AI味版';
            } else if (type === 'status' && data === 'style_rewrite_start') {
                isDeaiPhase = false;
                isStyleRewritePhase = true;
                updateStatus();
            } else if (type === 'status' && data === 'style_rewrite_done') {
                isStyleRewritePhase = false;
                updateStatus();
                $('#style-rewrite-content-section').style.display = '';
                $('#style-rewrite-content-section').querySelector('.section-header h4').textContent = '✅ 严格文风终稿';
            } else if (type === 'complete') {
                currentRecordId = eventData.record_id;
                reasoningContent = eventData.reasoning_content || reasoningContent;
                firstContent = eventData.first_content || firstContent;
                deaiContent = eventData.deai_content || deaiContent;
                styleRewriteContent = eventData.style_rewrite_content || styleRewriteContent;
            } else if (type === 'error') {
                throw new Error(data);
            }
        }
    }

    // 流结束，最终渲染
    $('#loading-overlay').style.display = 'none';
    $('#first-content-section').querySelector('.section-header h4').textContent = '第一版（原始）';

    if (reasoningContent) {
        $('#reasoning-section').style.display = '';
        $('#reasoning-content').textContent = reasoningContent;
    }

    if (deaiContent) {
        $('#deai-content-section').style.display = '';
        $('#deai-content-section').querySelector('.section-header h4').textContent = '✅ 去AI味版';
        $('#deai-content').innerHTML = formatArticle(deaiContent);
    }

    if (styleRewriteContent) {
        $('#style-rewrite-content-section').style.display = '';
        $('#style-rewrite-content-section').querySelector('.section-header h4').textContent = '✅ 严格文风终稿';
        $('#style-rewrite-content').innerHTML = formatArticle(styleRewriteContent);
    }

    state.currentRecordId = currentRecordId;
    toast('文章生成成功！' + (styleRewriteContent
        ? '已应用严格文风重写。' : (deaiContent ? '已应用去AI味处理。' : '')));
}

/** 渲染同步生成结果（同步接口保留） */
function displayResult(response) {
    const section = $('#result-section');
    section.style.display = '';

    // 思维链
    if (response.reasoning_content) {
        $('#reasoning-section').style.display = '';
        $('#reasoning-content').textContent = response.reasoning_content;
    } else {
        $('#reasoning-section').style.display = 'none';
    }

    // 第一版
    $('#first-content').innerHTML = formatArticle(response.first_content || response.content);

    // 去AI味版
    if (response.deai_content) {
        $('#deai-content-section').style.display = '';
        $('#deai-content').innerHTML = formatArticle(response.deai_content);
    } else {
        $('#deai-content-section').style.display = 'none';
    }

    if (response.style_rewrite_content) {
        $('#style-rewrite-content-section').style.display = '';
        $('#style-rewrite-content').innerHTML = formatArticle(response.style_rewrite_content);
    } else {
        $('#style-rewrite-content-section').style.display = 'none';
    }

    // 保存记录ID
    state.currentRecordId = response.record?.id;
    state.resultReady = true;
    $('#btn-open-result-editor').disabled = false;
    $('#btn-open-result-editor').title = '进入全屏编辑';

    section.scrollIntoView({ behavior: 'smooth' });
}

// ==================== 复制与下载 ====================

safeBind('#btn-copy-result', 'click', () => {
    const styleRewriteContent = getArticleText($('#style-rewrite-content'));
    const deaiContent = getArticleText($('#deai-content'));
    const content = styleRewriteContent || deaiContent || getArticleText($('#first-content'));

    navigator.clipboard.writeText(content).then(() => {
        toast('已复制到剪贴板');
    }).catch(() => {
        toast('复制失败，请手动复制', 'error');
    });
});

safeBind('#btn-download-result', 'click', () => {
    const styleRewriteContent = getArticleText($('#style-rewrite-content'));
    const deaiContent = getArticleText($('#deai-content'));
    const content = styleRewriteContent || deaiContent || getArticleText($('#first-content'));
    const title = $('#article-title').value || '未命名';

    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${title}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast('文章已下载');
});
