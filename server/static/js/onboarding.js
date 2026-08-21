import { $, api, toast } from './utils.js';

const PAGES = [
    {
        title: '欢迎来到雨生编辑器',
        html: `
            <p><strong>雨生编辑器会把人物、世界、剧情和文风要求整理成一条看得见的生成链，陪你把零散想法写成可以继续打磨的文章。</strong></p>
            <p>它不会替你决定故事，而是帮助你保存设定、组合写作要求、调用你选择的大模型，并把初稿与修改结果留在本机。</p>
            <p>你不需要先学会复杂的提示词工程。第一次使用时，可以直接启用自带的“雨生”和“草木知春”两个案例模板，填写 API 密钥后开始生成。</p>`,
    },
    {
        title: '用示例完成第一次生成',
        html: `
            <ol>
                <li>打开<strong>模板管理</strong>，查看“示例人物：雨生”和“示例剧情：草木知春”。它们是普通模板，可以修改或删除。</li>
                <li>回到<strong>工作台</strong>，点击左侧模板卡片启用它们。圆点亮起表示本次生成会使用该模板。</li>
                <li>在顶栏选择服务商和模型，填入该平台签发的 API Key，再点击<strong>生成文章</strong>。</li>
            </ol>
            <P></P>
            <p>这两个示例只在首次使用时自动加入。删除后不会自行恢复；需要重新体验时，可在模板列表上方点击<strong>生成示例模板</strong>。已有同名同类模板不会重复添加。</p>`,
    },
    {
        title: '怎样写一个好用的模板',
        html: `
            <p>模板是可以反复使用的写作说明。人物模板适合写身份、性格、关系和行为边界；背景模板写时代、地点与规则；剧情模板写目标、冲突、转折和结局方向。</p>
            <p>尽量写清楚“必须保留什么”和“不要出现什么”，避免只写“写得好一点”这类模糊要求。模板内容会按原文进入生成链，不需要特殊占位符。</p>
            <p>同一分类可以保存多个模板。工作台只会使用当前亮起的模板，因此你可以保存不同角色或剧情方案，按本次创作需要组合。</p>
            <p>需要寻找提示词灵感时，可从模板编辑器或帮助页打开 AiShort 社区；请在使用社区内容前自行检查其适用范围与安全性。</p>`,
    },
    {
        title: '选择模型并填写 API Key',
        html: `
            <p>API Key 必须来自当前选择的服务商，不能把 DeepSeek 的密钥用于 OpenAI，也不能把硅基流动密钥用于 Kimi 官方接口。密钥只随当前请求发送，不写入数据库。</p>
            <p>“思考模式”是否能开启由模型能力决定。“高级”面板可调整 temperature、top_p、max_tokens 等参数；不熟悉时保留默认值通常更稳妥。</p>
            <p>模型名称、价格、上下文长度和参数支持可能由厂商调整。遇到鉴权或参数错误时，应先查看当前厂商官方文档。</p>
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
            <p><strong>01 提示词编排、02 风格卡、03 上下文输入</strong>共同准备初稿信息，然后进入<strong>04 生成初稿</strong>。没有启用的节点不会参与处理。</p>
            <p>右侧<strong>提示词预览</strong>用于生成前核对初稿提示词与 Token 预算，不会调用 AI。内容很多时会显示加载状态，等待预览稳定后再检查即可。</p>
            <p><strong>05 语言自然化</strong>和<strong>06 风格参考</strong>是初稿完成后的可选二次处理。节点转圈和流动虚线表示当前正在执行；生成完成后点击 04 或 07 才会展开正文，避免长文章挤乱画布。</p>
            <p>如果 05 和 06 都未开启，04 的初稿就是本次结果；开启任一处理后，处理完成的版本会进入<strong>07 最终成稿</strong>。</p>`,
    },
    {
        title: '风格卡与文风语料的区别',
        html: `
            <p><strong>风格卡</strong>来自“范例文章”模板。系统先概括范例的视角、节奏和语言习惯，再把这些要求加入初稿提示词，适合少量参考文章。</p>
            <p><strong>文风语料</strong>在“文风管理”中导入，适合较大的 TXT、DOC 或 DOCX 文本。开启 06 后，系统在初稿完成后检索 3～5 个片段，并要求模型只参考语言组织，不复制人物、地点和剧情。</p>
            <p>Style Engine 的句长、标点和功能词分析在本机完成。语义向量只是辅助；本地 ONNX 模型未安装时，检索会自动降级，不会让整个功能失效。</p>
            <p>请只导入你有权使用的文本。任何自动分数都不能等同于人工判断，最终仍建议自己阅读并修改成稿。</p>`,
    },
    {
        title: '自然化、风格参考与结果编辑',
        html: `
            <p><strong>语言自然化</strong>会读取初稿和你填写的修改要求，再调用一次模型。提示词应说明要修正的语言问题，同时明确保持剧情、事实和人物关系。</p>
            <p><strong>风格参考</strong>会使用文风管理中选中的语料库检索片段，再做一次受约束改写。弹窗会显示实际采用的参考片段，便于判断检索是否合理。</p>
            <p>每次额外处理都会增加 API 时间和 Token 消耗。若初稿已经满意，可以关闭二次处理。完成后可进入全屏编辑器继续续写、重写、扩写、润色或比较版本。</p>
            <p><strong>生成记录</strong>保存在本机，可置顶、删除或清空；API 中断时，系统可能保留未完成内容，方便你判断是否续写。</p>`,
    },
    {
        title: '本地数据、模型与故障排查',
        html: `
            <p>模板、文风索引和生成记录默认保存在 <code>%USERPROFILE%\.flora-editor\data\flora.db</code>。卸载程序默认保留这些数据，彻底清理前请先备份。</p>
            <p>本地 Embedding 模型保存在 <code>%USERPROFILE%\.flora-editor\models\</code>，不会塞进 SQLite。下载模型需要联网，但没有模型时仍可使用不含语义辅助的本地文风检索。</p>
            <p>桌面版由“雨生编辑器.exe”和“flora-server.exe”共同运行，两者必须处于同一目录。启动超时或双击无反应时，请检查文件是否齐全，以及杀毒软件是否拦截后端。</p>
            <p>开发浏览器入口只监听 <code>127.0.0.1</code>。它用于本机调试，不是可公开访问的 Web 服务。</p>`,
    },
    {
        title: '官方文档与提示词入口',
        html: `
            <p>下面的按钮会调用系统默认浏览器打开固定官方地址，不会把任意网址交给后端。服务商页面可能改版，请以其最新说明、价格和模型列表为准。</p>
            <div class="onboarding-links">
                <button type="button" data-help-link="zhipu">智谱 GLM 文档 ↗</button>
                <button type="button" data-help-link="gemini">Google Gemini 文档 ↗</button>
                <button type="button" data-help-link="xai">xAI Grok 文档 ↗</button>
                <button type="button" data-help-link="siliconflow">硅基流动文档 ↗</button>
                <button type="button" data-help-link="aishort">AiShort 社区提示词 ↗</button>
            </div>
            <P></P>
            <p>社区提示词只能作为灵感来源。复制前请检查是否包含与你的任务无关、过时或不安全的要求，也不要在社区页面粘贴 API Key、私人语料或未公开作品。</p>
            <p>以后需要重看这些说明，随时点击工作台标题右侧的<strong>帮助</strong>按钮。</p>`,
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
