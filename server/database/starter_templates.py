"""首次启动时写入可删除的普通示例模板。"""

from database import db
from database.models import ProjectSetting, PromptTemplate


STARTER_TEMPLATES_SETTING_KEY = "starter_templates_seeded_v1"

STARTER_TEMPLATES = (
    {
        "name": "示例人物：推云童子雨生",
        "category": "character",
        "description": "第一次使用时提供的入门人物案例，可自由修改或删除。",
        "sort_order": -200,
        "content": """人物姓名：雨生

身份：天界年纪最小的推云童子，负责把云朵推往需要雨水的地方。他住在云海边的一座青瓦小院里，袖口常沾着淡淡水汽。

外貌：看起来约十一二岁，乌发束成小髻，眼睛明亮，穿一身云白短袍，腰间挂着一只收集故事的青色小葫芦。

性格：活泼开朗，童真可爱，好奇心很重。遇到新鲜事总想追问到底，也会因为急着帮助别人而偶尔闯下小祸。犯错后不推卸，愿意认真补救。

能力：能听懂风、云和雨的低语，可以把听来的故事收入葫芦，再将它们化成带有记忆的雨滴。

人物原则：善良但不完美；说话自然灵动；面对离别会难过，面对责任也会逐渐学会耐心与担当。""",
    },
    {
        "name": "示例剧情：雨落万物生",
        "category": "plot",
        "description": "与“推云童子雨生”配套的入门剧情案例，可自由修改或删除。",
        "sort_order": -190,
        "content": """雨生奉命巡游四海，收录人间、山川与海岛上的故事。他听渔人讲归航，听老树讲四季，也听孩童讲尚未实现的愿望，并把这些声音一一收入青色葫芦。

归途中，一片久旱的土地已经失去颜色，河床开裂，种子沉睡，连风都变得干涩。雨生发现普通云雨无法唤醒这里，于是决定打开葫芦，让收集来的无数故事化作雨滴落向人间。

每一滴雨都带着一段生命的记忆：勇气落进石缝，长出嫩芽；思念落进枯井，重新映出月亮；善意落进田野，让泥土恢复温度。雨生也必须面对选择——故事一旦化雨，便不能再完整地留在葫芦中。

请围绕雨生的旅途、选择与成长展开故事。结尾让沃土生出无数新生命，而那些消散的旧故事以花香、鸟鸣和人们口中的新传说继续流传。""",
    },
)


def ensure_starter_templates():
    """原子地执行一次示例模板初始化；删除模板不会触发再次写入。"""
    seeded = ProjectSetting.query.filter_by(
        key=STARTER_TEMPLATES_SETTING_KEY,
    ).first()
    if seeded is not None:
        return False

    for template_data in STARTER_TEMPLATES:
        db.session.add(PromptTemplate(
            **template_data,
            is_active=True,
            is_sample=False,
            style_strength="light",
            version=1,
        ))
    db.session.add(ProjectSetting(
        key=STARTER_TEMPLATES_SETTING_KEY,
        value="1",
    ))
    db.session.commit()
    return True
