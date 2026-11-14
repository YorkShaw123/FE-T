/**
 * Flora Editor - 界面缩放
 * 通过 CSS zoom 属性控制整个界面的显示比例（与浏览器原生缩放的实现方式一致）。
 * 提供工具栏按钮、快捷键（Ctrl/⌘ + ±/0）与 Ctrl+滚轮三种调节方式，
 * 缩放比例持久化到 localStorage，下次打开自动恢复。
 */
import { $ } from './utils.js';

/** 缩放范围与单步增量 */
const MIN_ZOOM = 0.8;
const MAX_ZOOM = 1.5;
const ZOOM_STEP = 0.1;
const ZOOM_KEY = 'flora_zoom';

/** 将值约束在缩放范围内 */
function clamp(value) {
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
}

/** 读取持久化的缩放比例，值非法时回退为 100% */
function loadZoom() {
    const raw = parseFloat(localStorage.getItem(ZOOM_KEY));
    return Number.isFinite(raw) ? clamp(raw) : 1;
}

/** 当前缩放比例（1 = 100%） */
let currentZoom = loadZoom();

/** 应用缩放比例：更新 body.zoom、控件文字并持久化 */
function applyZoom(zoom) {
    currentZoom = clamp(zoom);
    document.documentElement.style.setProperty('--ui-zoom', String(currentZoom));
    document.documentElement.style.setProperty('--ui-zoom-inverse', String(1 / currentZoom));
    document.body.style.zoom = String(currentZoom);
    // CSS media queries do not react to the CSS `zoom` property. Expose the
    // enlarged state so the header can switch to two rows before controls overlap.
    document.documentElement.toggleAttribute('data-ui-enlarged', currentZoom >= 1.2);
    window.dispatchEvent(new CustomEvent('flora:zoom', { detail: { zoom: currentZoom } }));
    const level = $('#zoom-reset');
    if (level) level.textContent = `${Math.round(currentZoom * 100)}%`;
    localStorage.setItem(ZOOM_KEY, String(currentZoom));
}

/** 按固定步长增减缩放 */
function stepZoom(delta) {
    applyZoom(currentZoom + delta);
}

/** 初始化缩放功能：恢复上次比例、绑定按钮与快捷键 */
export function initZoom() {
    // 恢复上次的缩放比例并同步控件显示
    applyZoom(currentZoom);

    $('#zoom-in').addEventListener('click', () => stepZoom(ZOOM_STEP));
    $('#zoom-out').addEventListener('click', () => stepZoom(-ZOOM_STEP));
    $('#zoom-reset').addEventListener('click', () => applyZoom(1));

    // 快捷键：Ctrl/⌘ + + / - / 0（覆盖浏览器默认缩放，统一走界面缩放）
    document.addEventListener('keydown', (e) => {
        if (!(e.ctrlKey || e.metaKey)) return;
        const key = e.key;
        if (key === '=' || key === '+') {
            e.preventDefault();
            stepZoom(ZOOM_STEP);
        } else if (key === '-' || key === '_') {
            e.preventDefault();
            stepZoom(-ZOOM_STEP);
        } else if (key === '0') {
            e.preventDefault();
            applyZoom(1);
        }
    });

    // Ctrl+滚轮：阻止 WebView2/浏览器原生缩放，避免与界面缩放叠加
    document.addEventListener('wheel', (e) => {
        if (!(e.ctrlKey || e.metaKey)) return;
        e.preventDefault();
        stepZoom(e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP);
    }, { passive: false });
}
