import { $ } from './utils.js';

const PAGES = [
    {
        title: '欢迎来到 Flora Editor',
        html: `
            <p><strong>Flora Editor 会把你准备的人物、世界、剧情和文风要求整理成一条清楚的生成链，陪你把一个想法写成可以继续打磨的文章。</strong></p>
            <p>你不需要先弄懂复杂的提示词工程。准备好想写的内容，选择模型，Flora 会在每一步告诉你正在做什么。</p>`,
    },
    {
        title: '第一次生成，只要三步',
        html: `
            <ol>
                <li>到<strong>模板管理</strong>写下人物、背景、剧情或其他要求，并保存模板。</li>
                <li>回到工作台，在左侧开启本次要用的模板；在顶栏选择模型并输入对应平台的 API 密钥。</li>
                <li>点击<strong>生成文章</strong>。标题、提示词编排、风格卡和前置文章都可以按需要再补充。</li>
            </ol>
            <p>模板就是可重复使用的写作说明。内容写清楚即可，不需要特殊占位符。</p>`,
    },
    {
        title: '看懂工作台生成链',
        html: `
            <p><strong>01 提示词编排、02 风格卡、03 上下文输入</strong>共同准备初稿所需信息，然后进入<strong>04 生成初稿</strong>。</p>
            <p><strong>05 语言自然化</strong>和<strong>06 风格参考</strong>都是可选的二次处理。开启后，它们会在初稿完成之后继续修改，而不是混进第一次生成。</p>
            <p>初稿显示在 04，二次处理后的版本显示在<strong>07 最终成稿</strong>。节点里的转圈提示和流动连线表示当前正在执行的步骤。</p>`,
    },
    {
        title: '风格卡与文风语料有什么不同？',
        html: `
            <p><strong>风格卡</strong>来自“范例文章”模板，是一份对表达习惯的概括；启用智能风格链后，它参与初稿提示词。</p>
            <p><strong>文风语料</strong>在“文风管理”中导入。开启 06 后，系统会在初稿完成后从所选语料库检索 3～5 个真实片段，再做一次受约束的风格改写。</p>
            <p>两者可以单独使用，也可以配合使用。语义向量是可选辅助；缺少本地模型时，文风检索仍会降级到纯本地 Style Engine。</p>`,
    },
    {
        title: '模型、预览与生成结果',
        html: `
            <p><strong>API 密钥</strong>只随本次请求使用，不写入数据库。密钥、提供商和模型必须来自同一个平台；“高级”可以调整常用采样参数。</p>
            <p>右侧<strong>提示词预览</strong>用于生成前检查初稿提示词和 Token 预算，不会调用 AI。生成时，04 显示初稿进度；若开启自然化或风格参考，07 会继续显示处理进度。</p>
            <p>完成后点击 04 或 07 查看正文。<strong>生成记录</strong>会保存结果，<strong>全屏编辑</strong>可继续修改、续写或比较版本。</p>
            <p>需要再次查看介绍时，点击“文章生成链路”右侧的<strong>帮助</strong>。</p>`,
    },
];

export function initOnboarding() {
    const backdrop = $('#onboarding-backdrop');
    const dialog = $('#onboarding-dialog');
    const helpButton = $('#btn-open-onboarding');
    const title = $('#onboarding-title');
    const page = $('#onboarding-page');
    const progress = $('#onboarding-progress');
    const previous = $('#btn-prev-onboarding');
    const next = $('#btn-next-onboarding');
    const cancel = $('#btn-cancel-onboarding');
    const close = $('#btn-close-onboarding');
    if (!backdrop || !dialog || !helpButton || !title || !page || !progress || !previous || !next) return;

    let pageIndex = 0;
    let closeTimer = null;

    const render = () => {
        const current = PAGES[pageIndex];
        title.textContent = current.title;
        page.innerHTML = current.html;
        progress.textContent = `${pageIndex + 1} / ${PAGES.length}`;
        previous.disabled = pageIndex === 0;
        next.textContent = pageIndex === PAGES.length - 1 ? '开始使用' : '下一页';
        page.scrollTop = 0;
    };

    const open = () => {
        if (closeTimer) window.clearTimeout(closeTimer);
        pageIndex = 0;
        render();
        backdrop.hidden = false;
        backdrop.classList.remove('is-closing');
        document.body.classList.add('onboarding-open');
        window.requestAnimationFrame(() => backdrop.classList.add('is-open'));
        close.focus();
    };

    const finishClose = () => {
        backdrop.hidden = true;
        backdrop.classList.remove('is-open', 'is-closing');
        dialog.style.removeProperty('--onboarding-target-x');
        dialog.style.removeProperty('--onboarding-target-y');
        document.body.classList.remove('onboarding-open');
        helpButton.focus();
    };

    const closeToHelp = () => {
        if (backdrop.hidden || backdrop.classList.contains('is-closing')) return;
        const dialogRect = dialog.getBoundingClientRect();
        const targetRect = helpButton.getBoundingClientRect();
        dialog.style.setProperty('--onboarding-target-x', `${targetRect.left + targetRect.width / 2 - (dialogRect.left + dialogRect.width / 2)}px`);
        dialog.style.setProperty('--onboarding-target-y', `${targetRect.top + targetRect.height / 2 - (dialogRect.top + dialogRect.height / 2)}px`);
        backdrop.classList.add('is-closing');
        backdrop.classList.remove('is-open');
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
            finishClose();
            return;
        }
        closeTimer = window.setTimeout(finishClose, 360);
    };

    previous.addEventListener('click', () => {
        if (pageIndex > 0) pageIndex -= 1;
        render();
    });
    next.addEventListener('click', () => {
        if (pageIndex < PAGES.length - 1) {
            pageIndex += 1;
            render();
            return;
        }
        closeToHelp();
    });
    cancel?.addEventListener('click', closeToHelp);
    close?.addEventListener('click', closeToHelp);
    helpButton.addEventListener('click', open);
    backdrop.addEventListener('click', event => {
        if (event.target === backdrop) closeToHelp();
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && !backdrop.hidden) closeToHelp();
    });

    open();
}
