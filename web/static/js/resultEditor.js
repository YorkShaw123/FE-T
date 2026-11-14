/**
 * Flora Editor - 生成结果全屏编辑器
 * 负责全屏 Markdown 编辑、局部 AI 处理（续写/重写/扩写/润色）、diff 对比与修改版保存。
 */
import { $, $$, api, toast, escapeHtml, safeBind, getArticleText } from './utils.js';
import { state } from './state.js';

/** 全屏编辑器局部状态 */
const resultEditState = {
    recordId: null,
    baseContent: '',
    editHistory: [],
    selectionStart: 0,
    selectionEnd: 0,
    selectedText: '',
    operation: 'rewrite',
    controller: null,
    dirty: false,
};

/** 将 Markdown 源文本渲染为简易 HTML 预览 */
function renderResultMarkdown() {
    const source = $('#result-markdown-editor').value;
    const inline = text => escapeHtml(text)
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>');
    let inList = false;
    const html = [];
    source.split('\n').forEach(line => {
        if (/^- /.test(line)) {
            if (!inList) { html.push('<ul>'); inList = true; }
            html.push(`<li>${inline(line.slice(2))}</li>`);
            return;
        }
        if (inList) { html.push('</ul>'); inList = false; }
        if (/^### /.test(line)) html.push(`<h3>${inline(line.slice(4))}</h3>`);
        else if (/^## /.test(line)) html.push(`<h2>${inline(line.slice(3))}</h2>`);
        else if (/^# /.test(line)) html.push(`<h1>${inline(line.slice(2))}</h1>`);
        else if (/^> /.test(line)) html.push(`<blockquote>${inline(line.slice(2))}</blockquote>`);
        else if (line.trim()) html.push(`<p>${inline(line)}</p>`);
        else html.push('<div class="markdown-spacer"></div>');
    });
    if (inList) html.push('</ul>');
    $('#result-markdown-preview').innerHTML = `<div class="editor-pane-label"><span>预览</span><small>实时排版</small></div>${
        html.join('') || '<div class="markdown-preview-empty">修改版预览</div>'
    }`;
}

/** 更新编辑器保存状态指示 */
function setResultEditorDirty(dirty) {
    resultEditState.dirty = dirty;
    $('#result-editor-save-state').textContent = dirty ? '有未保存修改' : '已保存';
    $('#result-editor-save-state').classList.toggle('dirty', dirty);
}

/** 打开全屏结果编辑器 */
export async function openResultEditor() {
    if (state.isGenerating) {
        toast('请等待生成结束或先停止生成', 'warning');
        return;
    }
    if (!state.resultReady) {
        toast('文章尚未完整生成，暂不能进入编辑', 'warning');
        return;
    }
    let base = getArticleText($('#final-content'))
        || getArticleText($('#style-rewrite-content'))
        || getArticleText($('#deai-content')) || getArticleText($('#first-content'));
    let edited = '';
    let history = [];
    if (state.currentRecordId) {
        try {
            const data = await api(`/api/generation/records/${state.currentRecordId}`);
            const record = data.data;
            base = record.final_content || record.deai_content || record.content || base;
            edited = record.edited_content || '';
            history = JSON.parse(record.edit_history || '[]');
        } catch (error) {
            toast('读取生成记录失败，将编辑当前页面内容', 'warning');
        }
    }
    if (!base && !edited) {
        toast('当前没有可编辑的生成结果', 'warning');
        return;
    }
    resultEditState.recordId = state.currentRecordId;
    resultEditState.baseContent = base;
    resultEditState.editHistory = Array.isArray(history) ? history : [];
    resultEditState.selectedText = '';
    $('#result-markdown-editor').value = edited || base;
    $('#result-editor-title').textContent = `修改生成结果 · ${$('#article-title').value || '未命名'}`;
    $('#result-selection-status').textContent = '请在左侧选中需要处理的文字';
    $('#btn-result-transform').disabled = true;
    $('#result-comparison-overlay').style.display = 'none';
    // 该面板本身是三行 CSS Grid；使用 flex 会破坏标题栏、工具栏和正文区的排版。
    $('#result-editor-panel').style.display = 'grid';
    document.body.classList.add('result-editor-open');
    renderResultMarkdown();
    setResultEditorDirty(false);
}

safeBind('#btn-open-result-editor', 'click', openResultEditor);
safeBind('#btn-open-draft-editor', 'click', openResultEditor);
safeBind('#btn-close-result-editor', 'click', () => {
    if (resultEditState.dirty && !confirm('修改版尚未保存，确定退出吗？')) return;
    $('#result-editor-panel').style.display = 'none';
    document.body.classList.remove('result-editor-open');
});

safeBind('#result-markdown-editor', 'input', () => {
    renderResultMarkdown();
    setResultEditorDirty(true);
});

/** 捕获编辑器当前选区，作为局部 AI 处理的目标 */
function captureResultSelection() {
    const editor = $('#result-markdown-editor');
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const text = editor.value.slice(start, end);
    resultEditState.selectionStart = start;
    resultEditState.selectionEnd = end;
    resultEditState.selectedText = text;
    $('#btn-result-transform').disabled = !text.trim();
    $('#result-selection-status').textContent = text.trim()
        ? `已选择 ${text.trim().length.toLocaleString()} 字`
        : '请在左侧选中需要处理的文字';
}
['select', 'keyup', 'mouseup'].forEach(eventName =>
    safeBind('#result-markdown-editor', eventName, captureResultSelection)
);

// 局部处理方式切换
$$('.result-selection-operation').forEach(button => {
    button.addEventListener('click', () => {
        $$('.result-selection-operation').forEach(item => item.classList.toggle('active', item === button));
        resultEditState.operation = button.dataset.operation;
    });
});

/** 计算原文与 AI 候选的公共前后缀，生成 diff 高亮 HTML */
function highlightedPair(original, proposed) {
    let prefix = 0;
    while (prefix < original.length && prefix < proposed.length && original[prefix] === proposed[prefix]) prefix++;
    let suffix = 0;
    while (
        suffix < original.length - prefix && suffix < proposed.length - prefix &&
        original[original.length - 1 - suffix] === proposed[proposed.length - 1 - suffix]
    ) suffix++;
    const originalMiddle = original.slice(prefix, original.length - suffix || original.length);
    const proposedMiddle = proposed.slice(prefix, proposed.length - suffix || proposed.length);
    const commonPrefix = escapeHtml(original.slice(0, prefix));
    const commonSuffix = escapeHtml(suffix ? original.slice(original.length - suffix) : '');
    return {
        original: `${commonPrefix}<span class="diff-removed">${escapeHtml(originalMiddle)}</span>${commonSuffix}`,
        proposed: `${commonPrefix}<span class="diff-added">${escapeHtml(proposedMiddle)}</span>${commonSuffix}`,
    };
}

// 局部 AI 处理
safeBind('#btn-result-transform', 'click', async () => {
    captureResultSelection();
    if (!resultEditState.selectedText.trim()) return;
    const apiKey = $('#api-key-input').value.trim();
    if (!apiKey) { toast('请先在顶部输入API密钥', 'warning'); return; }
    resultEditState.controller = new AbortController();
    $('#btn-result-transform').style.display = 'none';
    $('#result-transform-loading').style.display = '';
    try {
        const response = await fetch('/api/generation/transform-text', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: resultEditState.controller.signal,
            body: JSON.stringify({
                api_key: apiKey,
                provider: $('#provider-select').value,
                model: $('#model-select').value,
                operation: resultEditState.operation,
                text: resultEditState.selectedText,
                instruction: $('#result-selection-instruction').value,
                surrounding_context: $('#result-markdown-editor').value.slice(0, 8000),
            }),
        });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || '局部处理失败');
        const diff = highlightedPair(resultEditState.selectedText, result.data.content);
        $('#result-comparison-original').innerHTML = diff.original;
        $('#result-comparison-proposed').innerHTML = diff.proposed;
        $('#result-comparison-proposed').dataset.plainText = result.data.content;
        $('#result-comparison-overlay').style.display = 'grid';
    } catch (error) {
        if (error.name === 'AbortError') toast('已取消局部AI处理', 'warning');
        else toast('局部处理失败: ' + error.message, 'error');
    } finally {
        resultEditState.controller = null;
        $('#btn-result-transform').style.display = '';
        $('#result-transform-loading').style.display = 'none';
    }
});

safeBind('#btn-cancel-result-transform', 'click', () => resultEditState.controller?.abort());
['#btn-close-result-comparison', '#btn-discard-result-transform'].forEach(selector =>
    safeBind(selector, 'click', () => $('#result-comparison-overlay').style.display = 'none')
);
safeBind('#result-comparison-proposed', 'input', event => {
    event.currentTarget.dataset.plainText = event.currentTarget.innerText;
});

// 应用 AI 候选替换选中原文
safeBind('#btn-apply-result-transform', 'click', () => {
    const editor = $('#result-markdown-editor');
    const current = editor.value.slice(resultEditState.selectionStart, resultEditState.selectionEnd);
    if (current !== resultEditState.selectedText) {
        toast('原文位置已变化，请重新选择', 'warning');
        return;
    }
    const proposed = $('#result-comparison-proposed').dataset.plainText?.trim();
    if (!proposed) { toast('AI候选为空', 'warning'); return; }
    editor.setRangeText(proposed, resultEditState.selectionStart, resultEditState.selectionEnd, 'end');
    resultEditState.editHistory.push({
        operation: resultEditState.operation,
        original: resultEditState.selectedText,
        replacement: proposed,
        instruction: $('#result-selection-instruction').value.trim(),
        created_at: new Date().toISOString(),
    });
    $('#result-comparison-overlay').style.display = 'none';
    resultEditState.selectedText = '';
    $('#btn-result-transform').disabled = true;
    $('#result-selection-status').textContent = '已替换原文，可继续选择其他段落';
    renderResultMarkdown();
    setResultEditorDirty(true);
    toast('AI候选已替换选中原文', 'success');
});

// 保存修改版到生成记录
safeBind('#btn-save-result-edit', 'click', async () => {
    if (!resultEditState.recordId) {
        toast('当前内容尚未形成生成记录，暂时无法保存修改版', 'warning');
        return;
    }
    try {
        await api(`/api/generation/records/${resultEditState.recordId}`, {
            method: 'PUT',
            body: JSON.stringify({
                edited_content: $('#result-markdown-editor').value,
                edit_history: JSON.stringify(resultEditState.editHistory),
            }),
        });
        setResultEditorDirty(false);
        toast('修改版已保存到生成记录', 'success');
    } catch (error) {
        toast('保存修改版失败: ' + error.message, 'error');
    }
});

// Markdown 工具栏：前缀/包裹
$$('.result-editor-toolbar button[data-result-md-prefix], .result-editor-toolbar button[data-result-md-wrap]').forEach(button => {
    button.addEventListener('click', () => {
        const editor = $('#result-markdown-editor');
        const start = editor.selectionStart;
        const end = editor.selectionEnd;
        const selected = editor.value.slice(start, end);
        if (button.dataset.resultMdWrap) {
            const mark = button.dataset.resultMdWrap;
            editor.setRangeText(`${mark}${selected || '文字'}${mark}`, start, end, 'select');
        } else {
            const lineStart = editor.value.lastIndexOf('\n', start - 1) + 1;
            editor.setRangeText(button.dataset.resultMdPrefix, lineStart, lineStart, 'end');
        }
        editor.focus();
        editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
});
