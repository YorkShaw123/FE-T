/**
 * Forestar Editor - 生成记录（历史）
 * 负责生成记录列表、搜索、置顶、删除、详情查看与修改版 diff 展示。
 */
import { $, $$, api, toast, escapeHtml, safeBind, formatArticle } from './utils.js';
import { state } from './state.js';

const HISTORY_PAGE_SIZE = 50;
let currentHistoryPage = 1;

/** 加载生成记录列表并渲染 */
export async function loadHistoryList(page = currentHistoryPage) {
    try {
        const data = await api(`/api/generation/records?page=${page}&per_page=${HISTORY_PAGE_SIZE}`);
        const records = data.data.items;
        currentHistoryPage = data.data.current_page || 1;
        state.historyRecords = records;

        const container = $('#history-list');

        if (records.length === 0) {
            container.innerHTML = `<p style="text-align:center;padding:40px;color:var(--text-muted);">暂无生成记录</p>`;
            return;
        }

        container.innerHTML = `<div class="list-toolbar history-toolbar">
            <input id="history-search" class="input-text" type="search"
                placeholder="搜索标题、模型或正文摘要">
            <button id="btn-delete-all-records" class="btn btn-danger btn-sm" type="button">🗑 删除全部</button>
        </div><div id="history-list-results"></div><div id="history-pagination" class="history-pagination"></div>`;
        renderHistoryRecords(records);
        renderHistoryPagination(data.data);
        $('#history-search').addEventListener('input', event => {
            const query = event.target.value.trim().toLowerCase();
            renderHistoryRecords(state.historyRecords.filter(r =>
                [r.title, r.model_used, r.content_preview].some(value =>
                    String(value || '').toLowerCase().includes(query)
                )
            ));
        });
        safeBind('#btn-delete-all-records', 'click', deleteAllRecords);
    } catch (e) {
        console.error('加载历史记录失败:', e);
    }
}

function renderHistoryPagination(pagination) {
    const container = $('#history-pagination');
    if (!container) return;
    const pages = pagination.pages || 1;
    const page = pagination.current_page || 1;
    container.innerHTML = `<button class="btn btn-outline btn-sm" type="button" data-page="${page - 1}" ${page <= 1 ? 'disabled' : ''}>上一页</button>
        <span>第 ${page} / ${pages} 页 · 共 ${pagination.total || 0} 条</span>
        <button class="btn btn-outline btn-sm" type="button" data-page="${page + 1}" ${page >= pages ? 'disabled' : ''}>下一页</button>`;
    $$('button[data-page]', container).forEach(button => {
        button.addEventListener('click', () => loadHistoryList(Number(button.dataset.page)));
    });
}

/** 渲染生成记录列表 */
function renderHistoryRecords(records) {
    const container = $('#history-list-results');
    if (!container) return;
    if (!records.length) {
        container.innerHTML = '<div class="empty-state">没有匹配的生成记录</div>';
        return;
    }
    container.innerHTML = records.map(r => `
            <div class="history-item ${r.pinned ? 'pinned' : ''}" data-id="${r.id}">
                <div class="h-main">
                    <div class="h-title">${escapeHtml(r.title)}</div>
                    <div class="h-preview">${escapeHtml(r.content_preview || '')}</div>
                    <div class="h-meta">
                        <span>${escapeHtml(r.model_used || '未知模型')}</span>
                        ${r.has_deai ? '<span style="color:var(--accent-success)">已去AI味</span>' : ''}
                        ${r.has_edited ? '<span class="history-edited-badge">有修改版</span>' : ''}
                        <span>${new Date(r.created_at).toLocaleString('zh-CN')}</span>
                    </div>
                </div>
                <div class="history-actions">
                    <button type="button" class="btn-pin ${r.pinned ? 'active' : ''}" data-action="pin" title="${r.pinned ? '取消置顶' : '置顶'}">
                        ${r.pinned ? '取消置顶' : '置顶'}
                    </button>
                    <button type="button" class="danger" data-action="delete" title="删除">删除</button>
                </div>
            </div>
        `).join('');

    $$('.history-item', container).forEach(item => {
        item.addEventListener('click', (e) => {
            if (e.target.closest('.history-actions, [data-action]')) return;
            const id = parseInt(item.dataset.id);
            loadHistoryDetail(id);
            $$('.history-item', container).forEach(i => i.classList.remove('active'));
            item.classList.add('active');
        });
    });

    $$('.history-item .btn-pin', container).forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const id = parseInt(btn.closest('.history-item').dataset.id);
            toggleRecordPinned(id);
        });
    });

    $$('.history-item .history-actions .danger', container).forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const id = parseInt(btn.closest('.history-item').dataset.id);
            deleteRecord(id);
        });
    });
}

/** 置顶/取消置顶生成记录 */
async function toggleRecordPinned(recordId) {
    const record = state.historyRecords.find(r => r.id === recordId);
    if (!record) return;
    try {
        await api(`/api/generation/records/${recordId}`, {
            method: 'PUT',
            body: JSON.stringify({ pinned: !record.pinned }),
        });
        toast(record.pinned ? '已取消置顶' : '已置顶');
        loadHistoryList(currentHistoryPage);
    } catch (e) {
        toast('置顶失败: ' + e.message, 'error');
    }
}

/** 删除单条生成记录 */
async function deleteRecord(recordId) {
    if (!confirm('确定要删除这条生成记录吗？此操作不可撤销。')) return;
    try {
        await api(`/api/generation/records/${recordId}`, { method: 'DELETE' });
        toast('记录已删除');
        if (state.currentRecordId === recordId) {
            $('#history-detail').style.display = 'none';
            state.currentRecordId = null;
        }
        loadHistoryList(currentHistoryPage);
    } catch (e) {
        toast('删除失败: ' + e.message, 'error');
    }
}

/** 删除所有生成记录 */
async function deleteAllRecords() {
    if (!confirm('确定要删除所有生成记录吗？此操作不可撤销。')) return;
    try {
        await api('/api/generation/records', { method: 'DELETE' });
        toast('所有记录已删除');
        $('#history-detail').style.display = 'none';
        state.currentRecordId = null;
        loadHistoryList(1);
    } catch (e) {
        toast('删除失败: ' + e.message, 'error');
    }
}

/** 渲染原文与修改版的逐行 diff */
function renderEditedHistoryDiff(original, edited) {
    if (!edited) {
        return '<div class="empty-state">尚未保存修改版。请从工作台打开“全屏编辑”，修改并保存后再查看。</div>';
    }
    const originalLines = String(original || '').split('\n');
    const editedLines = String(edited).split('\n');
    const maxLength = Math.max(originalLines.length, editedLines.length);
    const rows = [];

    for (let index = 0; index < maxLength; index++) {
        const before = originalLines[index];
        const after = editedLines[index];
        if (before === after) {
            rows.push(before ? `<p>${escapeHtml(before)}</p>` : '<br>');
            continue;
        }
        if (before !== undefined && before !== '') {
            rows.push(`<p class="history-diff-removed"><span class="history-diff-mark">原</span>${escapeHtml(before)}</p>`);
        }
        if (after !== undefined && after !== '') {
            rows.push(`<p class="history-diff-added"><span class="history-diff-mark">改</span>${escapeHtml(after)}</p>`);
        }
    }

    return `<div class="history-diff-legend">
        <span><i class="legend-swatch removed"></i>原文删除或替换</span>
        <span><i class="legend-swatch added"></i>修改版新增内容</span>
    </div><div class="history-diff-content">${rows.join('')}</div>`;
}

/** 加载生成记录详情 */
async function loadHistoryDetail(recordId) {
    try {
        const data = await api(`/api/generation/records/${recordId}`);
        const record = data.data;

        const detail = $('#history-detail');
        detail.style.display = '';

        $('#history-detail-title').textContent = record.title;
        $('#history-detail-meta').innerHTML = `
            模型: ${escapeHtml(record.model_used || '未知')} |
            ${record.thinking_enabled ? '思考模式: 启用 | ' : ''}
            时间: ${new Date(record.created_at).toLocaleString('zh-CN')}
            ${record.rating ? ` | 评分: ${'⭐'.repeat(record.rating)}` : ''}
        `;

        $('#history-detail-content').innerHTML = formatArticle(record.deai_content || record.content);

        // 详情标签切换
        $$('.detail-tab', detail).forEach(tab => {
            tab.classList.remove('active');
            if (tab.dataset.content === 'final') tab.classList.add('active');

            tab.addEventListener('click', () => {
                $$('.detail-tab', detail).forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                switch (tab.dataset.content) {
                    case 'final':
                        $('#history-detail-content').innerHTML = formatArticle(record.deai_content || record.content);
                        break;
                    case 'edited':
                        $('#history-detail-content').innerHTML = renderEditedHistoryDiff(
                            record.deai_content || record.content,
                            record.edited_content
                        );
                        break;
                    case 'original':
                        $('#history-detail-content').innerHTML = formatArticle(record.content);
                        break;
                    case 'prompt':
                        $('#history-detail-content').innerHTML = formatArticle(record.assembled_prompt || '无提示词记录');
                        break;
                }
            });
        });

        state.currentRecordId = recordId;
    } catch (e) {
        console.error('加载详情失败:', e);
    }
}

safeBind('#btn-close-history-detail', 'click', () => {
    $('#history-detail').style.display = 'none';
});
