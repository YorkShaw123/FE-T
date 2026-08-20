/**
 * Flora Editor - 全局状态与共享常量
 * 集中管理跨模块共享的应用状态、常量配置与模板分类元信息。
 */

/** 全局应用状态 */
export const state = {
    theme: localStorage.getItem('flora_theme') || 'dark',
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
    /** 一键续写时作为「前置文章」传入的已生成正文；非续写时为 null */
    pendingContinueText: null,
};

/** 工作台草稿存储键名 */
export const DRAFT_KEY = 'flora_workspace_draft_v2';

/** 需要随工作台草稿持久化的表单字段 */
export const DRAFT_FIELDS = [
    'article-title', 'previous-article',
    'deai-prompt', 'deai-enabled', 'style-reference-enabled', 'provider-select', 'model-select',
    'thinking-enabled',
    'structured-prompt-enabled',
];

/** 模板分类展示元信息（图标与名称） */
export const categoryConfig = {
    background: { name: '背景设定' },
    character: { name: '人物设定' },
    plot: { name: '剧情设定' },
    example: { name: '范例文章' },
    constraint: { name: '更多约束' },
};

/** 收集当前启用的模板 ID（供生成与预览使用） */
export function getActiveTemplateIds() {
    const ids = [];
    for (const templates of Object.values(state.groupedTemplates)) {
        for (const tpl of templates) {
            if (tpl.is_active) ids.push(tpl.id);
        }
    }
    return ids;
}
