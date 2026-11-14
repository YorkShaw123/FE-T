/**
 * Flora Editor - 通用工具函数
 * 提供 DOM 查询、API 请求、提示、HTML 转义等无状态的基础工具。
 */

/** 查询单个元素 */
export const $ = (sel, ctx) => (ctx || document).querySelector(sel);
/** 查询元素数组 */
export const $$ = (sel, ctx) => [...(ctx || document).querySelectorAll(sel)];

/** 统一 API 请求：合并请求头，并统一处理 HTTP、JSON 与业务错误。 */
export async function api(url, opts = {}) {
    const headers = new Headers(opts.headers || {});
    if (opts.body && !(opts.body instanceof FormData) && !headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json');
    }
    const response = await fetch(url, { ...opts, headers });
    const contentType = response.headers.get('content-type') || '';
    let data;
    if (contentType.includes('application/json')) {
        data = await response.json().catch(() => null);
    }
    if (!response.ok || !data?.success) {
        throw new Error(data?.error || `请求失败（HTTP ${response.status}）`);
    }
    return data;
}

/** 顶部轻提示；duration 为显示时长（毫秒），默认 3.5 秒 */
export function toast(msg, type = 'info', duration = 3500) {
    const container = $('#toast-container');
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => { el.remove(); }, duration);
}

/** 转义 HTML，防止 XSS */
export function escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

/** 安全绑定辅助函数：元素不存在时静默跳过 */
export function safeBind(selector, event, handler) {
    const el = typeof selector === 'string' ? $(selector) : selector;
    if (el) {
        el.addEventListener(event, handler);
    } else {
        console.warn('[Flora] 未找到元素:', selector);
    }
}

/** 简单段落格式化：将纯文本按行转换为 HTML 段落 */
export function formatArticle(text) {
    if (!text) return '<p style="color:var(--text-muted)">暂无内容</p>';
    // 简单的段落格式化
    return text
        .split('\n')
        .map(line => line.trim() ? `<p>${escapeHtml(line)}</p>` : '<br>')
        .join('');
}

/** 获取 DOM 元素的纯文本内容（去除渲染标记） */
export function getArticleText(element) {
    return (element.innerText || element.textContent || '').trim();
}

/** 将多行文本转为去空白的数组（用于风格卡/规则等换行输入的解析） */
export function linesToList(value) {
    return String(value || '').split('\n').map(item => item.trim()).filter(Boolean);
}
