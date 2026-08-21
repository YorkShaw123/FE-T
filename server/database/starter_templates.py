"""首次初始化示例模板，并支持用户主动补齐。"""

from database import db
from database.models import ProjectSetting, PromptTemplate


STARTER_TEMPLATES_SETTING_KEY = "starter_templates_seeded_v1"

STARTER_TEMPLATES = (
    {
        "name": "示例人物：雨生",
        "category": "character",
        "description": "第一次使用时提供的入门人物案例，可自由修改或删除。",
        "sort_order": -200,
        "content": """人物姓名：雨生

身份：
雨生是天界年纪最小的推云童子，隶属水部，协助四海龙王与水部正神梳理云气、筹备时雨。他住在天边的一座青瓦小院里，腰间挂着一只黑色小葫芦。

外貌：
看起来约十一二岁，乌发束成小髻，眼睛清澈明亮，穿一身素色短袍。认真揉云的时候，额前的碎发常被水汽打湿；害羞时会低下头，把半张脸都藏进衣袖里。

性格：
活泼开朗，童真可爱，同时感性、天真而羞涩。他很容易被人间的喜怒哀乐所触动，听见欢喜的故事会跟着露出笑容，看到悲伤的情景也会偷偷掉眼泪。

雨生偶尔会因为理解错愿望而手忙脚乱，但不会推卸错误。他愿意重新倾听，把事情认真做好。

职责与能力：
雨生能从人间香火中听见百姓家家户户的祈愿。他会分辨每个愿望真正想表达的内容，将其中的期盼、限制与情感整理清楚，再一点点揉进云气里。

愿望越清楚，云朵便越完整；愿望彼此矛盾时，云朵就会变得混乱。雨生必须耐心辨认，不能擅自改变许愿人真正想要的结果。

揉好的云朵会被装入他的小葫芦里。雨生常托着小脸守在旁边，等时辰到了，再与同僚们一起把它们化作春雨，送往人间。

人物习惯：
降雨时，雨生常因害羞躲在大家身后，只探出半张脸观察人间。

当他看见百姓的愿望得到回应，看见人们迎着雨水露出笑容时，自己也会笑得满面灿烂。

人物原则：
雨生善良但不完美，感性却不软弱。他会迷茫、误解和害怕，也会在一次次回应祈愿的过程中学会认真倾听、分辨要求并承担责任。

他说话自然灵动，保留孩童般的真诚与羞涩。不要把他写成无所不能、永远正确或故作深沉的人物。""",
    },
    {
        "name": "示例剧情：草木知春",
        "category": "plot",
        "description": "与“雨生”配套的入门剧情案例，可自由修改或删除。",
        "sort_order": -190,
        "content": """故事主题：
雨生倾听人间祈愿，将纷杂的愿望整理成云，并在经历误解、悲伤与争斗后，为大地生成一场真正回应众人期盼的春雨。

故事开端：
人间久旱，田地开裂，草木沉睡。无数香火与祈愿升入天界，有人求庄稼得救，有人盼亲人归来，也有人提出彼此矛盾的要求。

雨生第一次独自承担重要任务：听懂这些祈愿，把其中真正需要实现的部分揉成云朵，再与四海龙王、水部正神共同降下春雨。

主要波折：
愿望同时涌来，雨生很快晕晕乎乎。他没有分辨清楚便急着揉云，结果云层彼此冲撞，若不是被一位龙王拉住，他险些降下一场错乱的雨。

重新倾听时，他又遇见一段格外悲惨的祈愿。雨生感同身受，陷入其中，水汽不断从指缝散去，怎样也无法成云。风伯雨师鼓励他，教他必须学会理解悲伤，而不被悲伤完全吞没。

随后，一股贪婪的怨念闯入云海，企图扭曲众人的愿望，让所有雨水只落向一处。雨生不再一味顺从。他和雷公电母一起，与怨念争斗，保留其中真实的苦楚，扫去伤害他人的恶意，让天地通明。

故事高潮：
在前辈们的帮助下，雨生终于明白，回应祈愿并不是机械地满足每一句话，也不是擅自替人决定答案，而是在尊重愿望的前提下，理解它真正指向的结果。

他重新整理所有云朵：把清楚的期盼放在中心，把必要的限制编入风向，把众人的悲欢化作雨水的温度。

四海龙王引动水脉，水部正神校准天时。雨生打开葫芦，与众神一同将整理好的云朵送往人间。

故事结尾：
春雨终于落下。它落在每一片真正需要水分的土地上。

泥土变得湿润，嫩芽钻出石缝，河流重新流动。百姓奔出屋檐，在雨中露出欣喜的笑容。

雨生害羞地躲在同僚身后，悄悄探出脸来。看见自己的努力真正回应了人间的期盼，他也笑得满面灿烂。

这一刻他明白：最好的春雨，并不是凭空创造奇迹，而是认真听见每一个愿望，再让它以合适的模样抵达人间。

剧情要求：

- 故事篇幅不要太长，保持结构紧凑。
- 必须包含误解愿望、陷入悲伤、对抗怨念三个递进波折。
- 雨生不能轻易解决问题，关键决定必须由他自己完成。
- 四海龙王与水部正神负责协助，不替代雨生的成长。
- 隐含“接收要求、理解要求、整理要求、生成结果”的主题，但不要直接出现 AI、程序、提示词或编辑器等现代概念。
- 结尾落在春雨降临、草木复苏和愿望得到恰当回应上。""",
    },
)


def ensure_starter_templates():
    """仅在数据库首次初始化时写入示例模板。"""
    seeded = ProjectSetting.query.filter_by(
        key=STARTER_TEMPLATES_SETTING_KEY,
    ).first()
    if seeded is not None:
        return False

    created = _add_missing_starter_templates()
    db.session.add(ProjectSetting(
        key=STARTER_TEMPLATES_SETTING_KEY,
        value="1",
    ))
    db.session.commit()
    return bool(created)


def create_missing_starter_templates():
    """由用户主动触发，补齐缺失的示例模板并返回新增模板。"""
    created = _add_missing_starter_templates()
    if created:
        db.session.commit()
    return created


def _add_missing_starter_templates():
    """将当前会话中缺失的示例模板加入待提交队列。"""
    created = []
    for template_data in STARTER_TEMPLATES:
        existing = PromptTemplate.query.filter_by(
            name=template_data["name"],
            category=template_data["category"],
        ).first()
        if existing is not None:
            continue
        template = PromptTemplate(
            **template_data,
            is_active=True,
            is_sample=False,
            style_strength="light",
            version=1,
        )
        db.session.add(template)
        created.append(template)
    return created
