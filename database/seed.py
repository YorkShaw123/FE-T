"""
数据库种子数据
首次启动时，如果模板表为空，自动填充预设模板
"""
from services.template_service import create_template


SEED_TEMPLATES = [
    # ===== 人物设定 =====
    {
        'name': '主角性格与身份',
        'category': 'character',
        'content': (
            '主角姓名：{{角色名}}\n'
            '性别：{{性别}}\n'
            '年龄：{{年龄}}\n'
            '外貌特征：{{外貌描述}}\n'
            '性格特点：\n'
            '- 核心性格：{{核心性格}}\n'
            '- 性格优点：{{优点}}\n'
            '- 性格缺陷：{{缺陷}}\n'
            '- 口头禅/习惯动作：{{习惯}}\n'
            '身份背景：{{身份背景}}\n'
            '能力/特长：{{能力特长}}\n'
            '内心驱动力/目标：{{人生目标}}\n'
            '与其他人物的关系：{{人物关系}}'
        ),
        'description': '定义主角的基本信息、性格和能力',
        'is_sample': True,
    },
    {
        'name': '配角设定模板',
        'category': 'character',
        'content': (
            '角色名：{{配角名}}\n'
            '性别：{{配角性别}}\n'
            '与主角关系：{{关系}}\n'
            '性格特点：{{配角性格}}\n'
            '在故事中的作用：{{角色作用}}\n'
            '背景故事简述：{{配角背景}}'
        ),
        'description': '快速定义配角的基本信息',
        'is_sample': True,
    },

    # ===== 背景设定 =====
    {
        'name': '世界观基础设定',
        'category': 'background',
        'content': (
            '时代背景：{{时代背景}}\n'
            '地理位置/世界观：{{世界描述}}\n'
            '社会结构/权力体系：{{社会结构}}\n'
            '科技/魔法水平：{{技术等级}}\n'
            '核心规则/法则：{{世界观法则}}\n'
            '历史重大事件：{{历史事件}}\n'
            '当前社会矛盾/冲突：{{社会矛盾}}'
        ),
        'description': '建立小说的世界观基础框架',
        'is_sample': True,
    },
    {
        'name': '故事发生场景',
        'category': 'background',
        'content': (
            '主要场景：{{主要场景}}\n'
            '场景氛围：{{场景氛围}}\n'
            '场景特色/标志物：{{场景特色}}\n'
            '场景与主线关联：{{场景关联}}'
        ),
        'description': '描述故事发生的具体场景环境',
        'is_sample': True,
    },

    # ===== 剧情设定 =====
    {
        'name': '章节大纲模板',
        'category': 'plot',
        'content': (
            '本章节在故事中的位置：第{{章节号}}章\n'
            '本章核心事件：{{核心事件}}\n'
            '本章出场人物：{{出场人物}}\n'
            '本章情感基调：{{情感基调}}\n'
            '与主线的关联：{{主线关联}}\n'
            '本章需要完成的伏笔/铺垫：\n{{伏笔铺垫}}\n'
            '本章结尾状态（悬念/转折/收束）：{{结尾状态}}'
        ),
        'description': '规划单章的叙事框架和要点',
        'is_sample': True,
    },
    {
        'name': '主线剧情概要',
        'category': 'plot',
        'content': (
            '故事类型/流派：{{故事类型}}\n'
            '主线目标：主角最终要达成的目标——{{主线目标}}\n'
            '核心冲突：{{核心冲突}}\n'
            '故事分段：\n'
            '  第一阶段（开端）：{{阶段一}}\n'
            '  第二阶段（发展）：{{阶段二}}\n'
            '  第三阶段（高潮）：{{阶段三}}\n'
            '  第四阶段（结局）：{{阶段四}}\n'
            '主题/立意：{{故事主题}}'
        ),
        'description': '定义整个故事的主线剧情框架',
        'is_sample': True,
    },

    # ===== 范例文章 =====
    {
        'name': '优质小说开篇范例',
        'category': 'example',
        'content': (
            '以下是一段优质小说开篇的示例，请在写作时参考其节奏感和画面感：\n\n'
            '北风如刀，刮过荒原上最后一片枯草。\n\n'
            '林昭裹紧身上单薄的外套，眯起眼睛望向远处那座孤零零的驿站。'
            '他已经在路上走了三天，脚底磨出了水泡，但脚步却不敢停——'
            '身后的追兵最快今晚就能赶到。\n\n'
            '驿站的门半掩着，里面透出昏黄的油灯光。'
            '林昭推开门的瞬间，右手已经按在了腰间的短刀上。\n\n'
            '屋里只有一个人。\n\n'
            '一个他以为再也见不到的人。'
        ),
        'description': '展示优秀小说开篇的写法：环境渲染+冲突暗示+悬念',
    },
    {
        'name': '动作场面写法范例',
        'category': 'example',
        'content': (
            '写动作/战斗场景时参考以下节奏：\n\n'
            '- 短句加快节奏，让读者感受到紧张感\n'
            '- 穿插感官描写（声音、触感、视觉碎片）\n'
            '- 动作-反应-结果三步循环\n'
            '- 不要求每个动作都详写，抓住关键转折点即可\n\n'
            '示例：\n'
            '刀光一闪。\n'
            '林昭本能地侧身，刀锋擦过耳际，削下几缕头发。'
            '金属碰撞声在巷子里回荡。他没有给对方收刀的机会——'
            '左手扣住对方手腕，右肘猛击对方肋下。'
            '闷哼声中，那人的刀掉在地上，发出清脆的响声。'
        ),
        'description': '战斗/动作场景的写作技巧和范例',
    },

    # ===== 更多约束 =====
    {
        'name': '写作质量要求',
        'category': 'constraint',
        'content': (
            '请严格按照以下标准进行写作：\n\n'
            '1. 避免空洞的概述性叙事，用具体的场景、动作和对话推进故事\n'
            '2. 尽量减少"他感到""他觉得""他意识到"等心理动词，用外部行为暗示内心\n'
            '3. 对话要符合人物性格和身份，不同角色说话方式应有明显区别\n'
            '4. 段落长短结合，避免每段字数过于均匀\n'
            '5. 注重感官描写：视觉、听觉、嗅觉、触觉，让读者身临其境\n'
            '6. 章节结尾应有钩子——一个悬念、一个问题或一个意外的转折\n'
            '7. 避免使用网络流行语和过于现代的表达（除非是当代背景）\n'
            '8. 输出字数不少于{{最低字数}}字'
        ),
        'description': '通用的写作质量标准和约束条件',
        'is_sample': True,
    },
    {
        'name': '叙事节奏控制',
        'category': 'constraint',
        'content': (
            '注意控制叙事节奏：\n\n'
            '1. 开篇200字内必须建立冲突或悬念\n'
            '2. 每500字左右需要有一个节奏变化（紧张→舒缓，或舒缓→紧张）\n'
            '3. 对话不可以连续超过5轮没有叙事穿插\n'
            '4. 环境描写每章控制在3处以内，且必须与人物的心理或处境相呼应\n'
            '5. 避免大段的信息性交代（设定说明），将背景信息融入场景和对话中\n'
            '6. 本章应集中描写不超过{{核心事件数}}个核心事件'
        ),
        'description': '控制文章叙事节奏和密度的约束条件',
        'is_sample': True,
    },
]


def seed_templates(force=False):
    """
    为数据库填充预设模板
    :param force: 为 True 时强制覆盖已有数据（慎用）
    """
    from database.models import PromptTemplate

    existing_count = PromptTemplate.query.count()
    if existing_count > 0 and not force:
        print(f'[Forestar] 已有 {existing_count} 个模板，跳过种子数据填充')
        return existing_count

    if force and existing_count > 0:
        print(f'[Forestar] 强制填充：清空现有 {existing_count} 个模板...')
        PromptTemplate.query.delete()

    created = 0
    for tpl in SEED_TEMPLATES:
        try:
            create_template(
                name=tpl['name'],
                category=tpl['category'],
                content=tpl['content'],
                description=tpl.get('description', ''),
                sort_order=0,
                is_sample=tpl.get('is_sample', False),
            )
            created += 1
        except Exception as e:
            print(f'[Forestar] 创建种子模板失败 [{tpl["name"]}]: {e}')

    print(f'[Forestar] 种子数据填充完成: 创建 {created} 个模板')
    return created
