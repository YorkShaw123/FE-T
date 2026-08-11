/**
 * Forestar Editor - 模板管理
 * 负责模板列表、分类筛选、新建/编辑/删除/导入导出、示例模板另存为、版本历史。
 */
import { $, $$, api, toast, escapeHtml, safeBind } from './utils.js';
import { state, categoryConfig } from './state.js';
import { loadWorkspaceTemplates } from './templatePanel.js';
import { loadStyleProfile } from './styleCard.js';

/** 当前模板列表的分类筛选 */
let currentTemplateCategory = 'all';

/** 加载模板列表并渲染 */
export async function loadTemplatesList() {
    try {
        const category = currentTemplateCategory === 'all' ? undefined : currentTemplateCategory;
        const data = await api(`/api/templates${category ? '?category=' + category : ''}`);
        state.templates = data.data;
        renderTemplateList(data.data);
    } catch (e) {
        console.error('加载模板列表失败:', e);
    }
}

/** 渲染模板列表（含搜索过滤与删除全部按钮） */
function renderTemplateList(templates) {
    const container = $('#template-list');
    const query = state.templateSearch.trim().toLowerCase();
    const filtered = query ? templates.filter(tpl =>
        [tpl.name, tpl.description, tpl.content].some(value =>
            String(value || '').toLowerCase().includes(query)
        )
    ) : templates;

    if (templates.length === 0) {
        container.innerHTML = `<p style="text-align:center;padding:40px;color:var(--text-muted);">
            该分类下暂无模板，点击左侧"新建模板"添加
        </p>`;
        return;
    }

    container.innerHTML = `<div class="list-toolbar">
        <input id="template-search" class="input-text" type="search"
            value="${escapeHtml(state.templateSearch)}" placeholder="搜索名称、说明或内容">
        <span class="list-count">${filtered.length} / ${templates.length}</span>
        <button id="btn-delete-all-templates" class="btn btn-danger btn-sm" type="button">🗑 删除全部</button>
    </div><div id="template-list-results"></div>`;
    const results = $('#template-list-results', container);
    results.innerHTML = filtered.length ? filtered.map(tpl => {
        const active = tpl.is_active !== false;
        const isSample = tpl.is_sample;
        const preview = tpl.content ? tpl.content.replace(/\{\{.*?\}\}/g, '___').substring(0, 60) : '';
        const vars = tpl.variables ? (typeof tpl.variables === 'string' ? JSON.parse(tpl.variables) : tpl.variables).join(', ') : '';
        const updatedAt = tpl.updated_at ? new Date(tpl.updated_at).toLocaleString('zh-CN') : '';
        return `<div class="template-list-item ${active ? 'active' : ''} ${isSample ? 'is-sample' : ''}" data-id="${tpl.id}">
            <span class="item-status"></span>
            <div class="item-info">
                <div class="item-name">${escapeHtml(tpl.name)} <span style="font-size:11px;color:var(--text-muted)">v${tpl.version}</span>${isSample ? ' <span class="sample-badge">示例</span>' : ''}</div>
                <div class="item-meta">${isSample ? '✏️ 示例模板' : vars ? '📌 ' + escapeHtml(vars) : '无变量'} · ${updatedAt}</div>
            </div>
            <div class="item-preview">${escapeHtml(preview)}</div>
        </div>`;
    }).join('') : '<div class="empty-state">没有匹配的模板</div>';
    $('#template-search').addEventListener('input', event => {
        state.templateSearch = event.target.value;
        renderTemplateList(state.templates);
        const search = $('#template-search');
        search.focus();
        search.setSelectionRange(search.value.length, search.value.length);
    });
    safeBind('#btn-delete-all-templates', 'click', deleteAllTemplates);

    // 绑定点击事件
    $$('.template-list-item', results).forEach(item => {
        item.addEventListener('click', () => {
            const id = parseInt(item.dataset.id);
            openTemplateEditor(id);
        });
    });
}

// ==================== 分类筛选 / 新建 / 导入导出 ====================

$$('#category-list .category-item').forEach(item => {
    item.addEventListener('click', () => {
        $$('#category-list .category-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        currentTemplateCategory = item.dataset.category;
        loadTemplatesList();
    });
});

safeBind('#btn-new-template', 'click', () => {
    openTemplateEditor(null);
});

safeBind('#btn-export-templates', 'click', async () => {
    try {
        const response = await fetch('/api/templates/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ format: 'json' }),
        });

        if (!response.ok) {
            const error = await response.json().catch(() => null);
            throw new Error(error?.error || `HTTP ${response.status}`);
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'forestar_templates_export.json';
        a.click();
        URL.revokeObjectURL(url);
        toast('模板已导出');
    } catch (e) {
        toast('导出失败: ' + e.message, 'error');
    }
});

const importFileInput = $('#import-file-input');
safeBind('#btn-import-templates', 'click', () => {
    if (importFileInput) importFileInput.click();
});
if (importFileInput) {
    importFileInput.addEventListener('change', async () => {
        const file = importFileInput.files[0];
        if (!file) return;

        try {
            const formData = new FormData();
            formData.append('file', file);
            const response = await fetch('/api/templates/import', {
                method: 'POST',
                body: formData,
            });
            const result = await response.json();
            if (result.success) {
                toast(`导入成功：${result.imported} 个模板，跳过 ${result.skipped} 个重复`);
                loadTemplatesList();
            } else {
                toast('导入失败: ' + result.error, 'error');
            }
        } catch (e) {
            toast('导入失败: ' + e.message, 'error');
        }

        importFileInput.value = '';
    });
}

// ==================== 模板编辑器 ====================

safeBind('#btn-close-editor', 'click', closeTemplateEditor);

/** 关闭模板编辑器（含版本历史与风格卡面板） */
function closeTemplateEditor() {
    $('#template-editor-panel').style.display = 'none';
    $('#version-history-panel').style.display = 'none';
    $('#style-card-panel').style.display = 'none';
    document.body.classList.remove('template-editor-open');
    state.editingTemplateId = null;
    state.currentStyleCard = null;
}

/** 根据分类切换风格卡入口的可见性 */
export function updateStyleCardVisibility() {
    const isExample = $('#edit-template-category').value === 'example';
    $('#btn-open-style-card').style.display = isExample ? '' : 'none';
    if (!isExample) $('#style-card-panel').style.display = 'none';
}

/** 渲染模板内容编辑器的 Markdown 预览 */
function renderMarkdownPreview() {
    const source = $('#edit-template-content').value;
    const preview = $('#markdown-preview');
    if (!source.trim()) {
        preview.innerHTML = '<div class="markdown-preview-empty">Markdown 预览会显示在这里</div>';
        return;
    }

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
    preview.innerHTML = html.join('');
}

safeBind('#edit-template-content', 'input', renderMarkdownPreview);
$$('.markdown-toolbar button[data-md-prefix], .markdown-toolbar button[data-md-wrap]').forEach(button => {
    button.addEventListener('click', () => {
        const editor = $('#edit-template-content');
        const start = editor.selectionStart;
        const end = editor.selectionEnd;
        const selected = editor.value.slice(start, end);
        if (button.dataset.mdWrap) {
            const mark = button.dataset.mdWrap;
            editor.setRangeText(`${mark}${selected || '文字'}${mark}`, start, end, 'select');
        } else {
            const prefix = button.dataset.mdPrefix;
            const lineStart = editor.value.lastIndexOf('\n', start - 1) + 1;
            editor.setRangeText(prefix, lineStart, lineStart, 'end');
        }
        editor.focus();
        editor.dispatchEvent(new Event('input', { bubbles: true }));
    });
});
safeBind('#btn-toggle-markdown-preview', 'click', event => {
    const panel = $('#template-editor-panel');
    const visible = !panel.classList.toggle('preview-hidden');
    event.currentTarget.classList.toggle('active', visible);
    event.currentTarget.textContent = visible ? '隐藏预览' : '显示预览';
});

// ==================== 示例模板 ====================

/** 加载示例模板列表（带缓存） */
async function loadSampleTemplates() {
    if (state.sampleTemplates.length > 0) return;
    try {
        const data = await api('/api/templates/samples');
        state.sampleTemplates = data.data;
    } catch (e) {
        console.error('加载示例模板失败:', e);
        state.sampleTemplates = [];
    }
}

/** 重置编辑器为普通模板编辑状态 */
function resetEditorUi() {
    const content = $('#edit-template-content');
    content.readOnly = false;
    content.disabled = false;

    $('#sample-template-tabs').style.display = 'none';
    $('#sample-template-tabs').innerHTML = '';
    $('#sample-variables-panel').style.display = 'none';
    $('#sample-variables-list').innerHTML = '';

    $('#btn-save-as-template').style.display = 'none';
    $('#btn-delete-sample').style.display = 'none';
    $('#btn-save-template').style.display = '';
    $('#btn-delete-template').style.display = '';
    $('#btn-version-history').style.display = '';
    $('#btn-open-style-card').style.display = '';
    $('#edit-template-is-sample-label').style.display = '';
    $('#edit-template-is-sample').checked = false;

    $('.markdown-toolbar').classList.remove('sample-mode');
}

/** 进入示例模板编辑模式（只读 + 变量填写 + 另存为） */
function enterSampleMode(tpl) {
    resetEditorUi();

    state.editingTemplateId = tpl.id;
    $('#editor-title').textContent = `示例模板 - ${tpl.name} (v${tpl.version})`;
    $('#edit-template-id').value = tpl.id;
    $('#edit-template-name').value = '';
    $('#edit-template-name').placeholder = '填写新模板名称';
    $('#edit-template-category').value = tpl.category;
    $('#edit-template-desc').value = tpl.description || '';

    const content = $('#edit-template-content');
    content.value = tpl.content;
    content.readOnly = true;
    renderMarkdownPreview();

    // 示例模式下隐藏保存/删除/版本/示例开关/风格卡，显示另存为与删除示例
    $('#btn-save-template').style.display = 'none';
    $('#btn-delete-template').style.display = 'none';
    $('#btn-version-history').style.display = 'none';
    $('#btn-open-style-card').style.display = 'none';
    $('#edit-template-is-sample-label').style.display = 'none';
    $('#btn-save-as-template').style.display = '';
    $('#btn-delete-sample').style.display = '';

    // 隐藏 Markdown 工具栏的格式按钮，仅保留预览切换
    $('.markdown-toolbar').classList.add('sample-mode');

    // 渲染示例模板 tab 栏
    const tabs = $('#sample-template-tabs');
    tabs.style.display = '';
    tabs.innerHTML = state.sampleTemplates.map(sample => {
        const active = sample.id === tpl.id;
        const cfg = categoryConfig[sample.category] || { icon: '📄' };
        return `<button type="button" class="variables-template-tab ${active ? 'active' : ''}" data-id="${sample.id}">
            ${cfg.icon} ${escapeHtml(sample.name)}
        </button>`;
    }).join('');
    $$('.variables-template-tab', tabs).forEach(tab => {
        tab.addEventListener('click', () => {
            const id = parseInt(tab.dataset.id);
            const sample = state.sampleTemplates.find(s => s.id === id);
            if (sample) enterSampleMode(sample);
        });
    });

    // 渲染变量大文本框
    const list = $('#sample-variables-list');
    const vars = tpl.variables ? (typeof tpl.variables === 'string' ? JSON.parse(tpl.variables) : tpl.variables) : [];
    list.innerHTML = vars.length ? vars.map(v => `
        <label class="sample-variable-item">
            <span>${escapeHtml(v)}</span>
            <textarea class="input-textarea" data-var="${escapeHtml(v)}" rows="4" placeholder="填写 ${escapeHtml(v)}"></textarea>
        </label>
    `).join('') : '<div class="variables-empty">该示例模板没有变量</div>';
    $('#sample-variables-panel').style.display = '';
}

/** 打开模板编辑器：null 新建、示例模板进入示例模式、普通模板编辑 */
export async function openTemplateEditor(templateId) {
    const panel = $('#template-editor-panel');
    panel.style.display = '';
    document.body.classList.add('template-editor-open');
    $('#version-history-panel').style.display = 'none';
    $('#style-card-panel').style.display = 'none';

    if (templateId === null) {
        // 新建普通模板
        resetEditorUi();
        $('#editor-title').textContent = '新建模板';
        $('#edit-template-id').value = '';
        $('#edit-template-name').value = '';
        $('#edit-template-name').placeholder = '无标题模板';
        $('#edit-template-category').value = currentTemplateCategory === 'all' ? 'constraint' : currentTemplateCategory;
        $('#edit-template-desc').value = '';
        $('#edit-template-content').value = '';
        renderMarkdownPreview();
        state.editingTemplateId = null;
        updateStyleCardVisibility();
        return;
    }

    try {
        const data = await api(`/api/templates/${templateId}`);
        const tpl = data.data;

        if (tpl.is_sample) {
            await loadSampleTemplates();
            enterSampleMode(tpl);
        } else {
            resetEditorUi();
            $('#editor-title').textContent = `编辑模板 - ${tpl.name} (v${tpl.version})`;
            $('#edit-template-id').value = tpl.id;
            $('#edit-template-name').value = tpl.name;
            $('#edit-template-name').placeholder = '无标题模板';
            $('#edit-template-category').value = tpl.category;
            $('#edit-template-desc').value = tpl.description || '';
            $('#edit-template-content').value = tpl.content;
            $('#edit-template-is-sample').checked = Boolean(tpl.is_sample);
            renderMarkdownPreview();
            state.editingTemplateId = tpl.id;
            updateStyleCardVisibility();
        }
    } catch (e) {
        toast('加载模板失败: ' + e.message, 'error');
        closeTemplateEditor();
    }
}

// ==================== 保存 / 另存 / 删除 / 版本历史 ====================

safeBind('#edit-template-category', 'change', updateStyleCardVisibility);

safeBind('#btn-save-template', 'click', async () => {
    const id = $('#edit-template-id').value;
    const data = {
        name: $('#edit-template-name').value,
        category: $('#edit-template-category').value,
        content: $('#edit-template-content').value,
        description: $('#edit-template-desc').value,
        is_sample: $('#edit-template-is-sample').checked,
    };

    if (!data.name.trim()) { toast('请输入模板名称', 'warning'); return; }
    if (!data.content.trim()) { toast('请输入模板内容', 'warning'); return; }

    try {
        let result;
        if (id) {
            result = await api(`/api/templates/${id}`, {
                method: 'PUT',
                body: JSON.stringify(data),
            });
            if (result.is_new_version) {
                toast('内容变更，已创建新版本 v' + result.data.version);
            } else {
                toast('模板已更新');
            }
        } else {
            result = await api('/api/templates', {
                method: 'POST',
                body: JSON.stringify(data),
            });
            toast('模板已创建');
        }

        $('#edit-template-id').value = result.data.id;
        state.editingTemplateId = result.data.id;
        $('#editor-title').textContent = `编辑模板 - ${result.data.name} (v${result.data.version})`;
        updateStyleCardVisibility();
        if ($('#style-card-panel').style.display !== 'none') await loadStyleProfile();

        loadTemplatesList();
    } catch (e) {
        toast('保存失败: ' + e.message, 'error');
    }
});

// 示例模板另存为新模板
safeBind('#btn-save-as-template', 'click', async () => {
    const sampleId = $('#edit-template-id').value;
    const name = $('#edit-template-name').value.trim();
    const category = $('#edit-template-category').value;
    const description = $('#edit-template-desc').value;

    if (!sampleId) { toast('请先选择一个示例模板', 'warning'); return; }
    if (!name) { toast('请输入新模板名称', 'warning'); $('#edit-template-name').focus(); return; }

    const variableValues = {};
    $$('#sample-variables-list textarea[data-var]').forEach(textarea => {
        variableValues[textarea.dataset.var] = textarea.value;
    });

    try {
        await api('/api/templates/from-sample', {
            method: 'POST',
            body: JSON.stringify({
                sample_id: parseInt(sampleId),
                name,
                category,
                description,
                variable_values: variableValues,
            }),
        });
        toast('新模板已创建');
        closeTemplateEditor();
        loadTemplatesList();
    } catch (e) {
        toast('保存失败: ' + e.message, 'error');
    }
});

// 删除示例模板
safeBind('#btn-delete-sample', 'click', async () => {
    const sampleId = $('#edit-template-id').value;
    if (!sampleId) { toast('请先选择示例模板', 'warning'); return; }
    if (!confirm('确定删除这个示例模板吗？删除后不可恢复。')) return;
    try {
        await api(`/api/templates/${sampleId}`, { method: 'DELETE' });
        // 同步内存缓存，避免刷新前列表仍显示已删除的示例
        state.sampleTemplates = state.sampleTemplates.filter(t => String(t.id) !== String(sampleId));
        toast('示例模板已删除');
        closeTemplateEditor();
        loadTemplatesList();
    } catch (e) {
        toast('删除失败: ' + e.message, 'error');
    }
});

// 删除模板
safeBind('#btn-delete-template', 'click', async () => {
    const id = $('#edit-template-id').value;
    if (!id) { toast('请先保存模板', 'warning'); return; }
    if (!confirm('确定要删除这个模板吗？此操作不可撤销。')) return;

    try {
        await api(`/api/templates/${id}`, { method: 'DELETE' });
        toast('模板已删除');
        closeTemplateEditor();
        loadTemplatesList();
    } catch (e) {
        toast('删除失败: ' + e.message, 'error');
    }
});

/** 删除所有模板并刷新列表与工作台 */
async function deleteAllTemplates() {
    if (!confirm('确定要删除所有模板吗？此操作不可撤销。')) return;
    try {
        await api('/api/templates/all', { method: 'DELETE' });
        toast('所有模板已删除');
        closeTemplateEditor();
        loadTemplatesList();
        loadWorkspaceTemplates();
    } catch (e) {
        toast('删除失败: ' + e.message, 'error');
    }
}

// 版本历史
safeBind('#btn-version-history', 'click', async () => {
    const id = $('#edit-template-id').value;
    if (!id) { toast('请先保存模板', 'warning'); return; }

    const panel = $('#version-history-panel');
    // 已打开则收起
    if (panel.style.display !== 'none') {
        panel.style.display = 'none';
        return;
    }

    try {
        const data = await api(`/api/templates/${id}/versions`);
        panel.style.display = '';

        const list = $('#version-list');
        list.innerHTML = data.data.map(v => `
            <div class="template-list-item version-history-item ${v.is_active ? 'active' : ''}" style="cursor:default;">
                <span class="item-status"></span>
                <div class="version-item-main">
                    <div class="version-item-info">
                        <div class="item-name">
                            v${v.version}
                            ${v.is_active ? '<span style="color:var(--accent-success);font-size:11px;"> ● 当前</span>' : ''}
                        </div>
                        <div class="item-meta">${new Date(v.updated_at).toLocaleString('zh-CN')}</div>
                    </div>
                    ${!v.is_active ? `<button class="btn btn-xs btn-outline restore-version-btn" data-vid="${v.id}">恢复</button>` : ''}
                </div>
            </div>
        `).join('');

        // 绑定恢复按钮
        $$('.restore-version-btn', list).forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const vid = btn.dataset.vid;
                try {
                    await api(`/api/templates/${id}/restore/${vid}`, { method: 'POST' });
                    toast('已恢复到该版本');
                    openTemplateEditor(id);
                } catch (err) {
                    toast('恢复失败: ' + err.message, 'error');
                }
            });
        });
    } catch (e) {
        toast('加载版本历史失败: ' + e.message, 'error');
    }
});
