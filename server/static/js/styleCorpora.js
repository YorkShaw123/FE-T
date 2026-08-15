/**
 * Forestar Editor - 风格语料库管理（Style RAG）
 * 负责语料库 CRUD、文本导入、向量化索引、检索测试，以及生成请求的语料选择。
 */
import { $, $$, api, toast, escapeHtml, safeBind } from './utils.js';

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

function getEmbeddingBackend() {
    return $('#style-rag-embedding-backend')?.value === 'remote' ? 'remote' : 'local';
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
        const usable = corpus.chunk_count > 0;
        return `<label class="style-rag-corpus-item" title="${escapeHtml(corpus.description || corpus.name)}">
            <input type="checkbox" value="${corpus.id}"${checked}${usable ? '' : ' disabled'}>
            <span><strong>${escapeHtml(corpus.name)}</strong>
                <small>${corpus.chunk_count} 片段${indexed ? ' · 含语义辅助' : ' · 纯本地文风检索'}</small>
            </span>
        </label>`;
    }).join('');
}

/** 渲染语料库管理面板列表 */
function renderCorpusManager(corpora) {
    const list = $('#style-corpus-list');
    const empty = $('#style-corpus-manager-empty');
    if (!list) return;
    if (empty) empty.style.display = corpora.length ? 'none' : '';
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

function openStyleManagement() {
    document.querySelector('.nav-tab[data-tab="styles"]')?.click();
    loadCorporaList();
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
    const backend = getEmbeddingBackend();
    const apiKey = getEmbeddingApiKey();
    if (backend === 'remote' && !apiKey) {
        toast('远程向量化需要独立的 Embedding 密钥', 'warning');
        return;
    }
    openIndexProgress();
    let polling = true;
    const poll = async () => {
        if (!polling) return;
        try {
            const { data } = await api(`/api/style-corpora/${corpusId}/index-progress`);
            renderIndexProgress(data);
        } catch (_error) {
            // 索引 POST 的最终结果负责展示错误；短暂轮询失败不打断任务。
        }
        if (polling) setTimeout(poll, 500);
    };
    poll();
    try {
        const { data } = await api(`/api/style-corpora/${corpusId}/index`, {
            method: 'POST',
            body: JSON.stringify({ backend, api_key: apiKey, provider: 'siliconflow' }),
        });
        renderIndexProgress({
            status: 'completed', completed: data.indexed_count, total: data.indexed_count,
            percent: 100, message: `向量化完成：${data.indexed_count} 个片段`,
            estimated_remaining_seconds: 0,
        });
        toast(`向量化完成：${data.indexed_count} 个片段，可参与风格检索`);
        loadCorporaList();
    } catch (e) {
        renderIndexProgress({ status: 'failed', message: `向量化失败：${e.message}` });
        toast('向量化失败: ' + e.message, 'error');
    } finally {
        polling = false;
    }
}

function openIndexProgress() {
    const modal = $('#embedding-progress-modal');
    modal.hidden = false;
    modal.querySelector('.embedding-progress-dialog')?.classList.remove('done');
    $('#btn-close-embedding-progress').hidden = true;
    renderIndexProgress({
        status: 'running', completed: 0, total: 0, percent: 0,
        elapsed_seconds: 0, estimated_remaining_seconds: null,
        message: '正在加载本地向量模型…',
    });
}

function renderIndexProgress(progress = {}) {
    const percent = Math.min(Math.max(Number(progress.percent) || 0, 0), 100);
    const completed = Number(progress.completed) || 0;
    const total = Number(progress.total) || 0;
    const done = progress.status === 'completed' || progress.status === 'failed';
    $('#embedding-progress-bar').style.width = `${percent}%`;
    $('#embedding-progress-percent').textContent = `${Math.round(percent)}%`;
    $('#embedding-progress-count').textContent = `${completed.toLocaleString()} / ${total.toLocaleString()} 个片段`;
    $('#embedding-progress-message').textContent = progress.message || '正在向量化…';
    $('#embedding-progress-elapsed').textContent = formatDuration(progress.elapsed_seconds);
    $('#embedding-progress-remaining').textContent = progress.estimated_remaining_seconds == null
        ? '计算中…' : formatDuration(progress.estimated_remaining_seconds);
    $('.embedding-progress-track').setAttribute('aria-valuenow', String(Math.round(percent)));
    $('.embedding-progress-dialog')?.classList.toggle('done', done);
    $('#btn-close-embedding-progress').hidden = !done;
}

function formatDuration(seconds) {
    const value = Math.max(Math.round(Number(seconds) || 0), 0);
    if (value < 60) return `${value} 秒`;
    const minutes = Math.floor(value / 60);
    const remainder = value % 60;
    return remainder ? `${minutes} 分 ${remainder} 秒` : `${minutes} 分钟`;
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
    const queryScene = SCENE_LABELS[meta.query_scene_type] || meta.query_scene_type || '无法判断';
    const effectiveScene = SCENE_LABELS[meta.effective_scene_type]
        || meta.effective_scene_type || '自动';
    const profileSummary = (meta.profile_summaries || []).map(profile => {
        const sceneProfile = profile.scene_profile || {};
        const sourceLabels = { mode: '精确场景', broad: '宽类别回退', global: '全局回退' };
        return `<div class="style-debug-profile-card">
            <strong>${escapeHtml(profile.corpus_name || `语料库 ${profile.corpus_id}`)}</strong>
            <span>全局：${profile.sample_count || 0} 窗口 · ${(profile.valid_char_count || 0).toLocaleString()} 字 · 置信度 ${formatScore(profile.confidence)}</span>
            <span>当前 Profile：${escapeHtml(sourceLabels[sceneProfile.source] || sceneProfile.source || '未知')} / ${escapeHtml(SCENE_LABELS[sceneProfile.resolved_mode] || sceneProfile.resolved_mode || 'global')} · ${sceneProfile.sample_count || 0} 窗口 · 置信度 ${formatScore(sceneProfile.confidence)}</span>
            <span>Feature v${profile.feature_version ?? '—'} · Signature v${profile.signature_version ?? '—'}</span>
        </div>`;
    }).join('');
    const head = `<div class="style-corpus-search-head">
        <span>候选 ${meta.candidate_count ?? 0} · 向量 ${meta.vector_enabled ? '开' : '关'} · BM25 ${meta.bm25_enabled ? '开' : '关'}</span>
        <span>Query 判定：${escapeHtml(queryScene)} · 实际检索：${escapeHtml(effectiveScene)} · 节奏 ${PACE_LABELS[meta.resolved_pacing] || meta.resolved_pacing || '自动'}</span>
    </div><div class="style-debug-profile-summary">${profileSummary}</div>${meta.embedding_fallback_reason
        ? `<small class="style-corpus-search-empty">语义辅助未启用：${escapeHtml(meta.embedding_fallback_reason)}；当前使用纯 Style Engine。需要语义辅助时请安装对应本地模型或重新索引。</small>`
        : ''}`;
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
        const scoreItems = [
            ['综合分', item.score], ['文风分', item.style_score], ['节奏', item.rhythm_score],
            ['标点', item.punctuation_score], ['功能词', item.function_word_score],
            ['Style Signature', item.signature_score, item.ranking_explanation?.signature_version_compatible],
            ['场景', item.scene_score], ['语义', item.semantic_score],
            ['内容重合惩罚', item.content_overlap_penalty], ['Confidence', item.confidence],
        ];
        const scores = scoreItems.map(([label, value, compatible]) => {
            const unavailable = value === null || value === undefined
                || (label === 'Style Signature' && compatible === false);
            return `<div class="style-debug-score${unavailable ? ' unavailable' : ''}">
                <small>${escapeHtml(label)}</small><strong>${unavailable ? '未启用' : formatScore(value)}</strong>
            </div>`;
        }).join('');
        const reasons = (item.debug_reasons || []).map(reason => {
            const tone = reason.startsWith('△') ? 'difference' : 'match';
            return `<li class="${tone}">${escapeHtml(reason)}</li>`;
        }).join('') || '<li>暂无足够可靠的主要理由</li>';
        const detail = item.ranking_explanation || {};
        return `<div class="style-corpus-search-item">
            <div class="style-corpus-search-item-head">
                <strong>片段 ${index + 1}</strong>
                <span>综合分 ${formatScore(item.score)}</span>
            </div>
            <small>${labels}</small>
            <div class="style-debug-score-grid">${scores}</div>
            <ul class="style-debug-reasons">${reasons}</ul>
            <p>${escapeHtml(item.content.slice(0, 220))}${item.content.length > 220 ? '…' : ''}</p>
            <details class="style-debug-details">
                <summary>展开详细指标</summary>
                <div class="style-debug-detail-grid">
                    <span>Profile：${escapeHtml(detail.profile_source || '未知')} / ${escapeHtml(detail.profile_mode || '未知')}</span>
                    <span>功能 Feature：节奏 ${detail.feature_counts?.rhythm ?? 0} · 标点 ${detail.feature_counts?.punctuation ?? 0} · 功能词 ${detail.feature_counts?.function_word ?? 0} · Signature ${detail.feature_counts?.signature ?? 0}</span>
                    <span>BM25 排名分：${formatScore(detail.lexical_score)}</span>
                    <span>字符 8-gram 重合：${formatScore(detail.ngram_overlap)}</span>
                    <span>内容关键词重合：${formatScore(detail.keyword_overlap)}</span>
                    <span>最长连续重合：${detail.longest_common_substring ?? 0} 字</span>
                    <span>Signature 版本：${detail.signature_version_compatible ? '兼容' : '不可用或需重建'}</span>
                </div>
            </details>
        </div>`;
    }).join('');
}

function formatScore(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(3) : '—';
}

// ==================== 事件绑定 ====================

safeBind('#btn-open-corpus-panel', 'click', openStyleManagement);
safeBind('#btn-refresh-corpora', 'click', loadCorporaList);
safeBind('#btn-create-corpus', 'click', createCorpus);
safeBind('#corpus-new-name', 'keydown', event => {
    if (event.key === 'Enter') createCorpus();
});
safeBind('#btn-corpus-search', 'click', runSearchTest);
safeBind('#btn-close-embedding-progress', 'click', () => {
    $('#embedding-progress-modal').hidden = true;
});
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
