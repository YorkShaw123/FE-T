/** Fixed workflow-canvas connectors. This is visual only; nodes are not draggable. */
import { $ } from './utils.js';

const CONNECTIONS = [
    [1, 4, 'horizontal'],
    [2, 4, 'horizontal'],
    [3, 4, 'horizontal'],
    [4, 5, 'horizontal'],
    [4, 6, 'horizontal'],
    [5, 7, 'horizontal'],
    [6, 7, 'horizontal'],
];

const NODE_EXPLANATIONS = {
    1: '决定模板、变量和系统要求如何组织成模型能够理解的消息。结构化模式会把不同职责拆成独立消息。',
    2: '选择参考文风的来源与强度。智能风格链会结合本地语料检索结果，但不会改变文章事实和剧情要求。',
    3: '补充已经写好的前文，让新生成内容承接已有情节、人物状态和叙述上下文。此步骤可以留空。',
    4: '汇总前三个输入节点，进行 Token 预算预检，然后调用当前选中的大语言模型生成第一版文章。',
    5: '可选的二次处理步骤，用于减少机械表达和模板化措辞。只有启用后才会增加对应的 API 调用。',
    6: '使用本地 Style Analyzer 对比目标作者画像；偏差明显且用户启用时，最多进行一次文风重写。',
    7: '集中查看本次生成的初稿、自然化版本和严格文风终稿，并提供全屏编辑、复制与下载入口。',
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

function renderConnections(canvas, svg) {
    const canvasRect = canvas.getBoundingClientRect();
    const width = canvas.scrollWidth;
    const height = canvas.scrollHeight;
    const scaleX = canvas.offsetWidth ? canvasRect.width / canvas.offsetWidth : 1;
    const scaleY = canvas.offsetHeight ? canvasRect.height / canvas.offsetHeight : scaleX;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('width', String(width));
    svg.setAttribute('height', String(height));

    const paths = CONNECTIONS.map(([from, to, direction]) => {
        const source = canvas.querySelector(`[data-step="${from}"]`);
        const target = canvas.querySelector(`[data-step="${to}"]`);
        if (!source || !target) return '';
        const startSide = direction === 'vertical' ? 'bottom' : direction === 'reverse' ? 'left' : 'right';
        const endSide = direction === 'vertical' ? 'top' : direction === 'reverse' ? 'right' : 'left';
        const start = anchor(source.getBoundingClientRect(), canvasRect, startSide, scaleX, scaleY);
        const end = anchor(target.getBoundingClientRect(), canvasRect, endSide, scaleX, scaleY);
        if (direction === 'vertical') end.x = start.x;
        return `<path d="${curve(start, end, direction)}" marker-end="url(#workflow-arrow)"/>`;
    }).join('');

    svg.innerHTML = `<defs><marker id="workflow-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z"/></marker></defs>${paths}`;
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
            child => child !== label && !child.classList.contains('flow-node-persistent'),
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
