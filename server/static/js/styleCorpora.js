/**
 * Forestar Editor - 风格语料库管理（Style RAG）
 * 负责语料库 CRUD、文本导入、向量化索引、检索测试，以及生成请求的语料选择。
 */
import { $, $$, api, toast, escapeHtml, safeBind } from './utils.js';
import { loadStyleProfile } from './styleCard.js';

// ==================== 状态与工具 ====================

const STATUS_LABELS = {
    empty: '未导入',
    imported: '待向量化',
    indexed: '已向量化',
};
const SCENE_LABELS = {
    dialogue: '对话', action: '动作', psychology: '心理', environment: '环境',
    transition: '转场', narration: '叙述', mixed: '综合',
};
const PACE_LABELS = { fast: '紧凑', medium: '中等', slow: '舒缓' };

function statusBadge(status) {
    const label = STATUS_LABELS[status] || status;
    return `<span class="style-corpus-status style-corpus-status-${status}">${label}</span>`;
}

function corpusIndexKey(corpusId) {
    // 语料库多选状态持久化在 localStorage，避免切换页面丢失
    return `forestar_rag_corpora_${corpusId}`;
}

/** 读取本次参与检索的语料库 ID（勾选 + localStorage 记忆） */
export function getSelectedCorpusIds() {
    return $$('#style-rag-corpora-list input[type="checkbox"]:checked')
        .map(input => Number(input.value))
        .filter(Number.isFinite);
}

/** 读取 Embedding 密钥（用户未单独填写时返回空串，由后端/调用方决定回退） */
export function getEmbeddingApiKey() {
    return $('#style-rag-embedding-key')?.value.trim() || '';
}

// ==================== 渲染 ====================

/** 渲染工作台语料库多选区 */
function renderCorporaCheckboxes(corpora) {
    const list = $('#style-rag-corpora-list');
    const hint = $('#style-rag-empty-hint');
    if (!list) return;
    if (!corpora.length) {
        list.innerHTML = '';
        if (hint) hint.style.display = '';
        return;
    }
    if (hint) hint.style.display = 'none';
    list.innerHTML = corpora.map(corpus => {
        const checked = localStorage.getItem(corpusIndexKey(corpus.id)) === '1' ? ' checked' : '';
        const indexed = corpus.index_status === 'indexed';
        return `<label class="style-rag-corpus-item" title="${escapeHtml(corpus.description || corpus.name)}">
            <input type="checkbox" value="${corpus.id}"${checked}${indexed ? '' : ' disabled'}>
            <span><strong>${escapeHtml(corpus.name)}</strong>
                <small>${corpus.chunk_count} 片段${indexed ? ' · 已向量化' : ' · 需先向量化'}</small>
            </span>
        </label>`;
    }).join('');
}

/** 渲染语料库管理面板列表 */
function renderCorpusManager(corpora) {
    const list = $('#style-corpus-list');
    const section = $('#style-corpus-section');
    if (!list || !section) return;
    section.style.display = corpora.length ? '' : 'none';
    list.innerHTML = corpora.map(corpus => {
        const modelInfo = corpus.embedding_model
            ? ` · 模型 ${escapeHtml(corpus.embedding_model)}` : '';
        return `<div class="style-corpus-item" data-id="${corpus.id}">
            <div class="style-corpus-item-head">
                <div class="style-corpus-item-title">
                    <strong>${escapeHtml(corpus.name)}</strong>${statusBadge(corpus.index_status)}
                </div>
                <div class="style-corpus-item-actions">
                    <label class="btn btn-outline btn-sm">导入
                        <input type="file" accept=".txt,.doc,.docx" hidden data-action="import">
                    </label>
                    <button class="btn btn-outline btn-sm" type="button" data-action="index">向量化</button>
                    <button class="btn btn-outline btn-sm" type="button" data-action="clear">清空</button>
                    <button class="btn btn-outline btn-sm style-corpus-danger" type="button" data-action="delete">删除</button>
                </div>
            </div>
            <small class="style-corpus-item-meta">
                ${escapeHtml(corpus.description || '无描述')} · ${corpus.chunk_count} 片段 ·
                ${corpus.total_chars.toLocaleString()} 字${modelInfo}
            </small>
        </div>`;
    }).join('');
}

/** 加载语料库列表并刷新所有相关 UI */
export async function loadCorporaList() {
    try {
        const { data } = await api('/api/style-corpora');
        renderCorporaCheckboxes(data || []);
        renderCorpusManager(data || []);
        return data || [];
    } catch (e) {
        toast('加载语料库失败: ' + e.message, 'error');
        return [];
    }
}

// ==================== 打开面板 ====================

function openCorpusPanel() {
    const panel = $('#style-card-panel');
    const section = $('#style-corpus-section');
    if (panel) panel.style.display = 'grid';
    if (section) {
        section.style.display = '';
        section.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    loadCorporaList();
    // 同步刷新"分析对象"提示，避免用户不清楚风格说明书的分析对象
    loadStyleProfile();
}

// ==================== 操作 ====================

async function createCorpus() {
    const nameInput = $('#corpus-new-name');
    const name = (nameInput?.value || '').trim();
    if (!name) {
        toast('请输入语料库名称', 'warning');
        nameInput?.focus();
        return;
    }
    try {
        await api('/api/style-corpora', {
            method: 'POST',
            body: JSON.stringify({ name, description: '' }),
        });
        nameInput.value = '';
        toast('语料库已创建');
        loadCorporaList();
    } catch (e) {
        toast('创建失败: ' + e.message, 'error');
    }
}

async function importCorpusFile(corpusId, file) {
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) {
        toast('文件超过 20MB 上限，请拆分后导入', 'warning');
        return;
    }
    toast('正在导入并切片，请稍候…');
    try {
        const form = new FormData();
        form.append('file', file);
        const response = await fetch(`/api/style-corpora/${corpusId}/import`, {
            method: 'POST',
            body: form,
        });
        const result = await response.json().catch(() => null);
        if (!response.ok || !result?.success) throw new Error(result?.error || `HTTP ${response.status}`);
        const data = result.data;
        toast(`导入完成：${data.chunk_count} 个风格片段，共 ${data.total_chars.toLocaleString()} 字`);
        loadCorporaList();
    } catch (e) {
        toast('导入失败: ' + e.message, 'error');
    }
}

async function indexCorpus(corpusId) {
    const apiKey = getEmbeddingApiKey() || $('#api-key-input')?.value.trim() || '';
    if (!apiKey) {
        toast('请先填写 Embedding 密钥或顶部 LLM API 密钥', 'warning');
        return;
    }
    toast('正在向量化全部片段，请稍候…');
    try {
        const { data } = await api(`/api/style-corpora/${corpusId}/index`, {
            method: 'POST',
            body: JSON.stringify({ api_key: apiKey, provider: 'siliconflow' }),
        });
        toast(`向量化完成：${data.indexed_count} 个片段，可参与风格检索`);
        loadCorporaList();
    } catch (e) {
        toast('向量化失败: ' + e.message, 'error');
    }
}

async function clearCorpus(corpusId) {
    if (!confirm('确定清空该语料库的全部片段吗？')) return;
    try {
        await api(`/api/style-corpora/${corpusId}/clear`, { method: 'POST' });
        toast('已清空语料库');
        loadCorporaList();
    } catch (e) {
        toast('清空失败: ' + e.message, 'error');
    }
}

async function deleteCorpus(corpusId) {
    if (!confirm('确定删除该语料库吗？该操作不可恢复。')) return;
    try {
        await api(`/api/style-corpora/${corpusId}`, { method: 'DELETE' });
        localStorage.removeItem(corpusIndexKey(corpusId));
        toast('语料库已删除');
        loadCorporaList();
    } catch (e) {
        toast('删除失败: ' + e.message, 'error');
    }
}

// ==================== 检索测试 ====================

async function runSearchTest() {
    const query = $('#corpus-search-query')?.value.trim();
    if (!query) {
        toast('请输入用于检索测试的一句话', 'warning');
        return;
    }
    const resultBox = $('#corpus-search-result');
    const scene = $('#corpus-search-scene')?.value || '';
    const pacing = $('#corpus-search-pacing')?.value || '';
    const apiKey = getEmbeddingApiKey() || $('#api-key-input')?.value.trim() || '';
    if (resultBox) {
        resultBox.innerHTML = '<small class="style-corpus-search-loading">正在检索…</small>';
    }
    try {
        const { data } = await api('/api/style-corpora/search', {
            method: 'POST',
            body: JSON.stringify({
                query_text: query,
                scene_type: scene || null,
                pacing: pacing || null,
                top_k: 3,
                api_key: apiKey,
                provider: 'siliconflow',
            }),
        });
        renderSearchResult(resultBox, data);
    } catch (e) {
        if (resultBox) resultBox.innerHTML = '';
        toast('检索失败: ' + e.message, 'error');
    }
}

function renderSearchResult(box, data) {
    if (!box) return;
    const meta = data.meta || {};
    const items = data.items || [];
    const head = `<div class="style-corpus-search-head">
        <span>候选 ${meta.candidate_count ?? 0} · 向量 ${meta.vector_enabled ? '开' : '关'} · BM25 ${meta.bm25_enabled ? '开' : '关'}</span>
        <span>场景 ${SCENE_LABELS[meta.resolved_scene_type] || meta.resolved_scene_type || '自动'} · 节奏 ${PACE_LABELS[meta.resolved_pacing] || meta.resolved_pacing || '自动'}</span>
    </div>`;
    if (!items.length) {
        box.innerHTML = head + '<small class="style-corpus-search-empty">未命中片段，请调整过滤条件或扩大语料库</small>';
        return;
    }
    box.innerHTML = head + items.map((item, index) => {
        const labels = [
            SCENE_LABELS[item.scene_type] || item.scene_type,
            PACE_LABELS[item.pacing] || item.pacing,
            item.pov ? `${item.pov}视角` : '',
            item.emotion ? `情绪：${escapeHtml(item.emotion)}` : '',
            `${item.char_count} 字`,
        ].filter(Boolean).join(' · ');
        return `<div class="style-corpus-search-item">
            <div class="style-corpus-search-item-head">
                <strong>片段 ${index + 1}</strong>
                <span>相关度 ${item.score}</span>
            </div>
            <small>${labels}</small>
            <p>${escapeHtml(item.content.slice(0, 220))}${item.content.length > 220 ? '…' : ''}</p>
        </div>`;
    }).join('');
}

// ==================== 事件绑定 ====================

safeBind('#btn-open-corpus-panel', 'click', openCorpusPanel);
safeBind('#btn-test-corpus-search', 'click', () => {
    openCorpusPanel();
    $('#corpus-search-details')?.setAttribute('open', '');
});
safeBind('#btn-create-corpus', 'click', createCorpus);
safeBind('#corpus-new-name', 'keydown', event => {
    if (event.key === 'Enter') createCorpus();
});
safeBind('#btn-corpus-search', 'click', runSearchTest);
safeBind('#corpus-search-query', 'keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) runSearchTest();
});

// 语料库管理面板：操作委托
safeBind('#style-corpus-list', 'click', event => {
    const actionButton = event.target.closest('[data-action]');
    if (!actionButton) return;
    const item = actionButton.closest('.style-corpus-item');
    const corpusId = Number(item?.dataset.id);
    if (!corpusId) return;
    const action = actionButton.dataset.action;
    if (action === 'index') indexCorpus(corpusId);
    else if (action === 'clear') clearCorpus(corpusId);
    else if (action === 'delete') deleteCorpus(corpusId);
});
safeBind('#style-corpus-list', 'change', event => {
    const fileInput = event.target.closest('input[type="file"][data-action="import"]');
    if (!fileInput) return;
    const item = fileInput.closest('.style-corpus-item');
    const corpusId = Number(item?.dataset.id);
    if (!corpusId) return;
    importCorpusFile(corpusId, fileInput.files?.[0]);
    fileInput.value = '';
});

// 语料库多选：记忆勾选状态
safeBind('#style-rag-corpora-list', 'change', event => {
    if (!event.target.matches('input[type="checkbox"]')) return;
    const corpusId = event.target.value;
    localStorage.setItem(corpusIndexKey(corpusId), event.target.checked ? '1' : '0');
});

// 首次加载
document.addEventListener('DOMContentLoaded', loadCorporaList);
