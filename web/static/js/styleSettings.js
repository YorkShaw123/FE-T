/**
 * Flora Editor - 工作台风格设置
 * 负责模板级风格卡模式（legacy/smart/off）与风格强度的读取和提示更新。
 */
import { $ } from './utils.js';

/** 读取当前风格模式 */
export function getWorkspaceStyleMode() {
    return $('input[name="workspace-style-mode"]:checked')?.value || 'legacy';
}

/** 根据风格模式更新说明文案与相关控件状态 */
export function updateWorkspaceStyleModeHelp() {
    const mode = getWorkspaceStyleMode();
    const help = $('#style-mode-help');
    const structured = $('#structured-prompt-enabled');
    if (!help) return;
    const descriptions = {
        legacy: '原文拼接：把你启用的“范例文章”模板全文直接拼进生成提示词。适合范例不长、希望严格贴近原文风格的情况。',
        smart: '智能风格链：先把范例分析成 Style Card（写作规则摘要），再用 Style Card + 少量范例指导生成；没有 Style Card 时自动退回原文拼接。',
    };
    help.textContent = descriptions[mode] || descriptions.legacy;
    if (structured) {
        // 智能风格链推荐开启结构化消息，但仍允许用户手动控制
        structured.disabled = false;
        structured.closest('.switch-label').title = mode === 'smart'
            ? '智能风格链推荐开启结构化消息（规则/任务/素材拆成独立消息），你仍可手动切换'
            : '关闭时所有规则与素材拼成一段提示词发送（兼容旧格式）';
    }
}
