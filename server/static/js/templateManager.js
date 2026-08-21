/**
 * Flora Editor - 模板管理
 * 负责模板列表、分类筛选、新建/编辑/删除/导入导出与版本历史。
 */
import { $, $$, api, toast, escapeHtml, safeBind } from './utils.js';
import { state } from './state.js';
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

/** 渲染模板列表（含搜索过滤与示例/删除按钮） */
function renderTemplateList(templates) {
    const container = $('#template-list');
    const query = state.templateSearch.trim().toLowerCase();
    const filtered = query ? templates.filter(tpl =>
        [tpl.name, tpl.description, tpl.content].some(value =>
            String(value || '').toLowerCase().includes(query)
        )
    ) : templates;

    container.innerHTML = `<div class="list-toolbar">
        <input id="template-search" class="input-text" type="search"
            value="${escapeHtml(state.templateSearch)}" placeholder="搜索名称、说明或内容">
        <span class="list-count">${filtered.length} / ${templates.length}</span>
        <button id="btn-create-starter-templates" class="btn btn-outline btn-sm" type="button">生成示例模板</button>
        <button id="btn-delete-all-templates" class="btn btn-danger btn-sm" type="button">🗑 删除全部</button>
    </div><div id="template-list-results"></div>`;
    const results = $('#template-list-results', container);
    results.innerHTML = filtered.length ? filtered.map(tpl => {
        const active = tpl.is_active !== false;
        const description = String(tpl.description || '').trim();
        const preview = description || (tpl.content ? tpl.content.substring(0, 60) : '');
        const updatedAt = tpl.updated_at ? new Date(tpl.updated_at).toLocaleString('zh-CN') : '';
        return `<div class="template-list-item ${active ? 'active' : ''}" data-id="${tpl.id}">
            <span class="item-status"></span>
            <div class="item-info">
                <div class="item-name">${escapeHtml(tpl.name)} <span style="font-size:11px;color:var(--text-muted)">v${tpl.version}</span></div>
                <div class="item-meta">更新于 ${updatedAt || '未知时间'}</div>
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
    safeBind('#btn-create-starter-templates', 'click', createStarterTemplates);
    safeBind('#btn-delete-all-templates', 'click', deleteAllTemplates);

    // 绑定点击事件
    $$('.template-list-item', results).forEach(item => {
        item.addEventListener('click', () => {
            const id = parseInt(item.dataset.id);
            openTemplateEditor(id);
        });
    });
}

/** 按用户请求补齐内置示例模板。 */
async function createStarterTemplates() {
    try {
        const data = await api('/api/templates/starter', { method: 'POST' });
        toast(data.created > 0 ? `已生成 ${data.created} 个示例模板` : '示例模板已存在');
        await loadTemplatesList();
        await loadWorkspaceTemplates();
    } catch (e) {
        toast('生成示例模板失败: ' + e.message, 'error');
    }
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
        a.download = 'flora_templates_export.json';
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
safeBind('#btn-open-community-prompts', 'click', async () => {
    try {
        await api('/api/system/open-community-prompts', { method: 'POST' });
    } catch (error) {
        toast('无法打开社区提示词：' + error.message, 'error');
    }
});

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
/** 打开模板编辑器：null 新建，否则编辑已有模板。 */
export async function openTemplateEditor(templateId) {
    const panel = $('#template-editor-panel');
    panel.style.display = '';
    document.body.classList.add('template-editor-open');
    $('#version-history-panel').style.display = 'none';
    $('#style-card-panel').style.display = 'none';

    if (templateId === null) {
        // 新建模板
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

        $('#editor-title').textContent = `编辑模板 - ${tpl.name} (v${tpl.version})`;
        $('#edit-template-id').value = tpl.id;
        $('#edit-template-name').value = tpl.name;
        $('#edit-template-name').placeholder = '无标题模板';
        $('#edit-template-category').value = tpl.category;
        $('#edit-template-desc').value = tpl.description || '';
        $('#edit-template-content').value = tpl.content;
        renderMarkdownPreview();
        state.editingTemplateId = tpl.id;
        updateStyleCardVisibility();
    } catch (e) {
        toast('加载模板失败: ' + e.message, 'error');
        closeTemplateEditor();
    }
}

// ==================== 保存 / 删除 / 版本历史 ====================

safeBind('#edit-template-category', 'change', updateStyleCardVisibility);

safeBind('#btn-save-template', 'click', async () => {
    const id = $('#edit-template-id').value;
    const data = {
        name: $('#edit-template-name').value,
        category: $('#edit-template-category').value,
        content: $('#edit-template-content').value,
        description: $('#edit-template-desc').value,
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
