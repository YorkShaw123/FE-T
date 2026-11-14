/** Fixed workflow-canvas connectors. This is visual only; nodes are not draggable. */
import { $ } from './utils.js';

/** 基础连线：输入步骤汇聚到「生成初稿」，始终显示但只在对应输入有效时流动。 */
const BASE_CONNECTIONS = [
    [1, 4, 'horizontal'],
    [2, 4, 'horizontal'],
    [3, 4, 'horizontal'],
];

/** 后处理连线始终存在；开关只控制强调与流动状态，避免流程图结构跳变。 */
const POSTPROCESS_CONNECTIONS = [
    { from: 4, to: 5, key: 'deai', phase: 'deai' },
    { from: 4, to: 6, key: 'styleReference', phase: 'style' },
    { from: 5, to: 7, key: 'deai', phase: 'deai' },
    { from: 6, to: 7, key: 'styleReference', phase: 'style' },
];

/** 纯状态函数：输入节点连线采用与后处理一致的显示规则。 */
export function getBaseConnectionStates({
    promptOrchestrationEnabled = false,
    styleCardEnabled = false,
    contextEnabled = false,
    phase = '',
} = {}) {
    const enabledByStep = {
        1: promptOrchestrationEnabled,
        2: styleCardEnabled,
        3: contextEnabled,
    };
    return BASE_CONNECTIONS.map(([from, to, direction]) => {
        const enabled = !!enabledByStep[from];
        return { from, to, direction, enabled, flowing: enabled && phase === 'draft' };
    });
}

/** 纯状态函数供画布和运行态测试共用。 */
export function getPostProcessConnectionStates({
    deaiEnabled = false,
    styleReferenceEnabled = false,
    phase = '',
} = {}) {
    const enabledByKey = { deai: deaiEnabled, styleReference: styleReferenceEnabled };
    return POSTPROCESS_CONNECTIONS.map(connection => {
        const enabled = !!enabledByKey[connection.key];
        return { ...connection, enabled, flowing: enabled && phase === connection.phase };
    });
}

const NODE_EXPLANATIONS = {
    1: '决定模板和系统要求如何组织成模型能够理解的消息。结构化模式会把不同职责拆成独立消息。',
    2: '选择范例原文拼接或已分析的 Style Card。该节点只参与初稿提示词，不再加载大语料 RAG。',
    3: '补充已经写好的前文，让新生成内容承接已有情节、人物状态和叙述上下文。此步骤可以留空。',
    4: '汇总前三个输入节点，进行 Token 预算预检，然后调用当前选中的大语言模型生成第一版文章。初稿会直接显示在本步骤。',
    5: '可选的二次处理步骤，用于减少机械表达和模板化措辞。该节点负责开关和规则设置，处理后的内容统一显示在「07 最终成稿」。',
    6: '在初稿完成后从所选本地语料库检索 3～5 个风格片段，并最多进行一次受约束的风格参考重写。处理结果显示在「07 最终成稿」。',
    7: '汇总语言自然化/风格参考后的最终成稿，提供全屏编辑、复制与下载入口。仅启用对应后处理步骤时激活。',
};

function anchor(rect, canvasRect, side, scaleX, scaleY) {
    const x = side === 'left' ? rect.left : side === 'right' ? rect.right : rect.left + rect.width / 2;
    const y = side === 'top' ? rect.top : side === 'bottom' ? rect.bottom : rect.top + 47;
    return { x: (x - canvasRect.left) / scaleX, y: (y - canvasRect.top) / scaleY };
}

function curve(start, end, direction) {
    if (direction === 'vertical') {
        const bend = Math.max(34, Math.abs(end.y - start.y) * 0.5);
        return `M ${start.x} ${start.y} C ${start.x} ${start.y + bend}, ${end.x} ${end.y - bend}, ${end.x} ${end.y}`;
    }
    const sign = direction === 'reverse' ? -1 : 1;
    const bend = Math.max(32, Math.abs(end.x - start.x) * 0.5);
    return `M ${start.x} ${start.y} C ${start.x + bend * sign} ${start.y}, ${end.x - bend * sign} ${end.y}, ${end.x} ${end.y}`;
}

/** 读取当前「正在处理」的生成阶段（draft / deai / style / 空） */
function activePhase() {
    return document.body.dataset.flowPhase || '';
}

function inputStepEnabled(step) {
    if (step === 1) return !!($('#structured-prompt-enabled')?.checked);
    if (step === 2) {
        const mode = document.querySelector('input[name="workspace-style-mode"]:checked')?.value;
        return mode === 'smart';
    }
    if (step === 3) return !!($('#previous-article')?.value.trim());
    return false;
}

function syncNodeStates(canvas) {
    [1, 2, 3].forEach(step => {
        canvas.querySelector(`[data-step="${step}"]`)?.classList.toggle('is-enabled', inputStepEnabled(step));
    });
    const deaiEnabled = !!($('#deai-enabled')?.checked);
    const styleEnabled = !!($('#style-reference-enabled')?.checked);
    canvas.querySelector('[data-step="5"]')?.classList.toggle('is-enabled', deaiEnabled);
    canvas.querySelector('[data-step="6"]')?.classList.toggle('is-enabled', styleEnabled);
    canvas.querySelector('[data-step="7"]')?.classList.toggle('is-enabled', deaiEnabled || styleEnabled);
}

function renderConnections(canvas, svg) {
    const canvasRect = canvas.getBoundingClientRect();
    const width = canvas.scrollWidth;
    const height = canvas.scrollHeight;
    const scaleX = canvas.offsetWidth ? canvasRect.width / canvas.offsetWidth : 1;
    const scaleY = canvas.offsetHeight ? canvasRect.height / canvas.offsetHeight : scaleX;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('width', String(width));
    svg.setAttribute('height', String(height));

    const phase = activePhase();
    const paths = [];
    syncNodeStates(canvas);

    const buildPath = (from, to, direction, { enabled = true, flowing = false } = {}) => {
        const source = canvas.querySelector(`[data-step="${from}"]`);
        const target = canvas.querySelector(`[data-step="${to}"]`);
        if (!source || !target) return '';
        const startSide = direction === 'vertical' ? 'bottom' : direction === 'reverse' ? 'left' : 'right';
        const endSide = direction === 'vertical' ? 'top' : direction === 'reverse' ? 'right' : 'left';
        const start = anchor(source.getBoundingClientRect(), canvasRect, startSide, scaleX, scaleY);
        const end = anchor(target.getBoundingClientRect(), canvasRect, endSide, scaleX, scaleY);
        if (direction === 'vertical') end.x = start.x;
        const classes = [flowing && 'is-flowing', !enabled && 'is-disabled'].filter(Boolean);
        const classAttr = classes.length ? ` class="${classes.join(' ')}"` : '';
        return `<path${classAttr} d="${curve(start, end, direction)}" marker-end="url(#workflow-arrow)"/>`;
    };

    // 基础连线：初稿生成阶段（draft）时整体流动
    getBaseConnectionStates({
        promptOrchestrationEnabled: inputStepEnabled(1),
        styleCardEnabled: inputStepEnabled(2),
        contextEnabled: inputStepEnabled(3),
        phase,
    }).forEach(conn => {
        paths.push(buildPath(conn.from, conn.to, conn.direction, conn));
    });

    // 后处理连线始终显示；未启用时弱化，正在处理对应阶段时流动。
    getPostProcessConnectionStates({
        deaiEnabled: !!($('#deai-enabled')?.checked),
        styleReferenceEnabled: !!($('#style-reference-enabled')?.checked),
        phase,
    }).forEach(conn => {
        paths.push(buildPath(conn.from, conn.to, 'horizontal', conn));
    });

    svg.innerHTML = `<defs><marker id="workflow-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z"/></marker></defs>${paths.join('')}`;
}

export function initWorkflowCanvas() {
    const canvas = $('.generation-flow');
    const svg = $('#workflow-connections');
    if (!canvas || !svg) return;
    let frame = 0;
    const schedule = () => {
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => renderConnections(canvas, svg));
    };
    const observer = new ResizeObserver(schedule);
    observer.observe(canvas);
    canvas.querySelectorAll('.flow-node').forEach(node => observer.observe(node));
    window.addEventListener('resize', schedule);
    window.addEventListener('flora:zoom', schedule);
    // 生成阶段变化（初稿/去AI味/风格参考）时重绘连线，展示流动动画
    document.addEventListener('flora:flow-phase', schedule);
    // 后处理开关变化时更新对应步骤连线的强调状态
    document.addEventListener('change', event => {
        if (event.target.matches(
            '#structured-prompt-enabled, #deai-enabled, #style-reference-enabled, input[name="workspace-style-mode"]',
        )) schedule();
    });
    document.addEventListener('input', event => {
        if (event.target.matches('#previous-article')) schedule();
    });
    document.addEventListener('flora:workflow-input-change', schedule);

    const backdrop = $('#workflow-node-backdrop');
    const modal = $('#workflow-node-modal');
    const modalBody = $('#workflow-node-modal-body');
    const modalTitle = $('#workflow-node-modal-title');
    const modalSubtitle = $('#workflow-node-modal-subtitle');
    const modalExplanation = $('#workflow-node-modal-explanation');
    const modalClose = $('#workflow-node-modal-close');
    let activeNode = null;
    let activeDetails = null;
    const closeNode = () => {
        if (!activeNode) return;
        const closingNode = activeNode;
        closingNode.classList.remove('is-selected');
        closingNode.setAttribute('aria-expanded', 'false');
        if (activeDetails) closingNode.appendChild(activeDetails);
        activeNode = null;
        activeDetails = null;
        if (backdrop) backdrop.hidden = true;
        if (modal) modal.hidden = true;
        document.body.classList.remove('workflow-modal-open');
        closingNode.focus();
        schedule();
    };
    canvas.querySelectorAll('.flow-node').forEach(node => {
        const label = node.querySelector('.flow-node-label');
        const details = document.createElement('div');
        details.className = 'workflow-node-details';
        Array.from(node.children).filter(
            child => child !== label && !child.classList.contains('workflow-node-persistent'),
        ).forEach(child => details.appendChild(child));
        node.appendChild(details);
        node.setAttribute('role', 'button');
        node.setAttribute('tabindex', '0');
        node.setAttribute('aria-haspopup', 'dialog');
        node.setAttribute('aria-expanded', 'false');
        node.setAttribute('aria-label', `打开${node.querySelector('.flow-node-label strong')?.textContent || '流程节点'}详情`);
        const openNode = () => {
            if (activeNode || !modal || !modalBody) return;
            node.classList.remove('has-unread-result');
            activeNode = node;
            activeDetails = details;
            node.classList.add('is-selected');
            node.setAttribute('aria-expanded', 'true');
            modalTitle.textContent = label?.querySelector('strong')?.textContent || '流程节点';
            modalSubtitle.textContent = label?.querySelector('small')?.textContent || '';
            modalExplanation.textContent = NODE_EXPLANATIONS[node.dataset.step] || '';
            modalBody.appendChild(details);
            if (backdrop) backdrop.hidden = false;
            modal.hidden = false;
            modal.scrollTop = 0;
            document.body.classList.add('workflow-modal-open');
            modalClose?.focus();
        };
        node.addEventListener('click', event => {
            if (!event.target.closest('button, input, textarea, select, label, a')) openNode();
        });
        node.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                openNode();
            }
        });
    });
    backdrop?.addEventListener('click', event => {
        if (event.target === backdrop) closeNode();
    });
    modalClose?.addEventListener('click', closeNode);
    document.querySelectorAll('.nav-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            if (tab.dataset.tab !== 'workspace' && activeNode) closeNode();
        });
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && activeNode) closeNode();
    });
    schedule();
}
