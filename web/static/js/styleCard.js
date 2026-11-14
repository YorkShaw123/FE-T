/**
 * Flora Editor - 范例文章风格卡与片段库
 * 负责 Style Card 的加载、表单编辑、JSON 应用、分析与片段库的展示、重建和更新。
 */
import { $, $$, api, toast, escapeHtml, safeBind, linesToList } from './utils.js';
import { state } from './state.js';

/** 根据风格卡数据渲染编辑器表单 */
function renderStyleCardProfile(profile) {
    const card = profile?.card;
    const hasCard = Boolean(card && typeof card === 'object' && !Array.isArray(card));
    state.currentStyleCard = hasCard ? card : null;
    const statusLabels = {
        missing: '尚未分析', analyzing: '正在分析', ready: '可用于智能风格链', error: '分析失败',
    };
    $('#style-card-status').textContent = statusLabels[profile?.analysis_status] || '尚未分析';
    $('#style-card-empty').style.display = hasCard ? 'none' : '';
    $('#style-card-editor').style.display = hasCard ? '' : 'none';
    $('#style-excerpt-section').style.display = hasCard ? '' : 'none';
    $('#btn-save-style-card').style.display = hasCard ? '' : 'none';
    $('#btn-refresh-style-card').style.display = hasCard ? '' : 'none';
    $('#btn-restore-style-card').style.display = hasCard ? '' : 'none';
    $('#btn-analyze-style-card').textContent = profile?.analysis_status === 'error' ? '重新分析' : '分析当前模板风格';
    if (!hasCard) {
        if (profile?.error_message) $('#style-card-status').textContent = `分析失败：${profile.error_message}`;
        return;
    }
    $('#style-card-primary').checked = Boolean(profile.is_primary);
    $('#style-card-summary').value = card.summary || '';
    $('#style-card-person').value = card.narration?.person || '';
    $('#style-card-distance').value = card.narration?.distance || '';
    $('#style-card-rhythm').value = card.rhythm?.sentence_pattern || '';
    $('#style-card-register').value = card.language?.register || '';
    const behaviors = Array.isArray(card.language?.preferred_behaviors)
        ? card.language.preferred_behaviors : [];
    const avoid = Array.isArray(card.avoid) ? card.avoid : [];
    const rules = Array.isArray(card.checkable_rules) ? card.checkable_rules : [];
    $('#style-card-behaviors').value = behaviors.join('\n');
    $('#style-card-avoid').value = avoid.join('\n');
    $('#style-card-rules').value = rules.map(rule => {
        if (typeof rule === 'string') return `medium|${rule}`;
        if (!rule || typeof rule !== 'object') return '';
        return `${rule.priority || 'medium'}|${rule.rule || ''}`;
    }).filter(Boolean).join('\n');
    $('#style-card-json').value = JSON.stringify(card, null, 2);
    const notice = [];
    if (profile.is_stale) notice.push('模板正文已变化，这张风格卡需要重新分析。');
    if (profile.is_primary) notice.push('当前为主风格模板。');
    if (profile.error_message) notice.push(`最近一次重新分析失败，仍使用上次成功结果：${profile.error_message}`);
    notice.push(`分析模型：${profile.analysis_model || '未知'}`);
    $('#style-card-notice').textContent = notice.join(' ');
    $('#style-card-notice').classList.toggle(
        'warning', Boolean(profile.is_stale || profile.error_message),
    );
}

/** 从风格卡表单组装卡片对象 */
function cardFromStyleForm() {
    const card = JSON.parse(JSON.stringify(state.currentStyleCard || {}));
    card.schema_version = 1;
    card.summary = $('#style-card-summary').value.trim();
    card.narration = card.narration || {};
    card.narration.person = $('#style-card-person').value.trim();
    card.narration.distance = $('#style-card-distance').value.trim();
    card.rhythm = card.rhythm || {};
    card.rhythm.sentence_pattern = $('#style-card-rhythm').value.trim();
    card.language = card.language || {};
    card.language.register = $('#style-card-register').value.trim();
    card.language.preferred_behaviors = linesToList($('#style-card-behaviors').value);
    card.dialogue = card.dialogue || {};
    card.avoid = linesToList($('#style-card-avoid').value);
    card.checkable_rules = linesToList($('#style-card-rules').value).map((line, index) => {
        const separator = line.indexOf('|');
        const possiblePriority = separator >= 0 ? line.slice(0, separator).trim() : 'medium';
        const priority = ['hard', 'high', 'medium'].includes(possiblePriority) ? possiblePriority : 'medium';
        const rule = separator >= 0 ? line.slice(separator + 1).trim() : line;
        return { id: `rule_${String(index + 1).padStart(2, '0')}`, rule, priority };
    });
    return card;
}

/** 加载当前编辑模板的风格卡 */
export async function loadStyleProfile() {
    const id = $('#edit-template-id').value;
    // 明确"分析对象"：显示当前编辑的是哪个模板，避免用户分不清分析来源
    const targetEl = $('#style-card-target');
    if (targetEl) {
        const name = $('#edit-template-name')?.value.trim() || '未命名模板';
        const category = $('#edit-template-category')?.value || '';
        const categoryLabels = {
            example: '范例文章模板', character: '人物设定模板', background: '背景设定模板',
            plot: '剧情设定模板', constraint: '约束模板',
        };
        const label = categoryLabels[category] || '模板';
        // 无当前编辑模板（如从工作台"管理语料库"直接打开面板）时给出明确指引
        targetEl.textContent = id
            ? `分析对象：${name}（${label}）`
            : '未打开模板：请先在「模板管理 → 范例文章」中打开一个模板，再进行分析';
    }
    if (!id) {
        renderStyleCardProfile({ analysis_status: 'missing', card: null });
        return;
    }
    try {
        const data = await api(`/api/style-profiles/${id}`);
        if ($('#edit-template-id').value !== id) return;
        renderStyleCardProfile(data.data);
        if (data.data.card) await loadStyleExcerpts(id);
        else renderStyleExcerpts([]);
    } catch (error) {
        if ($('#edit-template-id').value !== id) return;
        renderStyleCardProfile({ analysis_status: 'error', error_message: error.message, card: null });
        renderStyleExcerpts([]);
    }
}

/** 渲染参考片段列表 */
function renderStyleExcerpts(excerpts) {
    const list = $('#style-excerpt-list');
    const summary = $('#style-excerpt-summary');
    const sceneLabels = {
        dialogue: '对话', action: '动作', psychology: '心理', environment: '环境',
        transition: '转场', narration: '叙事', mixed: '综合',
    };
    const enabledCount = excerpts.filter(item => item.is_enabled).length;
    const pinnedCount = excerpts.filter(item => item.is_pinned).length;
    summary.textContent = excerpts.length
        ? `${excerpts.length} 个片段 · ${enabledCount} 个启用${pinnedCount ? ` · ${pinnedCount} 个置顶` : ''}`
        : '尚未生成片段';
    if (!excerpts.length) {
        list.innerHTML = '<div class="style-excerpt-empty">生成片段后，智能风格链会按当前场景选择最相关的范例。</div>';
        return;
    }
    list.innerHTML = excerpts.map(item => `
        <article class="style-excerpt-item ${item.is_enabled ? '' : 'disabled'}" data-id="${item.id}">
            <div class="style-excerpt-item-head">
                <select class="excerpt-scene-select" data-field="scene_type" aria-label="片段场景类型">
                    ${Object.entries(sceneLabels).map(([value, label]) =>
                        `<option value="${value}" ${item.scene_type === value ? 'selected' : ''}>${label}</option>`
                    ).join('')}
                </select>
                <span>${item.char_count} 字 · 对话 ${Math.round((item.dialogue_ratio || 0) * 100)}% · ${item.pace}</span>
                <button class="excerpt-pin ${item.is_pinned ? 'active' : ''}" data-action="pin" type="button">${item.is_pinned ? '★ 已置顶' : '☆ 置顶'}</button>
                <button class="excerpt-enable ${item.is_enabled ? 'active' : ''}" data-action="enable" type="button">${item.is_enabled ? '启用' : '已排除'}</button>
            </div>
            <p>${escapeHtml(item.content.slice(0, 260))}${item.content.length > 260 ? '…' : ''}</p>
            <div class="style-excerpt-tags">${(item.tags || []).map(tag => `<span>${escapeHtml(tag)}</span>`).join('')}</div>
        </article>
    `).join('');
    $$('.style-excerpt-item', list).forEach(item => {
        const id = item.dataset.id;
        const source = excerpts.find(excerpt => String(excerpt.id) === String(id));
        $('.excerpt-scene-select', item).addEventListener('change', event => {
            updateExcerpt(id, { scene_type: event.target.value });
        });
        $('[data-action="pin"]', item).addEventListener('click', () => {
            updateExcerpt(id, { is_pinned: !source.is_pinned });
        });
        $('[data-action="enable"]', item).addEventListener('click', () => {
            updateExcerpt(id, { is_enabled: !source.is_enabled });
        });
    });
}

/** 加载当前编辑模板的参考片段 */
async function loadStyleExcerpts(templateId = $('#edit-template-id').value) {
    const id = String(templateId || '');
    if (!id) return renderStyleExcerpts([]);
    try {
        const data = await api(`/api/style-profiles/${id}/excerpts`);
        if ($('#edit-template-id').value !== id) return;
        renderStyleExcerpts(data.data || []);
    } catch (error) {
        if ($('#edit-template-id').value !== id) return;
        $('#style-excerpt-summary').textContent = '片段加载失败';
        $('#style-excerpt-list').innerHTML = `<div class="style-excerpt-empty">${escapeHtml(error.message)}</div>`;
    }
}

/** 更新单个参考片段属性 */
async function updateExcerpt(excerptId, payload) {
    const templateId = $('#edit-template-id').value;
    try {
        await api(`/api/style-profiles/${templateId}/excerpts/${excerptId}`, {
            method: 'PUT', body: JSON.stringify(payload),
        });
        if ($('#edit-template-id').value === templateId) await loadStyleExcerpts(templateId);
    } catch (error) {
        toast('更新片段失败：' + error.message, 'error');
    }
}

/** 重新切分并标注参考片段 */
async function rebuildCurrentStyleExcerpts() {
    const templateId = $('#edit-template-id').value;
    const apiKey = $('#api-key-input').value.trim();
    if (!templateId) { toast('请先保存范例模板', 'warning'); return; }
    if (!apiKey) { toast('请先在顶部输入 API 密钥', 'warning'); return; }
    const button = $('#btn-rebuild-style-excerpts');
    button.disabled = true;
    button.textContent = '正在切分与标注…';
    try {
        const data = await api(`/api/style-profiles/${templateId}/excerpts/rebuild`, {
            method: 'POST',
            body: JSON.stringify({
                api_key: apiKey,
                provider: $('#provider-select').value,
                model: $('#model-select').value,
            }),
        });
        if ($('#edit-template-id').value !== templateId) return;
        renderStyleExcerpts(data.data || []);
        toast(`已生成 ${data.data.length} 个参考片段`, 'success');
    } catch (error) {
        toast('生成参考片段失败：' + error.message, 'error');
    } finally {
        button.disabled = false;
        button.textContent = '重新生成片段';
    }
}

/** 触发当前范例模板的 Style Card 分析 */
async function analyzeCurrentStyleCard() {
    const id = $('#edit-template-id').value;
    if (!id) { toast('请先在「模板管理」中打开并保存一个范例模板', 'warning'); return; }
    const apiKey = $('#api-key-input').value.trim();
    if (!apiKey) { toast('请先在顶部输入 API 密钥', 'warning'); return; }
    const buttons = [$('#btn-analyze-style-card'), $('#btn-refresh-style-card')];
    const loading = $('#style-card-analysis-loading');
    buttons.forEach(button => { button.disabled = true; });
    loading.style.display = 'flex';
    loading.closest('.style-card-panel-body').scrollTop = 0;
    $('#style-card-status').textContent = '正在分析语言风格…';
    try {
        const data = await api(`/api/style-profiles/${id}/analyze`, {
            method: 'POST',
            body: JSON.stringify({
                api_key: apiKey,
                provider: $('#provider-select').value,
                model: $('#model-select').value,
            }),
        });
        if ($('#edit-template-id').value !== id) return;
        renderStyleCardProfile(data.data);
        await loadStyleExcerpts(id);
        toast('Style Card 分析完成', 'success');
    } catch (error) {
        if ($('#edit-template-id').value === id) {
            toast('风格分析失败：' + error.message, 'error');
            await loadStyleProfile();
        }
    } finally {
        loading.style.display = 'none';
        buttons.forEach(button => { button.disabled = false; });
    }
}

// ==================== 事件绑定 ====================

safeBind('#btn-open-style-card', 'click', async () => {
    $('#style-card-panel').style.display = 'grid';
    await loadStyleProfile();
});
safeBind('#btn-close-style-card', 'click', () => { $('#style-card-panel').style.display = 'none'; });
safeBind('#btn-analyze-style-card', 'click', analyzeCurrentStyleCard);
safeBind('#btn-refresh-style-card', 'click', analyzeCurrentStyleCard);
safeBind('#btn-rebuild-style-excerpts', 'click', rebuildCurrentStyleExcerpts);
safeBind('#btn-apply-style-json', 'click', () => {
    try {
        const card = JSON.parse($('#style-card-json').value);
        if (!card || typeof card !== 'object' || Array.isArray(card)) {
            throw new Error('Style Card 必须是 JSON 对象');
        }
        renderStyleCardProfile({
            analysis_status: 'ready', card, is_primary: $('#style-card-primary').checked,
            analysis_model: '手动编辑', is_stale: false,
        });
        toast('已将 JSON 应用到表单');
    } catch (error) {
        toast('JSON 格式错误：' + error.message, 'error');
    }
});
safeBind('#btn-save-style-card', 'click', async () => {
    const id = $('#edit-template-id').value;
    try {
        const card = cardFromStyleForm();
        const data = await api(`/api/style-profiles/${id}`, {
            method: 'PUT',
            body: JSON.stringify({ card, is_primary: $('#style-card-primary').checked }),
        });
        if ($('#edit-template-id').value !== id) return;
        renderStyleCardProfile(data.data);
        toast('Style Card 已保存', 'success');
    } catch (error) {
        toast('保存风格卡失败：' + error.message, 'error');
    }
});
safeBind('#btn-restore-style-card', 'click', async () => {
    const id = $('#edit-template-id').value;
    try {
        const data = await api(`/api/style-profiles/${id}/restore`, { method: 'POST' });
        if ($('#edit-template-id').value !== id) return;
        renderStyleCardProfile(data.data);
        toast('已恢复自动分析结果');
    } catch (error) {
        toast('恢复失败：' + error.message, 'error');
    }
});
