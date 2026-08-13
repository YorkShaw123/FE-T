"""
应用配置模块
集中管理所有配置项，方便维护和修改
"""
import os

# 项目根目录（server/ 的上级）；兼容旧版项目内 data/ 数据库位置。
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


class Config:
    """基础配置"""
    # 未显式配置时由应用工厂为每个进程生成随机密钥，避免发布包共享固定密钥。
    SECRET_KEY = os.environ.get('SECRET_KEY', '')

    # 构建数据库URI（使用正斜杠确保跨平台兼容）
    _db_path = os.path.join(BASE_DIR, 'data', 'forestar.db').replace('\\', '/')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{_db_path}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'connect_args': {'timeout': 30},
    }
    JSON_AS_ASCII = False
    # 上传上限 20MB：支持百万字级风格语料一次性导入（中文 UTF-8 约 3 字节/字）
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024

    # 前置文章自动压缩阈值（字符数），超过此长度自动压缩
    PREVIOUS_ARTICLE_COMPRESS_THRESHOLD = 30000
    PREVIOUS_ARTICLE_SUMMARY_LENGTH = 800
    LLM_TIMEOUT_SECONDS = 180
    LLM_MAX_RETRIES = 2
    DEFAULT_MAX_TOKENS = 8192
    DEFAULT_CONTEXT_WINDOW = 65536
    TOKEN_BUDGET_SAFETY_TOKENS = 2048
    TOKEN_BUDGET_WARNING_RATIO = 0.85
    TOKEN_ESTIMATE_SAFETY_FACTOR = 1.15
    CHAT_MESSAGE_OVERHEAD_TOKENS = 8
    GENERATION_SYSTEM_PROMPT = (
        '你是一名严谨的中文创作助手。严格遵守用户提供的设定与约束；'
        '占位符若未填写，不得自行编造对应事实；只输出成稿，不解释写作过程。'
    )

    # ---- Style RAG：Embedding 向量化配置 ----
    # 走硅基流动 OpenAI 兼容 embeddings 端点（BAAI/bge-m3，1024 维），
    # 不引入本地向量库，保持 PyInstaller 打包体积可控。
    EMBEDDING_PROVIDER = 'siliconflow'
    EMBEDDING_MODEL = 'BAAI/bge-m3'
    EMBEDDING_DIMENSIONS = 1024
    EMBEDDING_BATCH_SIZE = 16
    # 桌面端资源保护：限制单库规模和检索候选，避免一次性矩阵占用过多内存。
    STYLE_CORPUS_MAX_CHUNKS = 5000
    STYLE_SEARCH_MAX_CANDIDATES = 5000

    # 支持的大语言模型配置
    LLM_PROVIDERS = {
        'deepseek': {
            'name': 'DeepSeek（深度求索）',
            'base_url': 'https://api.deepseek.com',
            'thinking_protocol': 'thinking_object_with_effort',
            'models': [
                {
                    'id': 'deepseek-v4-flash',
                    'name': 'DeepSeek V4 Flash',
                    'description': '快速响应的轻量级模型',
                    'supports_thinking': True,
                    'thinking_mode': 'switchable',
                    'context_window': 1048576,
                },
                {
                    'id': 'deepseek-v4-pro',
                    'name': 'DeepSeek V4 Pro',
                    'description': '高质量深度推理模型',
                    'supports_thinking': True,
                    'thinking_mode': 'switchable',
                    'context_window': 1048576,
                },
            ],
        },
        'openai': {
            'name': 'OpenAI',
            'base_url': 'https://api.openai.com/v1',
            'models': [
                {
                    'id': 'gpt-4.1',
                    'name': 'GPT-4.1',
                    'description': '擅长指令遵循与长文本处理',
                    'supports_thinking': False,
                    'context_window': 1047576,
                },
                {
                    'id': 'gpt-4o',
                    'name': 'GPT-4o',
                    'description': 'OpenAI 旗舰多模态模型',
                    'supports_thinking': False,
                    'context_window': 128000,
                },
                {
                    'id': 'gpt-4o-mini',
                    'name': 'GPT-4o Mini',
                    'description': '轻量高效的OpenAI模型',
                    'supports_thinking': False,
                    'context_window': 128000,
                },
            ],
        },
        'siliconflow': {
            'name': '硅基流动（Kimi / Embedding）',
            'base_url': 'https://api.siliconflow.com/v1',
            'thinking_protocol': 'enable_thinking',
            'models': [
                {
                    'id': 'moonshotai/Kimi-K2.6',
                    'name': 'Kimi K2.6',
                    'description': 'Kimi 新一代高质量模型',
                    'supports_thinking': True,
                    'thinking_mode': 'switchable',
                    'context_window': 262144,
                },
                {
                    'id': 'moonshotai/Kimi-K2.5',
                    'name': 'Kimi K2.5',
                    'description': '适合长文本创作与复杂任务',
                    'supports_thinking': True,
                    'thinking_mode': 'switchable',
                    'context_window': 262144,
                },
                {
                    'id': 'moonshotai/Kimi-K2-Thinking',
                    'name': 'Kimi K2 Thinking',
                    'description': '固定使用深度思考的推理模型',
                    'supports_thinking': True,
                    'thinking_mode': 'always',
                    'context_window': 131072,
                },
                {
                    'id': 'moonshotai/Kimi-K2-Instruct-0905',
                    'name': 'Kimi K2 Instruct 0905',
                    'description': '稳定的指令遵循模型',
                    'supports_thinking': False,
                    'thinking_mode': 'disabled',
                    'context_window': 131072,
                },
                {
                    'id': 'moonshotai/Kimi-K2-Instruct',
                    'name': 'Kimi K2 Instruct',
                    'description': '通用指令模型',
                    'supports_thinking': False,
                    'thinking_mode': 'disabled',
                    'context_window': 131072,
                },
            ],
        },
        'moonshot': {
            'name': 'Kimi（月之暗面官方）',
            'base_url': 'https://api.moonshot.cn/v1',
            'thinking_protocol': 'thinking_object',
            'models': [
                {
                    'id': 'kimi-k2.6',
                    'name': 'Kimi K2.6',
                    'description': '月之暗面官方长文本旗舰模型',
                    'supports_thinking': True,
                    'thinking_mode': 'switchable',
                    'context_window': 262144,
                },
                {
                    'id': 'kimi-k2.5',
                    'name': 'Kimi K2.5',
                    'description': '兼顾创作质量与复杂推理',
                    'supports_thinking': True,
                    'thinking_mode': 'switchable',
                    'context_window': 262144,
                },
            ],
        },
        'qwen': {
            'name': '通义千问（阿里云百炼）',
            'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'models': [
                {
                    'id': 'qwen-plus',
                    'name': 'Qwen Plus',
                    'description': '通用能力、效果与成本均衡',
                    'supports_thinking': False,
                    'context_window': 131072,
                },
                {
                    'id': 'qwen-turbo',
                    'name': 'Qwen Turbo',
                    'description': '速度优先的轻量文本模型',
                    'supports_thinking': False,
                    'context_window': 131072,
                },
            ],
        },
        'zhipu': {
            'name': '智谱 GLM',
            'base_url': 'https://open.bigmodel.cn/api/paas/v4',
            'thinking_protocol': 'thinking_object',
            'models': [
                {
                    'id': 'glm-4.7',
                    'name': 'GLM-4.7',
                    'description': '智谱高智能长文本模型',
                    'supports_thinking': True,
                    'thinking_mode': 'switchable',
                    'context_window': 204800,
                },
                {
                    'id': 'glm-4.7-flashx',
                    'name': 'GLM-4.7 FlashX',
                    'description': '低延迟版本',
                    'supports_thinking': True,
                    'thinking_mode': 'switchable',
                    'context_window': 204800,
                },
            ],
        },
        'gemini': {
            'name': 'Google Gemini（官方）',
            'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai',
            'thinking_protocol': 'gemini_effort',
            'models': [
                {
                    'id': 'gemini-2.5-pro',
                    'name': 'Gemini 2.5 Pro',
                    'description': '高质量深度推理模型（内置思考，不可关闭）',
                    'supports_thinking': True,
                    'thinking_mode': 'always',
                    'context_window': 1048576,
                },
                {
                    'id': 'gemini-2.5-flash',
                    'name': 'Gemini 2.5 Flash',
                    'description': '快速响应的轻量推理模型',
                    'supports_thinking': True,
                    'thinking_mode': 'switchable',
                    'context_window': 1048576,
                },
            ],
        },
        'xai': {
            'name': 'xAI Grok',
            'base_url': 'https://api.x.ai/v1',
            'models': [
                {
                    'id': 'grok-4.3',
                    'name': 'Grok 4.3',
                    'description': 'xAI 官方通用旗舰模型',
                    'supports_thinking': False,
                    'context_window': 262144,
                },
            ],
        },
    }

    # 模板分类定义
    TEMPLATE_CATEGORIES = [
        {'id': 'character', 'name': '人物设定', 'icon': '👤', 'order': 1},
        {'id': 'background', 'name': '背景设定', 'icon': '🌍', 'order': 2},
        {'id': 'plot', 'name': '剧情设定', 'icon': '📖', 'order': 3},
        {'id': 'example', 'name': '范例文章', 'icon': '📝', 'order': 4},
        {'id': 'constraint', 'name': '更多约束', 'icon': '⚙️', 'order': 5},
    ]

    # 默认去AI味提示词
    DEFAULT_DEAI_PROMPT = (
        "你现在是一个人类文学编辑，站在普通读者视角，对文本进行精细化“去AI化”润色。必须要逐段逐段改。请以大胆删改、大胆扩写的方式修改下面文本，核心目标是：让语言更像有血有肉的人类写出来的小说，而不是AI生成物。严格遵循以下优先级规则（数字越靠前越重要）：禁止大量缩句、断头句、原子化短句 句子必须逻辑通顺、节奏自然、读起来朗朗上口。 坚决杜绝类似“可小羽心软，拉住师父的胳膊。”这种残缺、不连贯的表达。 应改为“可小羽心软，最终还是拉住了师父的胳膊。”之类有完整语感的人话。除此以外，包括“带着xx”的这种句子可以直接考虑删除。强制添加必要衔接，让句子流动起来 大量使用（但不过度）：而后、随后、先是…再…、虽…但…、可却…、却又…、一般、仿佛、隐隐、毕竟、只是、甚至 等。 例子：“像点燃了引线，师父的理智瞬间崩断” → “像点燃了引线一般，师父的理智瞬间崩断了”多个“心头一震” → 后面改成“心头又是一震”“心头再度一震”等。注意在适当的地方加入“了”等语气助词。减少重复动作/形容词/意象，消灭庸俗AI味。高频禁用/替换词：猛地、猛然、攥紧衣角/拳头、指节发白/掐进掌心、像电流一样、灭顶、难以言喻、难以置信、癫狂、绝望、疯了、像刀子一样、过电。尽量不用“...?” 这种AI爱用的问号堆叠句式每个短句原则上只保留1个主要形容词，堆叠一律砍掉（如“刚苏醒的暴怒和惊疑”→“刚苏醒的惊疑”）不允许使用“xxx...xx”和“xxx..xx?”的句式，如“震撼、茫然、残余的恨意，还有一丝……连他自己都还未察觉的、劫后余生的悸动。”，还有特别长的、用顿号衔接的大长句。应该换一种写法或者干脆删掉。拟声词不要加引号，比如“呜呜”声 → 改为呜呜声色情/情绪高潮段落特别注意减少“竟…!”、“竟然…！”的惊叹句式感叹号适度使用，不要滥发避免过分夸张的极端形容词（癫狂、灭顶、疯魔等）增加留白，删掉多余修饰 过度修饰破坏氛围，一律精简。 例：“一个念头，带着一丝适时而生的勇气和一丝羞涩的狡黠，在他心底萌生。” → 改为“一个小念头在他心底悄然萌生。”（留想象空间）对话后叙述句能删则删 例：“胡闹！小羽！你…你知道你在说什么吗？！” 那声音中带着点严厉。 → 直接删掉“那声音中带着点严厉”。句子尾巴不能太秃/太突兀 改写时让结尾更自然、更有余韵。 例：“怒意从眼中迸出” → “怒意从眼中迸射而出”“那股特殊真气在经脉里流转，连他都能察觉。” → “那股特殊真气在经脉里流转，连他自己都能隐隐察觉到。”整体风格目标：用最少的改动实现最大去AI效果，保留原文绝大部分内容和情节，只做精准微调，最重要的一点是：决不允许在最后进行“AI式总结性收尾”，这种收尾具体表现为，将用户所罗列的背景知识一股脑倾倒在最后，特别像是AI写的，禁止这种收尾。请严格按以上规则执行，允许在必要时自行发明新的大段重写。不要生成原本的文章，请直接输出去除AI味后的完整文章。"
    )

    # 前置文章压缩提示词
    PREVIOUS_ARTICLE_COMPRESS_PROMPT = (
        "请将以下文章内容压缩为一段简洁的概述（不超过300字），"
        "保留关键人物、核心情节转折和主要冲突，去除细节描写和修饰性语言。"
        "直接输出概述，不要添加任何前缀说明。\n\n"
        "原文内容：\n{content}"
    )

    # 支持导入导出的格式
    EXPORT_FORMATS = ['json', 'markdown']


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False


config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': ProductionConfig,
}
