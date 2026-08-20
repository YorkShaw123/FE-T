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
        legacy: '沿用当前范例文章拼接逻辑，不改变任何原有行为。',
        smart: '使用有效 Style Card 和少量代表性范例；缺少风格卡时自动回退原文拼接。',
    };
    help.textContent = descriptions[mode] || descriptions.legacy;
    if (structured) {
        // 智能风格链推荐开启结构化消息，但仍允许用户手动控制
        structured.disabled = false;
        structured.closest('.switch-label').title = mode === 'smart'
            ? '智能风格链推荐开启结构化消息，你仍可手动切换'
            : '关闭时完整使用原有字符串拼装格式';
    }
}
