/**
 * Flora Editor - 文章生成与结果展示
 * 负责去AI味开关、流式生成流程、结果渲染、复制与下载。
 */
import { $, api, toast, safeBind, formatArticle, getArticleText } from './utils.js';
import { state, getActiveTemplateIds } from './state.js';
import { getWorkspaceStyleMode } from './styleSettings.js';
import { getSelectedCorpusIds, getEmbeddingApiKey } from './styleCorpora.js';
import { renderTokenBudget } from './promptPreview.js';
import { getAdvancedParams } from './advancedParams.js';

/** 更新工作台连线「正在处理」阶段（draft / deai / style / 空）并触发重绘 */
export function setFlowPhase(phase) {
    document.body.dataset.flowPhase = phase || '';
    document.dispatchEvent(new CustomEvent('flora:flow-phase'));
}

// ==================== 去AI味开关 ====================

safeBind('#deai-enabled', 'change', function () {
    const textarea = $('#deai-prompt');
    if (!textarea) return;
    textarea.style.display = this.checked ? '' : 'none';

    if (this.checked && !textarea.value) {
        api('/api/generation/default-deai-prompt').then(data => {
            if (this.checked && !textarea.value) {
                textarea.value = data.data;
                textarea.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }).catch(() => {});
    }
});

// ==================== 文章生成 ====================

safeBind('#btn-generate', 'click', () => runGeneration());

/** 触发一次完整生成；options.continueFrom 非空时表示续写（把已有正文作为前置文章） */
async function runGeneration(options = {}) {
    if (state.isGenerating) return;

    state.pendingContinueText = options.continueFrom || null;
    $('#continue-hint').style.display = 'none';

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
    const styleReferenceEnabled = $('#style-reference-enabled')?.checked || false;
    if (styleReferenceEnabled && getSelectedCorpusIds().length === 0) {
        toast('已启用风格参考，请先在 06 节点选择至少一个文风语料库', 'warning');
        return;
    }

    // 提示词组装、Token 预算和 RAG 检索由同一个生成请求完成，避免先预览再生成
    // 导致百万字语料被连续检索两遍。画布表面的状态卡立即提供反馈。
    $('#btn-generate').disabled = true;
    $('#btn-generate').textContent = '正在准备…';
    setFlowPhase('draft');

    state.isGenerating = true;
    state.resultReady = false;
    state.generationController = new AbortController();
    $('#btn-open-result-editor').disabled = true;
    $('#btn-open-result-editor').title = '文章完整生成后才可编辑';
    $('#btn-open-draft-editor').disabled = true;
    $('#btn-open-draft-editor').title = '文章完整生成后才可编辑';

    // 重置显示区域，准备接收流式内容
    $('#draft-node').classList.remove('has-unread-result');
    $('#result-section').classList.remove('has-unread-result');
    $('#first-content').innerHTML = '';
    $('#deai-content').innerHTML = '';
    $('#style-rewrite-content').innerHTML = '';
    $('#final-content').innerHTML = '';
    $('#reasoning-section').style.display = 'none';
    $('#reasoning-content').textContent = '';
    $('#deai-content-section').style.display = 'none';
    $('#style-rewrite-content-section').style.display = 'none';
    $('#final-result-area').style.display = 'none';
    $('#first-content-section').style.display = '';
    $('#first-content-section').querySelector('.section-header h4').textContent = '第一版（生成中...）';

    // 连线进入「初稿生成」阶段
    setFlowPhase('draft');

    // 显示加载指示器
    $('#btn-generate').disabled = true;
    $('#btn-generate').style.display = 'none';
    $('#btn-stop-generate').style.display = '';
    $('#btn-stop-generate').disabled = false;
    $('#btn-stop-generate').textContent = '停止生成';

    try {
        await generateStream(
            apiKey, templateIds, deaiEnabled, styleReferenceEnabled,
            state.generationController.signal
        );
        state.resultReady = true;
        $('#btn-open-result-editor').disabled = false;
        $('#btn-open-result-editor').title = '进入全屏编辑';
        $('#btn-open-draft-editor').disabled = false;
        $('#btn-open-draft-editor').title = '进入全屏编辑';
        // 初稿已生成：04 节点闪光提示（07 最终成稿的闪光由流内 final 渲染负责）
        $('#draft-node').classList.add('has-unread-result');
    } catch (e) {
        setFlowPhase('');
        if (e.name === 'AbortError') {
            $('#first-content-section').querySelector('.section-header h4').textContent = '第一版（已停止）';
            toast('已停止生成，当前已生成的内容已保留', 'warning');
            // 已生成部分内容时，同样提供一键续写
            const currentText = getArticleText($('#final-content'))
                || getArticleText($('#style-rewrite-content'))
                || getArticleText($('#deai-content'))
                || getArticleText($('#first-content'));
            if (currentText.trim()) {
                $('#continue-hint-text').textContent = '生成被中断，文章可能不完整，可一键续写。';
                $('#continue-hint').style.display = 'flex';
            }
        } else {
            toast('生成失败: ' + e.message, 'error');
        }
    } finally {
        state.isGenerating = false;
        state.generationController = null;
        $('#btn-generate').disabled = false;
        $('#btn-generate').textContent = '生成文章';
        $('#btn-generate').style.display = '';
        $('#btn-stop-generate').style.display = 'none';
    }
}

/** 一键续写：把当前已生成正文作为前置文章，继续生成剩余内容 */
safeBind('#btn-continue-generate', 'click', async () => {
    if (state.isGenerating) return;
    const currentText = getArticleText($('#final-content'))
        || getArticleText($('#style-rewrite-content'))
        || getArticleText($('#deai-content'))
        || getArticleText($('#first-content'));
    if (!currentText.trim()) {
        toast('当前没有可续写的内容', 'warning');
        return;
    }
    toast('正在基于已有内容继续生成…', 'info');
    await runGeneration({ continueFrom: currentText });
});

safeBind('#btn-stop-generate', 'click', () => {
    if (!state.isGenerating || !state.generationController) return;
    const button = $('#btn-stop-generate');
    button.disabled = true;
    button.textContent = '正在停止…';
    state.generationController.abort();
});

/** 流式生成：通过 SSE 逐块接收并渲染第一版/思考链/去AI味内容 */
async function generateStream(apiKey, templateIds, deaiEnabled, styleReferenceEnabled, signal) {
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
            style_reference_enabled: styleReferenceEnabled,
            title: $('#article-title').value || '未命名',
            previous_article: state.pendingContinueText ?? $('#previous-article').value,
            template_ids: templateIds,
            structured_prompt_enabled: $('#structured-prompt-enabled').checked,
            style_mode: getWorkspaceStyleMode(),
            scene_type: 'auto',
            // Style RAG：远程索引仅使用独立 Embedding 密钥；本地/纯 Style 无需密钥。
            style_corpus_ids: getSelectedCorpusIds(),
            embedding_api_key: getEmbeddingApiKey(),
            // 高级采样参数（temperature/top_p/max_tokens/penalty 等，由后端按厂商能力过滤）
            sampling: getAdvancedParams(),
        }),
    });

    if (!response.ok) {
        const err = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
        throw new Error(err.error || '请求失败');
    }

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
    let streamFinishReason = null;
    let streamTruncated = false;
    let reasoningFallback = false;
    let samplingDropped = [];
    let serverFinalContent = '';
    let styleReferenceMetadata = {};

    // 状态更新
    function updateStatus() {
        if (isStyleRewritePhase) {
            $('#style-rewrite-content-section').style.display = '';
        } else if (isDeaiPhase) {
            $('#deai-content-section').style.display = '';
        } else {
            $('#first-content-section').querySelector('.section-header h4').textContent = '第一版（生成中...）';
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
            } else if (type === 'token_budget') {
                renderTokenBudget(data);
                if (data?.status === 'warning') {
                    toast('Token 预算已接近上限，生成结果可能受上下文长度影响', 'warning');
                }
            } else if (type === 'reasoning') {
                reasoningContent += data;
                $('#reasoning-section').style.display = '';
                $('#reasoning-content').textContent = reasoningContent;
            } else if (type === 'status' && data === 'prompt_preparing') {
                setFlowPhase('draft');
            } else if (type === 'status' && data === 'postprocess_start') {
                setFlowPhase('postprocess');
            } else if (type === 'status' && data === 'deai_start') {
                isDeaiPhase = true;
                setFlowPhase('deai');
                updateStatus();
            } else if (type === 'status' && data === 'deai_done') {
                isDeaiPhase = false;
                setFlowPhase('postprocess');
                $('#deai-content-section').style.display = '';
                $('#deai-content-section').querySelector('.section-header h4').textContent = '✅ 去AI味版';
            } else if (type === 'status' && data === 'style_reference_retrieving') {
                isDeaiPhase = false;
                setFlowPhase('style');
            } else if (type === 'status' && data === 'style_reference_start') {
                isDeaiPhase = false;
                isStyleRewritePhase = true;
                setFlowPhase('style');
                updateStatus();
                const hitCount = Number(eventData.details?.reference_count || 0);
                if (hitCount > 0) {
                    toast(`已从文风语料库检索到 ${hitCount} 个真实片段，正在进行风格参考改写…`);
                }
            } else if (type === 'status' && data === 'style_reference_done') {
                isStyleRewritePhase = false;
                setFlowPhase('postprocess');
                $('#style-rewrite-content-section').style.display = '';
                $('#style-rewrite-content-section').querySelector('.section-header h4').textContent = '✅ 风格参考终稿';
            } else if (type === 'status' && data === 'style_reference_skipped') {
                isStyleRewritePhase = false;
                setFlowPhase('postprocess');
                const reasonLabels = {
                    no_corpus_selected: '没有选择文风语料库',
                    no_reference_match: '没有找到可用的风格片段',
                    retrieval_failed: '本地风格检索失败',
                };
                toast(`风格参考已跳过：${reasonLabels[eventData.reason] || '当前语料不可用'}`, 'warning');
            } else if (type === 'complete') {
                currentRecordId = eventData.record_id;
                reasoningContent = eventData.reasoning_content || reasoningContent;
                firstContent = eventData.first_content || firstContent;
                deaiContent = eventData.deai_content || deaiContent;
                styleRewriteContent = eventData.style_reference_content
                    || eventData.style_rewrite_content || styleRewriteContent;
                styleReferenceMetadata = eventData.style_reference_metadata || {};
                serverFinalContent = eventData.final_content || serverFinalContent;
                streamFinishReason = eventData.finish_reason || null;
                streamTruncated = !!eventData.truncated;
                reasoningFallback = !!eventData.reasoning_fallback;
                samplingDropped = eventData.sampling_dropped || [];
            } else if (type === 'error') {
                throw new Error(data);
            }
        }
    }

    // 流结束，最终渲染
    setFlowPhase('');
    $('#first-content-section').querySelector('.section-header h4').textContent = '第一版（原始）';

    // 思维链混入正文的兜底：正文为空时后端已把思维链回显，这里打上系统提示标记
    if (reasoningFallback && firstContent) {
        $('#first-content').innerHTML =
            '<p class="reasoning-fallback-mark">[系统提示：模型未按格式返回，已保留思维链文本]</p>'
            + formatArticle(firstContent);
    }

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
        $('#style-rewrite-content-section').querySelector('.section-header h4').textContent = '✅ 风格参考终稿';
        $('#style-rewrite-content').innerHTML = formatArticle(styleRewriteContent);
    }

    // 最终成稿：仅在启用语言自然化或 RAG 风格参考时输出至「07 最终成稿」
    const postProcessEnabled = deaiEnabled || styleReferenceEnabled;
    const finalContent = postProcessEnabled
        ? (serverFinalContent || styleRewriteContent || deaiContent || firstContent)
        : '';
    if (finalContent) {
        $('#final-content').innerHTML = formatArticle(finalContent);
        $('#final-result-area').style.display = '';
        $('#result-section').classList.add('has-unread-result');
    }

    // 厂商不支持的采样参数提示：让用户知道哪些高级参数被忽略
    if (samplingDropped && samplingDropped.length) {
        const names = samplingDropped.map(k => `“${k}”`).join('、');
        toast(`当前模型服务商不支持高级参数：${names}，本次已忽略`, 'warning', 5000);
    }

    // 截断（max_tokens 触顶）或流未正常结束 → 提供一键续写
    if ((currentRecordId === null || streamTruncated) && (firstContent || deaiContent || styleRewriteContent)) {
        $('#continue-hint-text').textContent = streamTruncated
            ? '已达到单次输出长度上限，文章可能缺少结尾，可一键续写。'
            : '生成被中断，文章可能不完整，可一键续写。';
        $('#continue-hint').style.display = 'flex';
    }

    state.currentRecordId = currentRecordId;
    const referenceCount = (styleReferenceMetadata.selected_excerpts || []).length;
    toast('文章生成成功！' + (styleRewriteContent
        ? `已应用${referenceCount ? ` ${referenceCount} 个` : ''} RAG 风格参考片段。`
        : (deaiContent ? '已应用去AI味处理。' : '')));
}

/** 渲染同步生成结果（同步接口保留） */
function displayResult(response) {
    const section = $('#result-section');
    section.style.display = '';
    setFlowPhase('');
    $('#final-result-area').style.display = 'none';
    $('#first-content-section').style.display = '';

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

    const styleReferenceContent = response.style_reference_content || response.style_rewrite_content;
    if (styleReferenceContent) {
        $('#style-rewrite-content-section').style.display = '';
        $('#style-rewrite-content').innerHTML = formatArticle(styleReferenceContent);
    } else {
        $('#style-rewrite-content-section').style.display = 'none';
    }

    // 最终成稿：仅在启用语言自然化或 RAG 风格参考时输出至「07 最终成稿」
    const postProcessEnabled = $('#deai-enabled')?.checked
        || $('#style-reference-enabled')?.checked;
    const finalContent = postProcessEnabled
        ? (response.final_content || styleReferenceContent
            || response.deai_content || response.first_content || response.content)
        : '';
    if (finalContent) {
        $('#final-content').innerHTML = formatArticle(finalContent);
        $('#final-result-area').style.display = '';
    }

    // 保存记录ID
    state.currentRecordId = response.record?.id;
    state.resultReady = true;
    $('#btn-open-result-editor').disabled = false;
    $('#btn-open-result-editor').title = '进入全屏编辑';
    $('#btn-open-draft-editor').disabled = false;
    $('#btn-open-draft-editor').title = '进入全屏编辑';
    section.classList.add('has-unread-result');
    $('#draft-node').classList.add('has-unread-result');

    section.scrollIntoView({ behavior: 'smooth' });
}

// ==================== 复制与下载 ====================

safeBind('#btn-copy-result', 'click', () => {
    const content = getArticleText($('#final-content'))
        || getArticleText($('#style-rewrite-content'))
        || getArticleText($('#deai-content'))
        || getArticleText($('#first-content'));

    navigator.clipboard.writeText(content).then(() => {
        toast('已复制到剪贴板');
    }).catch(() => {
        toast('复制失败，请手动复制', 'error');
    });
});

safeBind('#btn-copy-draft', 'click', () => {
    const content = getArticleText($('#first-content'));
    navigator.clipboard.writeText(content).then(() => {
        toast('已复制初稿');
    }).catch(() => {
        toast('复制失败，请手动复制', 'error');
    });
});

safeBind('#btn-download-result', 'click', () => {
    const content = getArticleText($('#final-content'))
        || getArticleText($('#style-rewrite-content'))
        || getArticleText($('#deai-content'))
        || getArticleText($('#first-content'));
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

safeBind('#btn-download-draft', 'click', () => {
    const content = getArticleText($('#first-content'));
    const title = $('#article-title').value || '未命名';
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${title}-初稿.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast('初稿已下载');
});
