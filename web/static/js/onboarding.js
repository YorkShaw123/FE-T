import { $, api, toast } from './utils.js';

const PAGES = [
    {
        title: '欢迎来到雨生编辑器',
        html: `
            <p><strong>雨生编辑器把“设定、范例、文风”整理成一条生成链，用你选择的大模型把想法写成文章。</strong></p>
            <p>它是一款本地写作工具：模板负责保存设定，生成链负责组织提示词，文风功能负责对齐风格，成稿与生成记录都留在你的电脑里。</p>
            <p>不需要先学提示词工程。跟着下一页走，几分钟就能完成第一次生成。</p>`,
    },
    {
        title: '用示例完成第一次生成',
        html: `
            <ol>
                <li>打开<strong>模板管理</strong>，确认已有“示例人物：雨生”和“示例剧情：草木知春”（首次使用会自动生成，可修改或删除）。</li>
                <li>回到<strong>工作台</strong>，点左侧模板卡片上的圆点启用它们——亮起表示本次生成会用到。</li>
                <li>顶栏选好服务商和模型，填入对应的 API Key，点击<strong>生成文章</strong>。</li>
            </ol>
            <p>删除示例后想找回，可在模板列表点击<strong>生成示例模板</strong>；同名同类模板不会重复添加。</p>`,
    },
    {
        title: '怎样写一个好用的模板',
        html: `
            <p>模板就是可以反复使用的写作说明，按分类存放：</p>
            <ul>
                <li><strong>人物</strong>：身份、性格、说话方式、行为边界。</li>
                <li><strong>背景</strong>：时代、地点、世界观规则。</li>
                <li><strong>剧情</strong>：目标、冲突、转折、结局方向。</li>
                <li><strong>范例</strong>：一段代表你想要的文风的文章。</li>
                <li><strong>约束</strong>：其他任何“必须做 / 不要做”的要求。</li>
            </ul>
            <p>要求写得越具体越好。例如把“文笔好一点”改成“多用短句、少用成语、对话保留口语”。模板内容会按原文进入生成链，不需要特殊占位符。</p>
            <p>同一分类可保存多个模板，工作台只使用当前亮起的那些，方便按不同角色或剧情方案自由组合。</p>`,
    },
    {
        title: '选择模型并填写 API Key',
        html: `
            <p><strong>API Key 必须和顶栏选的服务商一致</strong>：DeepSeek 的密钥不能用于 OpenAI，硅基流动的密钥也不能用于 Kimi 官方接口。密钥只随当前请求发送，不写入数据库；重新打开应用后需再填一次。</p>
            <p>点击密钥框旁的 📂 按钮，可直接读取本机保存的 DeepSeek API Key（环境变量 <code>DEEPSEEK_API_KEY</code> 或密钥文件），省去手动输入。</p>
            <p>“思考模式”能否开启由模型能力决定。<strong>高级</strong>面板可调 temperature、top_p、max_tokens 等参数，不熟悉时保留默认值通常更稳妥。</p>
            <div class="onboarding-links">
                <button type="button" data-help-link="deepseek">DeepSeek API 文档 ↗</button>
                <button type="button" data-help-link="openai">OpenAI API 文档 ↗</button>
                <button type="button" data-help-link="moonshot">Kimi API 文档 ↗</button>
                <button type="button" data-help-link="qwen">通义千问 API 文档 ↗</button>
            </div>`,
    },
    {
        title: '看懂工作台生成链',
        html: `
            <p>工作台是一条生成流水线：<strong>01 提示词编排、02 风格卡、03 上下文输入</strong>准备素材 → <strong>04 生成初稿</strong> →（可选）<strong>05 语言自然化、06 风格参考</strong>二次处理 → <strong>07 最终成稿</strong>。</p>
            <p>没有启用的节点不会参与处理；生成中的节点会转圈并流动。右侧<strong>提示词预览</strong>可先查看完整提示词与 Token 预算，不会调用 AI。</p>
            <p>05、06 都关闭时，04 的初稿就是最终结果；开启任一处理后，处理完成的版本进入 07。点击 04 或 07 节点才展开正文，避免长文章挤乱画布。</p>`,
    },
    {
        title: '风格卡与文风语料的区别',
        html: `
            <p>两者都能帮你对齐文风，区别在于素材规模和用法：</p>
            <ul>
                <li><strong>风格卡</strong>：从“范例文章”模板生成。系统先概括范例的视角、节奏和用词习惯，再把规则加进初稿提示词，适合少量参考文章。</li>
                <li><strong>文风语料</strong>：在“文风管理”导入成批 TXT、DOC 或 DOCX。开启 06 后，系统从语料库检索 3～5 段风格相近片段，只参考其语言组织，不复制人物、地点和剧情。</li>
            </ul>
            <p>句式、标点等分析在本机完成；没装语义模型时检索会自动降级，不影响使用。请只导入你有权使用的文本，最终成稿仍需自己阅读把关。</p>`,
    },
    {
        title: '自然化、风格参考与结果编辑',
        html: `
            <p><strong>语言自然化</strong>：把初稿按你的要求再生成一版，去掉“AI 腔”。建议写清楚要修什么、不能改什么（如剧情、人物关系）。</p>
            <p><strong>风格参考</strong>：用选中的语料库检索片段后做一次受约束改写；弹窗会展示实际采用的片段，方便判断检索是否合理。</p>
            <p>二次处理都会增加耗时与 Token 消耗，初稿满意时可以关掉。之后可进入全屏编辑器继续<strong>续写、重写、扩写、润色</strong>或比较版本；<strong>生成记录</strong>保存在本机，可置顶、删除、清空。</p>`,
    },
    {
        title: '本地数据、模型与故障排查',
        html: `
            <ul>
                <li><strong>数据</strong>：模板、文风索引和生成记录保存在 <code>%USERPROFILE%\.flora-editor\data\flora.db</code>，卸载默认保留；彻底清理前请先备份。</li>
                <li><strong>模型</strong>：本地 Embedding 模型在 <code>%USERPROFILE%\.flora-editor\models\</code>，需联网下载一次；没有它也能用纯本地文风检索。</li>
                <li><strong>桌面版</strong>：<code>雨生编辑器.exe</code> 与 <code>flora-server.exe</code> 必须放在同一目录。启动超时先检查文件是否齐全、杀毒软件是否拦截后端。</li>
                <li><strong>开发模式</strong>：浏览器入口只监听 <code>127.0.0.1</code>，仅用于本机调试，不是可公开访问的 Web 服务。</li>
            </ul>`,
    },
    {
        title: '官方文档与提示词入口',
        html: `
            <p>以下按钮会用系统默认浏览器打开固定官方地址（不会把任意网址交给后端）。服务商页面可能改版，请以其最新说明为准。</p>
            <div class="onboarding-links">
                <button type="button" data-help-link="zhipu">智谱 GLM 文档 ↗</button>
                <button type="button" data-help-link="gemini">Google Gemini 文档 ↗</button>
                <button type="button" data-help-link="xai">xAI Grok 文档 ↗</button>
                <button type="button" data-help-link="siliconflow">硅基流动文档 ↗</button>
                <button type="button" data-help-link="aishort">AiShort 社区提示词 ↗</button>
            </div>
            <p>社区提示词只作灵感参考：使用前检查是否含过时或不安全的内容，也不要往社区页面粘贴 API Key、私人语料或未公开作品。</p>
            <p>以后想再看这些说明，随时点击工作台右上角的<strong>帮助</strong>按钮。</p>`,
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
    page.addEventListener('click', async event => {
        const linkButton = event.target.closest('[data-help-link]');
        if (!linkButton) return;
        linkButton.disabled = true;
        try {
            await api(`/api/system/open-help-link/${encodeURIComponent(linkButton.dataset.helpLink)}`, {
                method: 'POST',
            });
        } catch (error) {
            toast(`打开帮助链接失败：${error.message}`, 'error');
        } finally {
            linkButton.disabled = false;
        }
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
