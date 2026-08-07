/**
 * Forestar Editor - 工作台风格设置
 * 负责风格模式（legacy/smart/off）与风格强度（light/medium/strict）的读取与提示更新。
 */
import { $ } from './utils.js';

/** 读取当前风格强度 */
export function getWorkspaceStyleStrength() {
    return $('input[name="workspace-style-strength"]:checked')?.value || 'light';
}

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
        off: '本次生成不发送任何“范例文章/参考风格”模板。',
    };
    help.textContent = descriptions[mode];
    if (structured) {
        // 智能风格链推荐开启结构化消息，但仍允许用户手动控制
        structured.disabled = false;
        structured.closest('.switch-label').title = mode === 'smart'
            ? '智能风格链推荐开启结构化消息，你仍可手动切换'
            : '关闭时完整使用原有字符串拼装格式';
    }
    const sceneControl = $('#style-scene-control');
    if (sceneControl) sceneControl.style.display = mode === 'smart' ? '' : 'none';
}

/** 根据风格强度更新说明文案 */
export function updateWorkspaceStyleStrengthHelp() {
    const help = $('#style-strength-help');
    if (!help) return;
    const descriptions = {
        light: '保持模板原有位置，不额外增加风格约束。',
        medium: '风格模板将移至前置文章之后，并要求正文明显贴近参考风格。',
        strict: '风格模板将移至前置文章之后，并作为本次写作的优先执行标准。',
    };
    help.textContent = descriptions[getWorkspaceStyleStrength()];
}
