import { $ } from './utils.js';

const PAGES = [
    {
        title: '先认识工作台',
        html: `
            <p>工作台把一次文章生成画成一条流程。你只需要从左向右看：</p>
            <ol>
                <li><strong>提示词编排</strong>：决定怎样把模板和要求交给模型。</li>
                <li><strong>文风参考</strong>：选择原文范例或本地文风语料。</li>
                <li><strong>上下文输入</strong>：放入已经写好的前文，保持剧情连续。</li>
                <li><strong>生成初稿</strong>：检查标题和 Token 预算。</li>
                <li><strong>语言自然化、文风校正</strong>：都是可选的后处理。</li>
                <li><strong>最终成稿</strong>：查看、编辑、复制或下载文章。</li>
            </ol>`,
    },
    {
        title: '模板管理是做什么的？',
        html: `
            <p>模板就是可以重复使用的提示词。人物、背景、剧情、范例文章和其他约束可以分开保存。</p>
            <p>模板中的 <code>{{变量名}}</code> 会在工作台变成输入项。工作台左侧可以直接开启或关闭某个模板。</p>
            <p>新手建议：先准备一个人物模板、一个背景模板和一个剧情模板，再回到工作台生成。</p>`,
    },
    {
        title: '文风管理是做什么的？',
        html: `
            <p>文风管理用于导入 TXT 或 DOCX 参考语料，并在本机分析作者的句长、标点和功能词习惯。</p>
            <p>建立索引后，工作台的“智能风格链”会挑选少量合适片段作为写作参考。它主要学习表达习惯，不应复制原文剧情。</p>
            <p>“检索测试与评分调试”只用于检查为什么命中某些片段，普通使用时可以保持折叠。</p>`,
    },
    {
        title: 'API 密钥、模型和思考模式',
        html: `
            <p><strong>API 密钥</strong>让 Flora 调用你选择的大模型。密钥只在本次使用时输入，不保存到项目数据库。</p>
            <p><strong>提供商和模型</strong>必须与密钥所属平台一致；不同平台的密钥不能混用。</p>
            <p><strong>思考模式</strong>只在模型本身支持时可用，通常更慢，也可能消耗更多 Token。</p>
            <div class="onboarding-links">
                <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">OpenAI API Key</a>
                <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener noreferrer">DeepSeek API Key</a>
                <a href="https://platform.moonshot.cn/console/api-keys" target="_blank" rel="noopener noreferrer">Kimi API Key</a>
                <a href="https://cloud.siliconflow.cn/account/ak" target="_blank" rel="noopener noreferrer">硅基流动 API Key</a>
            </div>`,
    },
    {
        title: '生成之后去哪里？',
        html: `
            <p>生成中的状态会显示在“最终成稿”节点。完成后，点击该节点即可查看文章。</p>
            <p><strong>生成记录</strong>保存过去的生成结果；<strong>全屏编辑</strong>可以继续修改、局部续写或比较版本。</p>
            <p>右侧“提示词预览”可以在调用模型前检查最终提示词和 Token 预算。右下角按钮用于主题与界面缩放。</p>
            <p>以后需要重新查看这份介绍时，点击“文章生成链路”右侧的“帮助”。</p>`,
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
