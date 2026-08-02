/**
 * Forestar Editor - 主应用脚本
 * 模块化结构，统一管理所有交互逻辑
 */
(function () {
    'use strict';

    // ==================== 工具函数 ====================

    const $ = (sel, ctx) => (ctx || document).querySelector(sel);
    const $$ = (sel, ctx) => [...(ctx || document).querySelectorAll(sel)];
    const api = (url, opts = {}) => fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts })
        .then(r => r.json())
        .then(d => { if (!d.success) throw new Error(d.error || '请求失败'); return d; });

    function toast(msg, type = 'info') {
        const container = $('#toast-container');
        const el = document.createElement('div');
        el.className = `toast toast-${type}`;
        el.textContent = msg;
        container.appendChild(el);
        setTimeout(() => { el.remove(); }, 3500);
    }

    function escapeHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    // ==================== 状态管理 ====================

    const state = {
        theme: localStorage.getItem('forestar_theme') || 'dark',
        templates: [],
        groupedTemplates: {},
        currentTab: 'workspace',
        templateFilterCategory: 'all',
        editingTemplateId: null,
        currentRecordId: null,
        models: {},
        isGenerating: false,
        showApiKey: false,
        historyRecords: [],
        templateSearch: '',
        generationController: null,
        resultReady: false,
        currentStyleCard: null,
    };

    const DRAFT_KEY = 'forestar_workspace_draft_v2';
    const DRAFT_FIELDS = [
        'article-title', 'previous-article',
        'deai-prompt', 'deai-enabled', 'provider-select', 'model-select',
        'thinking-enabled',
        'structured-prompt-enabled',
        'style-scene-type',
    ];

    function getWorkspaceStyleStrength() {
        return $('input[name="workspace-style-strength"]:checked')?.value || 'light';
    }

    function getWorkspaceStyleMode() {
        return $('input[name="workspace-style-mode"]:checked')?.value || 'legacy';
    }

    function updateWorkspaceStyleModeHelp() {
        const mode = getWorkspaceStyleMode();
        const help = $('#style-mode-help');
        const structured = $('#structured-prompt-enabled');
        if (!help) return;
        const descriptions = {
            legacy: '沿用当前范例文章拼接逻辑，不改变任何原有行为。',
            smart: '使用有效 Style Card 和少量代表性范例；缺少风格卡时自动回退原文拼接。',
            off: '本次生成不发送任何“范例文章/参考风格”模板。',
        };
        help.textContent = descriptions[mode];
        if (structured) {
            structured.disabled = mode === 'smart';
            structured.closest('.switch-label').title = mode === 'smart'
                ? '智能风格链会自动使用结构化消息'
                : '关闭时完整使用原有字符串拼装格式';
        }
        const sceneControl = $('#style-scene-control');
        if (sceneControl) sceneControl.style.display = mode === 'smart' ? '' : 'none';
    }

    function updateWorkspaceStyleStrengthHelp() {
        const help = $('#style-strength-help');
        if (!help) return;
        const descriptions = {
            light: '保持模板原有位置，不额外增加风格约束。',
            medium: '风格模板将移至前置文章之后，并要求正文明显贴近参考风格。',
            strict: '风格模板将移至前置文章之后，并作为本次写作的优先执行标准。',
        };
        help.textContent = descriptions[getWorkspaceStyleStrength()];
    }

    // ==================== 主题切换 ====================

    function initTheme() {
        document.documentElement.setAttribute('data-theme', state.theme);
        $('#theme-toggle').textContent = state.theme === 'dark' ? '🌙' : '☀️';

        $('#theme-toggle').addEventListener('click', () => {
            state.theme = state.theme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', state.theme);
            $('#theme-toggle').textContent = state.theme === 'dark' ? '🌙' : '☀️';
            localStorage.setItem('forestar_theme', state.theme);
        });
    }

    // ==================== 导航标签切换 ====================

    function initTabs() {
        $$('.nav-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const tabName = tab.dataset.tab;
                state.currentTab = tabName;

                $$('.nav-tab').forEach(t => t.classList.remove('active'));
                tab.classList.add('active');

                $$('.tab-content').forEach(c => c.classList.remove('active'));
                $(`#tab-${tabName}`).classList.add('active');

                if (tabName === 'templates') loadTemplatesList();
                if (tabName === 'history') loadHistoryList();
                if (tabName === 'workspace') loadWorkspaceTemplates();
            });
        });
    }

    // ==================== API密钥 ====================

    function initApiKey() {
        const input = $('#api-key-input');
        const toggle = $('#api-key-toggle');

        toggle.addEventListener('click', () => {
            state.showApiKey = !state.showApiKey;
            input.type = state.showApiKey ? 'text' : 'password';
            toggle.textContent = state.showApiKey ? '🙈' : '👁';
        });
    }

    // ==================== 模型选择器 ====================

    function initModelSelector() {
        const providerSelect = $('#provider-select');
        const modelSelect = $('#model-select');

        // 加载模型列表
        api('/api/generation/models').then(data => {
            state.models = data.data;
            updateModelOptions();
        }).catch(e => console.warn('加载模型列表失败:', e));

        providerSelect.addEventListener('change', updateModelOptions);
        modelSelect.addEventListener('change', updateThinkingAvailability);

        function updateModelOptions() {
            const provider = providerSelect.value;
            const models = state.models[provider]?.models || [];

            modelSelect.innerHTML = models.map(m =>
                `<option value="${m.id}">${m.name}${m.supports_thinking ? ' 🧠' : ''}</option>`
            ).join('');
            updateThinkingAvailability();
        }

        function updateThinkingAvailability() {
            const provider = providerSelect.value;
            const selectedModel = state.models[provider]?.models?.find(
                model => model.id === modelSelect.value
            );
            const thinking = $('#thinking-enabled');
            const label = thinking.closest('.thinking-toggle');
            const mode = selectedModel?.thinking_mode;

            if (!selectedModel?.supports_thinking) {
                thinking.checked = false;
                thinking.disabled = true;
                label.title = '当前模型不支持思考模式';
            } else if (mode === 'always') {
                thinking.checked = true;
                thinking.disabled = true;
                label.title = '当前模型固定启用思考模式';
            } else {
                thinking.disabled = false;
                label.title = '启用思考模式';
            }
        }
    }

    // ==================== 工作台 - 模板面板 ====================

    async function loadWorkspaceTemplates() {
        const container = $('#template-panel-body');
        container.innerHTML = '<p style="padding:20px;text-align:center;color:var(--text-muted);">正在加载模板...</p>';

        try {
            // 默认加载全部模板（含非活跃），让用户看到所有模板并显式控制开关
            const data = await api('/api/templates/grouped?active_only=false');
            console.log('[Forestar] 加载模板完成，各组数量:',
                Object.fromEntries(Object.entries(data.data).map(([k, v]) => [k, v.length])));
            state.groupedTemplates = data.data;
            renderWorkspaceTemplates(data.data);
            updateVariablesPanel();
        } catch (e) {
            console.error('[Forestar] 加载模板失败:', e);
            container.innerHTML = `<div style="padding:20px;text-align:center;">
                <p style="color:var(--accent-danger);margin-bottom:10px;">⚠️ 加载模板失败: ${escapeHtml(e.message)}</p>
                <button class="btn btn-outline btn-sm" onclick="location.reload()">🔄 重新加载</button>
            </div>`;
        }
    }

    const categoryConfig = {
        background: { icon: '🌍', name: '背景设定' },
        character: { icon: '👤', name: '人物设定' },
        plot: { icon: '📖', name: '剧情设定/前情提要' },
        example: { icon: '📝', name: '范例文章/参考风格' },
        constraint: { icon: '⚙️', name: '写作约束与要求' },
    };

    function renderWorkspaceTemplates(grouped) {
        const container = $('#template-panel-body');
        let html = '';
        let totalCount = 0;

        for (const [catId, templates] of Object.entries(grouped)) {
            if (!templates || templates.length === 0) continue;
            totalCount += templates.length;
            const cfg = categoryConfig[catId] || { icon: '📄', name: catId };
            const activeCount = templates.filter(t => t.is_active !== false).length;

            html += `<div class="template-category-group">`;
            html += `<div class="category-group-header" data-cat="${catId}">
                <span class="collapse-icon">▼</span>
                <span>${cfg.icon} ${cfg.name}</span>
                <span style="margin-left:auto;font-size:11px;color:var(--text-muted)">
                    ${activeCount}/${templates.length} 启用
                </span>
            </div>`;
            html += `<div class="category-templates">`;

            templates.forEach(tpl => {
                const active = tpl.is_active !== false;
                const preview = (tpl.content || '').replace(/\{\{.*?\}\}/g, '___').substring(0, 40);

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
                <p>暂无模板</p>
                <p style="font-size:12px;margin-top:8px;">请切换到"模板管理"标签页创建模板</p>
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
            updateVariablesPanel();
        } catch (e) {
            toast('切换失败: ' + e.message, 'error');
        }
    }

    // 安全绑定辅助函数：元素不存在时静默跳过
    function safeBind(selector, event, handler) {
        const el = typeof selector === 'string' ? $(selector) : selector;
        if (el) {
            el.addEventListener(event, handler);
        } else {
            console.warn('[Forestar] 找不到元素:', selector);
        }
    }

    // 刷新模板按钮
    safeBind('#btn-refresh-templates', 'click', () => {
        loadWorkspaceTemplates();
    });

    // ==================== 变量面板 ====================

    function updateVariablesPanel() {
        const content = $('#variables-modal-content');
        const tabs = $('#variables-template-tabs');
        const summary = $('#variables-summary');
        const templateGroups = [];
        const allVars = new Set();

        for (const templates of Object.values(state.groupedTemplates)) {
            for (const tpl of templates) {
                if (tpl.is_active && tpl.variables) {
                    try {
                        const vars = typeof tpl.variables === 'string' ? JSON.parse(tpl.variables) : tpl.variables;
                        if (vars.length) {
                            templateGroups.push({ template: tpl, variables: vars });
                            vars.forEach(v => allVars.add(v));
                        }
                    } catch (e) { /* ignore */ }
                }
            }
        }

        if (allVars.size === 0) {
            tabs.innerHTML = '';
            content.innerHTML = '<div class="variables-empty">当前启用的模板中没有需要填写的变量</div>';
            summary.textContent = '当前没有待填写变量';
            updateVariableCount();
            return;
        }

        tabs.innerHTML = templateGroups.map(({ template }, index) =>
            `<button type="button" class="${index === 0 ? 'active' : ''}" data-template-index="${index}">
                ${categoryConfig[template.category]?.icon || '📄'} ${escapeHtml(template.name)}
            </button>`
        ).join('');
        content.innerHTML = '';

        templateGroups.forEach(({ template }, index) => {
            const documentView = document.createElement('section');
            documentView.className = `variable-document ${index === 0 ? 'active' : ''}`;
            documentView.dataset.templateIndex = index;

            const heading = document.createElement('div');
            heading.className = 'variable-document-heading';
            const title = document.createElement('strong');
            title.textContent = template.name;
            const meta = document.createElement('span');
            meta.textContent = `${categoryConfig[template.category]?.name || template.category} · 高亮处可直接填写`;
            heading.append(title, meta);

            const body = document.createElement('div');
            body.className = 'variable-document-body';
            const source = template.content || '';
            const variablePattern = /\{\{([^{}]+)\}\}/g;
            let cursor = 0;
            let match;
            while ((match = variablePattern.exec(source)) !== null) {
                body.appendChild(document.createTextNode(source.slice(cursor, match.index)));
                const varName = match[1].trim();
                const editor = document.createElement('span');
                editor.className = 'var-input var-inline-editor';
                editor.dataset.var = varName;
                editor.contentEditable = 'plaintext-only';
                editor.setAttribute('role', 'textbox');
                editor.setAttribute('aria-label', `填写变量 ${varName}`);
                editor.dataset.placeholder = varName;
                editor.textContent = localStorage.getItem(`forestar_var_${varName}`) || '';
                editor.addEventListener('keydown', event => {
                    if (event.key === 'Enter') event.preventDefault();
                });
                body.appendChild(editor);
                cursor = variablePattern.lastIndex;
            }
            body.appendChild(document.createTextNode(source.slice(cursor)));
            documentView.append(heading, body);
            content.appendChild(documentView);
        });

        $$('.variables-template-tabs button', $('#variables-modal')).forEach(tab => {
            tab.addEventListener('click', () => {
                $$('.variables-template-tabs button', $('#variables-modal')).forEach(item => item.classList.toggle('active', item === tab));
                $$('.variable-document', content).forEach(item =>
                    item.classList.toggle('active', item.dataset.templateIndex === tab.dataset.templateIndex)
                );
            });
        });
        summary.textContent = `${templateGroups.length} 个模板 · ${allVars.size} 个变量`;

        // 绑定变化事件，自动保存到 localStorage
        $$('.var-input', content).forEach(input => {
            input.addEventListener('input', () => {
                const value = getEditableValue(input);
                localStorage.setItem(`forestar_var_${input.dataset.var}`, value);
                $$('.var-input', content)
                    .filter(other => other !== input && other.dataset.var === input.dataset.var)
                    .forEach(other => { other.textContent = value; });
                updateVariableCount();
            });
        });
        updateVariableCount();
    }

    function getEditableValue(element) {
        return element.isContentEditable ? element.textContent : element.value;
    }

    function updateVariableCount() {
        const unique = new Map();
        $$('.var-input', $('#variables-modal-content')).forEach(input =>
            unique.set(input.dataset.var, getEditableValue(input).trim())
        );
        const filled = [...unique.values()].filter(Boolean).length;
        const count = $('#variables-filled-count');
        if (count) count.textContent = unique.size ? `已填写 ${filled}/${unique.size} 个变量` : '';
    }

    function setVariablesModal(open) {
        const modal = $('#variables-modal');
        modal.hidden = !open;
        document.body.classList.toggle('modal-open', open);
        if (open) setTimeout(() => $('.var-input', modal)?.focus(), 0);
    }

    safeBind('#btn-open-variables', 'click', () => setVariablesModal(true));
    safeBind('#btn-close-variables', 'click', () => setVariablesModal(false));
    safeBind('#btn-done-variables', 'click', () => setVariablesModal(false));
    safeBind('#variables-modal', 'click', event => {
        if (event.target.id === 'variables-modal') setVariablesModal(false);
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !$('#variables-modal').hidden) setVariablesModal(false);
    });

    // ==================== 前置文章文件导入 ====================

    async function importArticleFile(file) {
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

    // ==================== 提示词预览 ====================

    function setPromptPreviewDrawer(open) {
        const drawer = $('#prompt-preview-drawer');
        const toggle = $('#btn-toggle-preview-drawer');
        if (!drawer || !toggle) return;
        drawer.classList.toggle('is-open', open);
        drawer.setAttribute('aria-expanded', String(open));
        toggle.setAttribute('aria-expanded', String(open));
        toggle.title = open ? '收起提示词预览' : '展开提示词预览';
    }

    safeBind('#btn-toggle-preview-drawer', 'click', () => {
        setPromptPreviewDrawer(!$('#prompt-preview-drawer').classList.contains('is-open'));
    });
    safeBind('#btn-collapse-preview-drawer', 'click', () => setPromptPreviewDrawer(false));
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && $('#prompt-preview-drawer')?.classList.contains('is-open')) {
            setPromptPreviewDrawer(false);
        }
    });

    function buildPromptPreviewPayload() {
        return {
            variable_values: getVariableValues(),
            previous_article: $('#previous-article').value,
            template_ids: getActiveTemplateIds(),
            style_strength: getWorkspaceStyleStrength(),
            provider: $('#provider-select').value,
            model: $('#model-select').value,
            deai_enabled: $('#deai-enabled').checked,
            deai_prompt: $('#deai-prompt').value,
            thinking_enabled: $('#thinking-enabled').checked,
            reasoning_effort: 'high',
            structured_prompt_enabled: $('#structured-prompt-enabled').checked,
            style_mode: getWorkspaceStyleMode(),
            scene_type: $('#style-scene-type')?.value || 'auto',
        };
    }

    function renderTokenBudget(budget) {
        const panel = $('#token-budget-panel');
        if (!panel || !budget) return;
        const labels = { safe: '预算充足', warning: '接近上限', over: '已超限' };
        const phaseLabels = { primary: '正文生成', deai: '去 AI 味' };
        const rows = Object.entries(budget.phases).map(([key, phase]) => {
            const percent = Math.max(0, Math.round(phase.usage_ratio * 100));
            const width = Math.min(100, percent);
            const remaining = phase.remaining_tokens >= 0
                ? `剩余 ${phase.remaining_tokens.toLocaleString()}`
                : `超出 ${Math.abs(phase.remaining_tokens).toLocaleString()}`;
            return `<div class="token-budget-phase ${phase.status}">
                <div class="token-budget-row"><strong>${phaseLabels[key] || key}</strong>
                    <span>${phase.input_tokens.toLocaleString()} / ${phase.usable_input_tokens.toLocaleString()} Token · ${remaining}</span></div>
                <div class="token-budget-track"><span style="width:${width}%"></span></div>
                <small>模型窗口 ${phase.context_window.toLocaleString()} · 输出预留 ${phase.output_reserved_tokens.toLocaleString()} · 安全余量 ${phase.safety_reserved_tokens.toLocaleString()}</small>
            </div>`;
        }).join('');
        panel.className = `token-budget-panel ${budget.status}`;
        panel.innerHTML = `<div class="token-budget-heading"><span>Token 预算（估算）</span><strong>${labels[budget.status] || budget.status}</strong></div>${rows}`;
        panel.style.display = '';
    }

    function renderStyleSelection(metadata, styleMode) {
        const panel = $('#style-selection-panel');
        if (!panel) return;
        if (!metadata || !String(styleMode || '').startsWith('smart')) {
            panel.style.display = 'none';
            return;
        }
        const sceneLabels = {
            dialogue: '对话', action: '动作', psychology: '心理', environment: '环境',
            transition: '转场', narration: '叙事', mixed: '综合',
        };
        const excerpts = metadata.selected_excerpts || [];
        const modeText = metadata.selection_mode === 'scene_retrieval'
            ? `已按“${sceneLabels[metadata.resolved_scene_type] || '综合'}”场景检索`
            : '片段库尚未建立，暂用代表性开头';
        const cards = excerpts.map(item => `
            <div class="style-selection-item">
                <div><strong>${escapeHtml(item.template_name)}</strong><span>${sceneLabels[item.scene_type] || item.scene_type} · ${item.pace} · ${item.char_count} 字</span></div>
                <small>评分 ${item.score} · ${escapeHtml((item.reasons || []).join('、') || '综合匹配')}</small>
            </div>
        `).join('');
        panel.innerHTML = `<div class="style-selection-heading"><strong>本次风格片段</strong><span>${modeText}</span></div>${cards}`;
        panel.style.display = '';
    }

    async function fetchPromptPreview() {
        return api('/api/generation/preview-prompt', {
            method: 'POST',
            body: JSON.stringify(buildPromptPreviewPayload()),
        });
    }

    safeBind('#btn-preview-prompt', 'click', async () => {
        try {
            const previewData = await fetchPromptPreview();

            const section = $('#prompt-preview-section');
            if (!section) return;
            $('#prompt-preview-empty').style.display = 'none';
            $('#prompt-preview-content').textContent = previewData.data.assembled_prompt;
            $('#prompt-preview-content').style.display = '';
            $('#prompt-preview-meta').style.display = '';
            const promptModeLabels = {
                legacy: '兼容字符串', structured: '结构化消息', 'smart-style': '智能风格链',
            };
            const fallback = previewData.data.style_mode === 'smart_fallback_legacy'
                ? ` · 已回退：${previewData.data.style_metadata?.fallback_reason || 'Style Card 不可用'}`
                : '';
            $('#prompt-preview-meta').textContent =
                `${promptModeLabels[previewData.data.prompt_mode] || previewData.data.prompt_mode} · ${previewData.data.message_count} 条消息 · ${previewData.data.template_count} 个模板 · ${previewData.data.char_count.toLocaleString()} 字符${fallback} · Token 为保守估算`;
            renderTokenBudget(previewData.data.token_budget);
            renderStyleSelection(previewData.data.style_metadata, previewData.data.style_mode);
            $('#btn-close-preview').style.display = '';
            toast(`提示词共 ${previewData.data.char_count} 字符，使用 ${previewData.data.template_count} 个模板`);
        } catch (e) {
            toast('预览失败: ' + e.message, 'error');
        }
    });

    safeBind('#btn-close-preview', 'click', () => {
        $('#prompt-preview-content').textContent = '';
        $('#prompt-preview-content').style.display = 'none';
        $('#prompt-preview-meta').style.display = 'none';
        $('#token-budget-panel').style.display = 'none';
        $('#style-selection-panel').style.display = 'none';
        $('#prompt-preview-empty').style.display = '';
        $('#btn-close-preview').style.display = 'none';
    });

    // ==================== 文章生成 ====================

    function getVariableValues() {
        const values = {};
        $$('.var-input').forEach(input => {
            values[input.dataset.var] = getEditableValue(input);
        });
        return values;
    }

    function getActiveTemplateIds() {
        const ids = [];
        for (const templates of Object.values(state.groupedTemplates)) {
            for (const tpl of templates) {
                if (tpl.is_active) ids.push(tpl.id);
            }
        }
        return ids;
    }

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
        $('#first-content').innerHTML = '';
        $('#deai-content').innerHTML = '';
        $('#reasoning-section').style.display = 'none';
        $('#reasoning-content').textContent = '';
        $('#deai-content-section').style.display = 'none';
        $('#first-content-section').querySelector('.section-header h4').textContent = '第一版（生成中...）';

        // 显示加载指示器
        $('#loading-overlay').style.display = '';
        $('#loading-text').textContent = deaiEnabled ? '正在连接API，准备生成...' : '正在连接API，准备生成...';
        $('#btn-generate').disabled = true;
        $('#btn-generate').style.display = 'none';
        $('#btn-stop-generate').style.display = '';
        $('#btn-stop-generate').disabled = false;
        $('#btn-stop-generate').textContent = '⏹ 停止生成';

        try {
            await generateStream(
                apiKey, templateIds, deaiEnabled, state.generationController.signal
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

    async function generateStream(apiKey, templateIds, deaiEnabled, signal) {
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
                title: $('#article-title').value || '未命名',
                previous_article: $('#previous-article').value,
                variable_values: getVariableValues(),
                template_ids: templateIds,
                style_strength: getWorkspaceStyleStrength(),
                structured_prompt_enabled: $('#structured-prompt-enabled').checked,
                style_mode: getWorkspaceStyleMode(),
                scene_type: $('#style-scene-type')?.value || 'auto',
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
        let reasoningContent = '';
        let currentRecordId = null;
        let isDeaiPhase = false;

        // 状态更新
        function updateStatus() {
            if (isDeaiPhase) {
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
                    if (isDeaiPhase) {
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
                } else if (type === 'complete') {
                    currentRecordId = eventData.record_id;
                    reasoningContent = eventData.reasoning_content || reasoningContent;
                    firstContent = eventData.first_content || firstContent;
                    deaiContent = eventData.deai_content || deaiContent;
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

        state.currentRecordId = currentRecordId;
        toast('文章生成成功！' + (deaiContent ? '已应用去AI味处理。' : ''));
    }

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

        // 保存记录ID
        state.currentRecordId = response.record?.id;
        state.resultReady = true;
        $('#btn-open-result-editor').disabled = false;
        $('#btn-open-result-editor').title = '进入全屏编辑';

        section.scrollIntoView({ behavior: 'smooth' });
    }

    function formatArticle(text) {
        if (!text) return '<p style="color:var(--text-muted)">暂无内容</p>';
        // 简单的段落格式化
        return text
            .split('\n')
            .map(line => line.trim() ? `<p>${escapeHtml(line)}</p>` : '<br>')
            .join('');
    }

    // ==================== 结果操作 ====================

    function getArticleText(element) {
        return (element.innerText || element.textContent || '').trim();
    }

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

    function setResultEditorDirty(dirty) {
        resultEditState.dirty = dirty;
        $('#result-editor-save-state').textContent = dirty ? '有未保存修改' : '已保存';
        $('#result-editor-save-state').classList.toggle('dirty', dirty);
    }

    async function openResultEditor() {
        if (state.isGenerating) {
            toast('请等待生成结束或先停止生成', 'warning');
            return;
        }
        if (!state.resultReady) {
            toast('文章尚未完整生成，暂不能进入编辑', 'warning');
            return;
        }
        let base = getArticleText($('#deai-content')) || getArticleText($('#first-content'));
        let edited = '';
        let history = [];
        if (state.currentRecordId) {
            try {
                const data = await api(`/api/generation/records/${state.currentRecordId}`);
                const record = data.data;
                base = record.deai_content || record.content || base;
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
    safeBind('#btn-close-result-editor', 'click', () => {
        if (resultEditState.dirty && !confirm('修改版尚未保存，确定退出吗？')) return;
        $('#result-editor-panel').style.display = 'none';
        document.body.classList.remove('result-editor-open');
    });

    safeBind('#result-markdown-editor', 'input', () => {
        renderResultMarkdown();
        setResultEditorDirty(true);
    });

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

    $$('.result-selection-operation').forEach(button => {
        button.addEventListener('click', () => {
            $$('.result-selection-operation').forEach(item => item.classList.toggle('active', item === button));
            resultEditState.operation = button.dataset.operation;
        });
    });

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
    safeBind('#btn-toggle-result-preview', 'click', event => {
        const hidden = $('#result-editor-panel').classList.toggle('preview-hidden');
        event.currentTarget.textContent = hidden ? '显示预览' : '隐藏预览';
    });

    safeBind('#btn-copy-result', 'click', () => {
        const deaiContent = getArticleText($('#deai-content'));
        const content = deaiContent || getArticleText($('#first-content'));

        navigator.clipboard.writeText(content).then(() => {
            toast('已复制到剪贴板');
        }).catch(() => {
            toast('复制失败，请手动复制', 'error');
        });
    });

    safeBind('#btn-download-result', 'click', () => {
        const deaiContent = getArticleText($('#deai-content'));
        const content = deaiContent || getArticleText($('#first-content'));
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

    // ==================== 模板管理 ====================

    let currentTemplateCategory = 'all';

    async function loadTemplatesList() {
        try {
            const category = currentTemplateCategory === 'all' ? undefined : currentTemplateCategory;
            const data = await api(`/api/templates${category ? '?category=' + category : ''}`);
            state.templates = data.data;
            renderTemplateList(data.data);
        } catch (e) {
            console.error('加载模板列表失败:', e);
        }
    }

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
        </div><div id="template-list-results"></div>`;
        const results = $('#template-list-results', container);
        results.innerHTML = filtered.length ? filtered.map(tpl => {
            const active = tpl.is_active !== false;
            const preview = tpl.content ? tpl.content.replace(/\{\{.*?\}\}/g, '___').substring(0, 60) : '';
            const vars = tpl.variables ? (typeof tpl.variables === 'string' ? JSON.parse(tpl.variables) : tpl.variables).join(', ') : '';
            const updatedAt = tpl.updated_at ? new Date(tpl.updated_at).toLocaleString('zh-CN') : '';
            return `<div class="template-list-item ${active ? 'active' : ''}" data-id="${tpl.id}">
                <span class="item-status"></span>
                <div class="item-info">
                    <div class="item-name">${escapeHtml(tpl.name)} <span style="font-size:11px;color:var(--text-muted)">v${tpl.version}</span></div>
                    <div class="item-meta">${vars ? '📌 ' + escapeHtml(vars) : '无变量'} · ${updatedAt}</div>
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

        // 绑定点击事件
        $$('.template-list-item', results).forEach(item => {
            item.addEventListener('click', () => {
                const id = parseInt(item.dataset.id);
                openTemplateEditor(id);
            });
        });
    }

    // 分类筛选
    $$('#category-list .category-item').forEach(item => {
        item.addEventListener('click', () => {
            $$('#category-list .category-item').forEach(i => i.classList.remove('active'));
            item.classList.add('active');
            currentTemplateCategory = item.dataset.category;
            loadTemplatesList();
        });
    });

    // 新建模板
    safeBind('#btn-new-template', 'click', () => {
        openTemplateEditor(null);
    });

    // 导出
    safeBind('#btn-export-templates', 'click', async () => {
        try {
            const response = await fetch('/api/templates/export', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ format: 'json' }),
            });

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

    // 导入
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

    // 关闭编辑器
    safeBind('#btn-close-editor', 'click', closeTemplateEditor);

    function closeTemplateEditor() {
        $('#template-editor-panel').style.display = 'none';
        $('#version-history-panel').style.display = 'none';
        $('#style-card-panel').style.display = 'none';
        document.body.classList.remove('template-editor-open');
        state.editingTemplateId = null;
        state.currentStyleCard = null;
    }

    function updateStyleCardVisibility() {
        const isExample = $('#edit-template-category').value === 'example';
        $('#btn-open-style-card').style.display = isExample ? '' : 'none';
        if (!isExample) $('#style-card-panel').style.display = 'none';
    }

    function linesToList(value) {
        return String(value || '').split('\n').map(item => item.trim()).filter(Boolean);
    }

    function renderStyleCardProfile(profile) {
        state.currentStyleCard = profile?.card || null;
        const hasCard = Boolean(profile?.card);
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
        $('#btn-analyze-style-card').textContent = profile?.analysis_status === 'error' ? '重新分析' : '分析当前范例';
        if (!hasCard) {
            if (profile?.error_message) $('#style-card-status').textContent = `分析失败：${profile.error_message}`;
            return;
        }
        const card = profile.card;
        $('#style-card-primary').checked = Boolean(profile.is_primary);
        $('#style-card-summary').value = card.summary || '';
        $('#style-card-person').value = card.narration?.person || '';
        $('#style-card-distance').value = card.narration?.distance || '';
        $('#style-card-rhythm').value = card.rhythm?.sentence_pattern || '';
        $('#style-card-register').value = card.language?.register || '';
        $('#style-card-behaviors').value = (card.language?.preferred_behaviors || []).join('\n');
        $('#style-card-avoid').value = (card.avoid || []).join('\n');
        $('#style-card-rules').value = (card.checkable_rules || []).map(rule =>
            `${rule.priority || 'medium'}|${rule.rule || ''}`
        ).join('\n');
        $('#style-card-json').value = JSON.stringify(card, null, 2);
        const notice = [];
        if (profile.is_stale) notice.push('模板正文已变化，这张风格卡需要重新分析。');
        if (profile.is_primary) notice.push('当前为主风格模板。');
        notice.push(`分析模型：${profile.analysis_model || '未知'}`);
        $('#style-card-notice').textContent = notice.join(' ');
        $('#style-card-notice').classList.toggle('warning', Boolean(profile.is_stale));
    }

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

    async function loadStyleProfile() {
        const id = $('#edit-template-id').value;
        if (!id) {
            renderStyleCardProfile({ analysis_status: 'missing', card: null });
            return;
        }
        try {
            const data = await api(`/api/style-profiles/${id}`);
            renderStyleCardProfile(data.data);
            if (data.data.card) await loadStyleExcerpts();
        } catch (error) {
            renderStyleCardProfile({ analysis_status: 'error', error_message: error.message, card: null });
        }
    }

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

    async function loadStyleExcerpts() {
        const id = $('#edit-template-id').value;
        if (!id) return renderStyleExcerpts([]);
        try {
            const data = await api(`/api/style-profiles/${id}/excerpts`);
            renderStyleExcerpts(data.data || []);
        } catch (error) {
            $('#style-excerpt-summary').textContent = '片段加载失败';
            $('#style-excerpt-list').innerHTML = `<div class="style-excerpt-empty">${escapeHtml(error.message)}</div>`;
        }
    }

    async function updateExcerpt(excerptId, payload) {
        const templateId = $('#edit-template-id').value;
        try {
            await api(`/api/style-profiles/${templateId}/excerpts/${excerptId}`, {
                method: 'PUT', body: JSON.stringify(payload),
            });
            await loadStyleExcerpts();
        } catch (error) {
            toast('更新片段失败：' + error.message, 'error');
        }
    }

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
            renderStyleExcerpts(data.data || []);
            toast(`已生成 ${data.data.length} 个参考片段`, 'success');
        } catch (error) {
            toast('生成参考片段失败：' + error.message, 'error');
        } finally {
            button.disabled = false;
            button.textContent = '重新生成片段';
        }
    }

    async function analyzeCurrentStyleCard() {
        const id = $('#edit-template-id').value;
        if (!id) { toast('请先保存范例模板', 'warning'); return; }
        const apiKey = $('#api-key-input').value.trim();
        if (!apiKey) { toast('请先在顶部输入 API 密钥', 'warning'); return; }
        const buttons = [$('#btn-analyze-style-card'), $('#btn-refresh-style-card')];
        buttons.forEach(button => { button.disabled = true; });
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
            renderStyleCardProfile(data.data);
            await loadStyleExcerpts();
            toast('Style Card 分析完成', 'success');
        } catch (error) {
            toast('风格分析失败：' + error.message, 'error');
            await loadStyleProfile();
        } finally {
            buttons.forEach(button => { button.disabled = false; });
        }
    }

    safeBind('#edit-template-category', 'change', updateStyleCardVisibility);
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
            renderStyleCardProfile(data.data);
            toast('已恢复自动分析结果');
        } catch (error) {
            toast('恢复失败：' + error.message, 'error');
        }
    });

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

    async function openTemplateEditor(templateId) {
        const panel = $('#template-editor-panel');
        panel.style.display = '';
        document.body.classList.add('template-editor-open');
        $('#version-history-panel').style.display = 'none';

        if (templateId === null) {
            // 新建
            $('#editor-title').textContent = '新建模板';
            $('#edit-template-id').value = '';
            $('#edit-template-name').value = '';
            $('#edit-template-category').value = currentTemplateCategory === 'all' ? 'constraint' : currentTemplateCategory;
            $('#edit-template-desc').value = '';
            $('#edit-template-content').value = '';
            renderMarkdownPreview();
                state.editingTemplateId = null;
                updateStyleCardVisibility();
            } else {
            // 编辑
            try {
                const data = await api(`/api/templates/${templateId}`);
                const tpl = data.data;
                $('#editor-title').textContent = `编辑模板 - ${tpl.name} (v${tpl.version})`;
                $('#edit-template-id').value = tpl.id;
                $('#edit-template-name').value = tpl.name;
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
    }

    // 保存模板
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

    // 一键删除所有模板
    safeBind('#btn-delete-all-templates', 'click', async () => {
        if (!confirm('确定要删除所有模板吗？此操作不可撤销。')) return;
        try {
            const result = await api('/api/templates', { method: 'DELETE' });
            toast(`已删除 ${result.deleted} 个模板`);
            closeTemplateEditor();
            loadTemplatesList();
        } catch (e) {
            toast('删除失败: ' + e.message, 'error');
        }
    });

    // 版本历史
    safeBind('#btn-version-history', 'click', async () => {
        const id = $('#edit-template-id').value;
        if (!id) { toast('请先保存模板', 'warning'); return; }

        try {
            const data = await api(`/api/templates/${id}/versions`);
            const panel = $('#version-history-panel');
            panel.style.display = '';

            const list = $('#version-list');
            list.innerHTML = data.data.map(v => `
                <div class="template-list-item ${v.is_active ? 'active' : ''}" style="cursor:default;">
                    <div class="item-info">
                        <div class="item-name">
                            v${v.version}
                            ${v.is_active ? '<span style="color:var(--accent-success);font-size:11px;"> ● 当前</span>' : ''}
                        </div>
                        <div class="item-meta">${new Date(v.updated_at).toLocaleString('zh-CN')}</div>
                    </div>
                    ${!v.is_active ? `<button class="btn btn-xs btn-outline restore-version-btn" data-vid="${v.id}">恢复</button>` : ''}
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

    // ==================== 历史记录 ====================

    async function loadHistoryList() {
        try {
            const data = await api('/api/generation/records');
            const records = data.data.items;
            state.historyRecords = records;

            const container = $('#history-list');

            if (records.length === 0) {
                container.innerHTML = `<p style="text-align:center;padding:40px;color:var(--text-muted);">暂无生成记录</p>`;
                return;
            }

            container.innerHTML = `<div class="list-toolbar history-toolbar">
                <input id="history-search" class="input-text" type="search"
                    placeholder="搜索标题、模型或正文摘要">
                <span class="list-count">${records.length} 条</span>
                <button id="btn-delete-all-records" class="btn btn-xs btn-danger" style="margin-left:auto;">🗑️ 删除全部</button>
            </div><div id="history-list-results"></div>`;
            renderHistoryRecords(records);
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

    function renderHistoryRecords(records) {
        const container = $('#history-list-results');
        if (!container) return;
        if (!records.length) {
            container.innerHTML = '<div class="empty-state">没有匹配的生成记录</div>';
            return;
        }
        container.innerHTML = records.map(r => `
                <div class="history-item ${r.is_pinned ? 'pinned' : ''}" data-id="${r.id}">
                    <div class="h-title" data-field="title">${escapeHtml(r.title)}</div>
                    <div class="h-preview">${escapeHtml(r.content_preview || '')}</div>
                    <div class="h-meta">
                        <span>${r.model_used || '未知模型'}</span>
                        ${r.has_deai ? '<span style="color:var(--accent-success)">已去AI味</span>' : ''}
                        ${r.has_edited ? '<span class="history-edited-badge">有修改版</span>' : ''}
                        <span>${new Date(r.created_at).toLocaleString('zh-CN')}</span>
                        <span class="history-actions" onclick="event.stopPropagation();">
                            <button data-action="rename" title="重命名">✏️</button>
                            <button data-action="pin" class="${r.is_pinned ? 'active' : ''}" title="${r.is_pinned ? '取消置顶' : '置顶'}">${r.is_pinned ? '★' : '☆'}</button>
                            <button data-action="delete" class="danger" title="删除">🗑️</button>
                        </span>
                    </div>
                </div>
            `).join('');

        $$('.history-item', container).forEach(item => {
            item.addEventListener('click', event => {
                if (event.target.closest('.history-actions') || event.target.closest('.history-rename-input')) return;
                const id = parseInt(item.dataset.id);
                loadHistoryDetail(id);
                $$('.history-item', container).forEach(i => i.classList.remove('active'));
                item.classList.add('active');
            });
        });

        $$('.history-actions button', container).forEach(button => {
            button.addEventListener('click', event => {
                event.stopPropagation();
                const item = button.closest('.history-item');
                const id = parseInt(item.dataset.id);
                const action = button.dataset.action;
                if (action === 'rename') startRenameHistoryRecord(item, id);
                else if (action === 'pin') togglePinHistoryRecord(id, !item.classList.contains('pinned'));
                else if (action === 'delete') deleteHistoryRecord(id);
            });
        });
    }

    async function togglePinHistoryRecord(id, pinned) {
        try {
            await api(`/api/generation/records/${id}`, {
                method: 'PUT',
                body: JSON.stringify({ is_pinned: pinned }),
            });
            toast(pinned ? '已置顶' : '已取消置顶');
            loadHistoryList();
        } catch (e) {
            toast('操作失败: ' + e.message, 'error');
        }
    }

    async function deleteHistoryRecord(id) {
        if (!confirm('确定要删除这条生成记录吗？此操作不可撤销。')) return;
        try {
            await api(`/api/generation/records/${id}`, { method: 'DELETE' });
            toast('生成记录已删除');
            if (state.currentRecordId === id) {
                $('#history-detail').style.display = 'none';
                state.currentRecordId = null;
            }
            loadHistoryList();
        } catch (e) {
            toast('删除失败: ' + e.message, 'error');
        }
    }

    async function deleteAllRecords() {
        if (!confirm('确定要删除所有生成记录吗？此操作不可撤销。')) return;
        try {
            const result = await api('/api/generation/records', { method: 'DELETE' });
            toast(`已删除 ${result.deleted} 条生成记录`);
            $('#history-detail').style.display = 'none';
            state.currentRecordId = null;
            loadHistoryList();
        } catch (e) {
            toast('删除失败: ' + e.message, 'error');
        }
    }

    function startRenameHistoryRecord(item, id) {
        const titleEl = $('.h-title[data-field="title"]', item);
        if (!titleEl || $('.history-rename-input', item)) return;

        const currentTitle = titleEl.textContent;
        titleEl.classList.add('editing');

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'history-rename-input';
        input.value = currentTitle;
        input.placeholder = '输入新名称';
        titleEl.before(input);
        input.focus();
        input.setSelectionRange(0, input.value.length);

        async function save() {
            if (!input.isConnected) return;
            const newTitle = input.value.trim();
            if (newTitle && newTitle !== currentTitle) {
                try {
                    await api(`/api/generation/records/${id}`, {
                        method: 'PUT',
                        body: JSON.stringify({ title: newTitle }),
                    });
                    titleEl.textContent = newTitle;
                    toast('已重命名');
                    if (state.currentRecordId === id) {
                        $('#history-detail-title').textContent = newTitle;
                    }
                    const record = state.historyRecords.find(r => r.id === id);
                    if (record) record.title = newTitle;
                } catch (e) {
                    toast('重命名失败: ' + e.message, 'error');
                }
            }
            cleanup();
        }

        function cleanup() {
            input.remove();
            titleEl.classList.remove('editing');
        }

        input.addEventListener('keydown', event => {
            if (event.key === 'Enter') save();
            else if (event.key === 'Escape') cleanup();
        });
        input.addEventListener('blur', save);
    }

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

    async function loadHistoryDetail(recordId) {
        try {
            const data = await api(`/api/generation/records/${recordId}`);
            const record = data.data;

            const detail = $('#history-detail');
            detail.style.display = '';

            $('#history-detail-title').textContent = record.title;
            $('#history-detail-meta').innerHTML = `
                模型: ${record.model_used || '未知'} |
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

    // ==================== 初始化 ====================

    function saveWorkspaceDraft() {
        const draft = {};
        DRAFT_FIELDS.forEach(id => {
            const el = $(`#${id}`);
            if (el) draft[id] = el.type === 'checkbox' ? el.checked : el.value;
        });
        draft.variableValues = {};
        draft.styleStrength = getWorkspaceStyleStrength();
        draft.styleMode = getWorkspaceStyleMode();
        $$('.var-input').forEach(input => {
            draft.variableValues[input.dataset.var] = getEditableValue(input);
        });
        localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    }

    function restoreWorkspaceDraft() {
        try {
            const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}');
            DRAFT_FIELDS.forEach(id => {
                const el = $(`#${id}`);
                if (!el || draft[id] === undefined) return;
                if (el.type === 'checkbox') el.checked = Boolean(draft[id]);
                else el.value = draft[id];
            });
            const strength = draft.styleStrength || 'light';
            const strengthInput = $(`input[name="workspace-style-strength"][value="${strength}"]`);
            if (strengthInput) strengthInput.checked = true;
            const styleMode = draft.styleMode || 'legacy';
            const modeInput = $(`input[name="workspace-style-mode"][value="${styleMode}"]`);
            if (modeInput) modeInput.checked = true;
            updateWorkspaceStyleStrengthHelp();
            updateWorkspaceStyleModeHelp();
            $$('input[name="workspace-style-strength"]').forEach(input => {
                input.addEventListener('change', updateWorkspaceStyleStrengthHelp);
            });
            $$('input[name="workspace-style-mode"]').forEach(input => {
                input.addEventListener('change', () => {
                    updateWorkspaceStyleModeHelp();
                    saveWorkspaceDraft();
                });
            });
            document.addEventListener('input', event => {
                if (event.target.matches('input, textarea, select')) saveWorkspaceDraft();
            });
            window.addEventListener('beforeunload', saveWorkspaceDraft);
        } catch (e) {
            console.warn('草稿恢复失败:', e);
        }
    }

    function init() {
        initTheme();
        initTabs();
        initApiKey();
        initModelSelector();
        restoreWorkspaceDraft();

        // 初始加载工作台模板
        loadWorkspaceTemplates();
    }

    // 页面加载完成后初始化
    document.addEventListener('DOMContentLoaded', init);

})();
