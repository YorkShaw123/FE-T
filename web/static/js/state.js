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

/**
 * 工作模式预设（骨架）。
 * 为“公众号/运营文案”等工作模式预留的声明式常量；当前仅 novel 已实现，
 * 其余模式由后端 /api/modes 提供完整元数据，这里只保留前端可用的精简常量。
 */
export const WORK_MODES = {
    novel: {
        id: 'novel',
        name: '小说创作',
        description: '人物、背景、剧情、范例组成的设定化写作',
        categories: ['background', 'character', 'plot', 'example', 'constraint'],
        enabled: true,
    },
    marketing: {
        id: 'marketing',
        name: '公众号/运营文案',
        description: '公众号文章、运营文案、更新日志等公告与营销文体（规划中）',
        categories: ['copy_article', 'copy_update', 'copy_social', 'copy_brand'],
        enabled: false,
    },
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
