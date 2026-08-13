/**
 * Forestar Editor - 工作台模板面板
 * 负责工作台左侧模板分类面板的加载、渲染、启停切换，以及前置文章文件导入。
 */
import { $, $$, api, toast, escapeHtml, safeBind } from './utils.js';
import { state, categoryConfig } from './state.js';

const VARIABLE_VALUES_KEY = 'forestar_workspace_variable_values_v1';

function loadStoredVariableValues() {
    try {
        const value = JSON.parse(localStorage.getItem(VARIABLE_VALUES_KEY) || '{}');
        return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch {
        return {};
    }
}

/** 收集工作台变量值，供提示词预览和正式生成共用。 */
export function getWorkspaceVariableValues() {
    const values = loadStoredVariableValues();
    $$('#workspace-variables-list [data-variable]').forEach(input => {
        values[input.dataset.variable] = input.value;
    });
    return values;
}

function renderWorkspaceVariables(grouped) {
    const section = $('#workspace-variables-section');
    const list = $('#workspace-variables-list');
    if (!section || !list) return;
    const variables = [];
    const seen = new Set();
    Object.values(grouped).flat().forEach(template => {
        if (template.is_active === false) return;
        let names = template.variables || [];
        if (typeof names === 'string') {
            try { names = JSON.parse(names); } catch { names = []; }
        }
        (Array.isArray(names) ? names : []).forEach(name => {
            const normalized = String(name || '').trim();
            if (normalized && !seen.has(normalized)) {
                seen.add(normalized);
                variables.push(normalized);
            }
        });
    });
    section.hidden = variables.length === 0;
    if (!variables.length) {
        list.innerHTML = '';
        return;
    }
    const stored = loadStoredVariableValues();
    list.innerHTML = variables.map(name => `
        <label class="workspace-variable-item">
            <span>${escapeHtml(name)}</span>
            <textarea class="input-textarea" rows="2" data-variable="${escapeHtml(name)}"
                placeholder="填写 ${escapeHtml(name)}">${escapeHtml(stored[name] || '')}</textarea>
        </label>
    `).join('');
    $$('[data-variable]', list).forEach(input => {
        input.addEventListener('input', () => {
            const values = loadStoredVariableValues();
            values[input.dataset.variable] = input.value;
            localStorage.setItem(VARIABLE_VALUES_KEY, JSON.stringify(values));
        });
    });
}

/** 加载并渲染工作台模板分组 */
export async function loadWorkspaceTemplates() {
    const container = $('#template-panel-body');
    container.innerHTML = '<p style="padding:20px;text-align:center;color:var(--text-muted);">正在加载模板...</p>';

    try {
        // 默认加载全部模板（含非活跃），让用户看到所有模板并显式控制开关
        const data = await api('/api/templates/grouped?active_only=false');
        console.log('[Forestar] 加载模板完成，各组数量:',
            Object.fromEntries(Object.entries(data.data).map(([k, v]) => [k, v.length])));
        state.groupedTemplates = data.data;
        renderWorkspaceTemplates(data.data);
        renderWorkspaceVariables(data.data);
    } catch (e) {
        console.error('[Forestar] 加载模板失败:', e);
        container.innerHTML = `<div style="padding:20px;text-align:center;">
            <p style="color:var(--accent-danger);margin-bottom:10px;">⚠️ 加载模板失败: ${escapeHtml(e.message)}</p>
            <button class="btn btn-outline btn-sm" onclick="location.reload()">重新加载</button>
        </div>`;
    }
}

/** 渲染工作台模板分组面板 */
function renderWorkspaceTemplates(grouped) {
    const container = $('#template-panel-body');
    let html = '';
    let totalCount = 0;

    for (const [catId, templates] of Object.entries(grouped)) {
        const visible = templates || [];
        if (visible.length === 0) continue;
        totalCount += visible.length;
        const cfg = categoryConfig[catId] || { name: catId };
        const activeCount = visible.filter(t => t.is_active !== false).length;

        html += `<div class="template-category-group">`;
        html += `<div class="category-group-header" data-cat="${catId}">
            <span class="collapse-icon">▼</span>
            <span>${cfg.name}</span>
            <span style="margin-left:auto;font-size:11px;color:var(--text-muted)">
                ${activeCount}/${visible.length} 启用
            </span>
        </div>`;
        html += `<div class="category-templates">`;

        visible.forEach(tpl => {
            const active = tpl.is_active !== false;
            const description = String(tpl.description || '').trim();
            const preview = description
                || (tpl.content || '').replace(/\{\{.*?\}\}/g, '___').substring(0, 40);

            html += `<div class="template-card ${active ? 'active' : ''}" data-id="${tpl.id}" data-cat="${catId}">
                <span class="toggle-dot" data-action="toggle" title="点击切换启用/禁用"></span>
                <span class="card-name">${escapeHtml(tpl.name)}</span>
                <span class="card-preview">${escapeHtml(preview)}</span>
            </div>`;
        });

        html += `</div></div>`;
    }

    if (totalCount === 0) {
        html = `<div style="padding:20px;text-align:center;color:var(--text-muted);">
            <p>暂无可用模板</p>
            <p style="font-size:12px;margin-top:8px;">请切换到“模板管理”标签页创建模板</p>
        </div>`;
    }

    container.innerHTML = html;

    // 绑定折叠事件
    $$('.category-group-header', container).forEach(header => {
        header.addEventListener('click', () => {
            const content = header.nextElementSibling;
            content.classList.toggle('collapsed');
            header.classList.toggle('collapsed');
        });
    });

    // 仅对 toggle-dot 绑定切换事件，不绑定整个卡片
    $$('.toggle-dot', container).forEach(dot => {
        dot.addEventListener('click', async (e) => {
            e.stopPropagation();
            const card = dot.closest('.template-card');
            await toggleTemplateActive(card);
        });
    });
}

/** 切换模板启用/禁用状态并刷新面板 */
async function toggleTemplateActive(card) {
    const id = parseInt(card.dataset.id);
    try {
        const result = await api(`/api/templates/${id}/toggle`, { method: 'POST' });
        const tpl = result.data;
        // 更新状态
        const catTemplates = state.groupedTemplates[tpl.category];
        if (catTemplates) {
            const idx = catTemplates.findIndex(t => t.id === tpl.id);
            if (idx !== -1) {
                catTemplates[idx] = tpl;
            }
        }
        // 重新渲染面板以更新开关状态和计数
        renderWorkspaceTemplates(state.groupedTemplates);
        renderWorkspaceVariables(state.groupedTemplates);
    } catch (e) {
        toast('切换失败: ' + e.message, 'error');
    }
}

// 刷新模板按钮
safeBind('#btn-refresh-templates', 'click', () => {
    loadWorkspaceTemplates();
});

// ==================== 前置文章文件导入 ====================

/** 导入前置文章文本文件（TXT/DOC/DOCX） */
export async function importArticleFile(file) {
    if (!file) return;
    const extension = '.' + (file.name.split('.').pop() || '').toLowerCase();
    if (!['.txt', '.doc', '.docx'].includes(extension)) {
        toast('请选择 .txt、.doc 或 .docx 文本文件', 'warning');
        return;
    }
    if (file.size > 10 * 1024 * 1024) {
        toast('文件不能超过 10 MB', 'warning');
        return;
    }

    const status = $('#article-file-status');
    status.hidden = false;
    status.className = 'file-status loading';
    status.textContent = `正在读取 ${file.name}…`;
    try {
        const form = new FormData();
        form.append('file', file);
        const response = await fetch('/api/generation/extract-text', { method: 'POST', body: form });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || '文件读取失败');
        $('#previous-article').value = data.data.text;
        $('#previous-article').dispatchEvent(new Event('input', { bubbles: true }));
        status.className = 'file-status success';
        status.textContent = `✓ 已导入 ${file.name}（${data.data.char_count.toLocaleString()} 字）`;
        toast('前置文章已导入', 'success');
    } catch (error) {
        status.className = 'file-status error';
        status.textContent = `导入失败：${error.message}`;
        toast('文件导入失败: ' + error.message, 'error');
    }
}

safeBind('#btn-browse-article', 'click', event => {
    event.stopPropagation();
    $('#article-file-input').click();
});
safeBind('#article-file-input', 'change', event => {
    importArticleFile(event.target.files[0]);
    event.target.value = '';
});
const articleDropZone = $('#article-drop-zone');
if (articleDropZone) {
    articleDropZone.addEventListener('click', event => {
        if (!event.target.closest('#btn-browse-article')) $('#article-file-input').click();
    });
    articleDropZone.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') $('#article-file-input').click();
    });
    ['dragenter', 'dragover'].forEach(type => articleDropZone.addEventListener(type, event => {
        event.preventDefault();
        articleDropZone.classList.add('dragging');
    }));
    ['dragleave', 'drop'].forEach(type => articleDropZone.addEventListener(type, event => {
        event.preventDefault();
        articleDropZone.classList.remove('dragging');
    }));
    articleDropZone.addEventListener('drop', event => importArticleFile(event.dataTransfer.files[0]));
}
