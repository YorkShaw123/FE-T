# -*- coding: utf-8 -*-
"""生成 Flora Editor 7 页答辩 PPT"""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

# ---------- 配色（浅色主题） ----------
INK = RGBColor(0x21, 0x21, 0x21)       # 主文字
GRAY = RGBColor(0x6E, 0x6E, 0x6E)      # 次级文字
GREEN = RGBColor(0x1B, 0x5E, 0x20)     # 主色 深绿
ACCENT = RGBColor(0x43, 0xA0, 0x47)    # 强调绿
LIGHT = RGBColor(0xF1, 0xF8, 0xE9)     # 浅绿面板
PANEL = RGBColor(0xF7, 0xF7, 0xF7)     # 灰面板
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LINE = RGBColor(0xDD, 0xDD, 0xDD)

FONT = "微软雅黑"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]


def set_font(run, size=14, bold=False, color=INK, name=FONT):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = color
    f.name = name
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", name)


def add_text(slide, x, y, w, h, lines, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
             size=14, bold=False, color=INK, line_spacing=1.15, space_after=4):
    """lines: str 或 [(text,{size,bold,color}), ...] 或 list[str]"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    if isinstance(lines, str):
        lines = [lines]
    first = True
    for ln in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        p.line_spacing = line_spacing
        p.space_after = Pt(space_after)
        if isinstance(ln, tuple):
            txt, opt = ln
        else:
            txt, opt = ln, {}
        run = p.add_run()
        run.text = txt
        set_font(run, opt.get("size", size), opt.get("bold", bold),
                 opt.get("color", color))
    return tb


def add_rect(slide, x, y, w, h, fill=LIGHT, line_color=None, radius=0.08, shadow=False):
    sp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                Inches(x), Inches(y), Inches(w), Inches(h))
    try:
        sp.adjustments[0] = radius
    except Exception:
        pass
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill
    if line_color is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line_color
        sp.line.width = Pt(1)
    sp.shadow.inherit = False
    sp.text_frame.text = ""
    return sp


def add_arrow_text(slide, x, y, w, h, text, fill=ACCENT, size=13, color=WHITE, bold=True):
    add_rect(slide, x, y, w, h, fill=fill, radius=0.15)
    add_text(slide, x, y, w, h, text, align=PP_ALIGN.CENTER,
             anchor=MSO_ANCHOR.MIDDLE, size=size, bold=bold, color=color,
             line_spacing=1.0, space_after=0)


def page_header(slide, num, title, subtitle=""):
    """页眉：色条 + 页码 + 标题"""
    add_rect(slide, 0, 0, 13.333, 0.14, fill=GREEN, radius=0)
    add_text(slide, 0.7, 0.42, 10.5, 0.7, title, size=26, bold=True, color=INK)
    if subtitle:
        add_text(slide, 0.7, 1.06, 11.5, 0.4, subtitle, size=13, color=GRAY)
    add_text(slide, 12.3, 0.45, 0.8, 0.5, f"{num} / 7", size=12, color=GRAY,
             align=PP_ALIGN.RIGHT)
    add_rect(slide, 0.7, 1.45, 12.0, 0.016, fill=LINE, radius=0)


# ================= 第 1 页：封面 =================
s = prs.slides.add_slide(BLANK)
add_rect(s, 0, 0, 13.333, 7.5, fill=WHITE, radius=0)
add_rect(s, 0, 0, 13.333, 2.9, fill=GREEN, radius=0)
add_text(s, 1.0, 1.0, 11.3, 1.0, "雨生编辑器 · Flora Editor",
         align=PP_ALIGN.CENTER, size=40, bold=True, color=WHITE)
add_text(s, 1.0, 2.05, 11.3, 0.6, "本地优先的中文 AI 创作工具 —— 模板复用 · 文风控制 · 数据不出本机",
         align=PP_ALIGN.CENTER, size=16, color=RGBColor(0xC8, 0xE6, 0xC9))

for i, (big, small) in enumerate([
    ("18,425", "行代码 · 86 个文件"),
    ("21 天", "单人独立开发 · 30 次提交"),
    ("8 家", "LLM 厂商统一适配"),
    ("44 个", "本地中文文风特征"),
]):
    x = 0.95 + i * 2.95
    add_rect(s, x, 3.55, 2.7, 1.35, fill=LIGHT, radius=0.1)
    add_text(s, x, 3.75, 2.7, 0.6, big, align=PP_ALIGN.CENTER, size=26, bold=True, color=GREEN)
    add_text(s, x, 4.38, 2.7, 0.45, small, align=PP_ALIGN.CENTER, size=12, color=GRAY)

add_text(s, 1.0, 5.55, 11.3, 0.5, "线上实训项目答辩",
         align=PP_ALIGN.CENTER, size=20, bold=True, color=INK)
add_text(s, 1.0, 6.15, 11.3, 0.4, "汇报人：肖嘉琛    技术路线：Tauri 2 + Flask + SQLite    2026 年 8 月",
         align=PP_ALIGN.CENTER, size=13, color=GRAY)

# ================= 第 2 页：背景与设计目的 =================
s = prs.slides.add_slide(BLANK)
page_header(s, 2, "一、项目背景与设计目的", "中文创作使用大模型辅助的三大痛点 → 本项目的针对性设计")

pains = [
    ("提示词难复用", "每次写作重新拼凑人物设定、\n背景、剧情约束", "模板管理系统",
     "五类分类 + 版本树 + 启用开关\n素材一次沉淀、终身复用"),
    ("AI 文风机械", "\u201c然而\u201d\u201c综上所述\u201d等 AI 味严重\n风格不连贯、不像本人", "Style Engine + Style RAG",
     "本地 44 特征文风分析\n语料检索注入 + 去 AI 味流水线"),
    ("隐私与成本顾虑", "在线平台需上传作品、订阅付费\n数据不可控", "本地优先架构",
     "纯本地 SQLite 存储\nAPI Key 不落盘 · 自带 Key 按量付费"),
]
for i, (pt, pd, sol, sd) in enumerate(pains):
    x = 0.7 + i * 4.13
    add_rect(s, x, 1.85, 3.85, 4.6, fill=PANEL, radius=0.06)
    add_rect(s, x, 1.85, 3.85, 0.09, fill=RGBColor(0xE5, 0x73, 0x73), radius=0)
    add_text(s, x + 0.25, 2.1, 3.35, 0.45, f"痛点 {i+1}：{pt}", size=16, bold=True, color=INK)
    add_text(s, x + 0.25, 2.62, 3.35, 0.9, pd, size=12.5, color=GRAY, line_spacing=1.3)
    add_arrow_text(s, x + 0.25, 3.75, 3.35, 0.55, "▼ 解决方案：" + sol, size=12.5)
    add_text(s, x + 0.25, 4.5, 3.35, 1.6, sd, size=12.5, color=INK, line_spacing=1.35)

add_text(s, 0.7, 6.75, 12.0, 0.5,
         "预期结果：双击 EXE 即用，无需任何环境；数据全本机、成本按量计费；文风可控、AI 干预可审计",
         size=13.5, bold=True, color=GREEN)

# ================= 第 3 页：技术栈与架构 =================
s = prs.slides.add_slide(BLANK)
page_header(s, 3, "二、技术栈与分层架构", "每个选型都回答\u201c为什么不用更重的方案\u201d")

add_text(s, 0.7, 1.7, 6.0, 0.4, "技术选型（精简）", size=15, bold=True, color=GREEN)
tech = [
    ("Tauri 2 (Rust)", "桌面壳，替代 Electron：安装包 3~5MB vs 80MB+"),
    ("Flask + SQLAlchemy", "单服务后端：页面与 API 同端口，天然无跨域"),
    ("SQLite + NumPy", "替代向量数据库：16MB 内存完成毫秒级余弦检索"),
    ("原生 JS / HTML", "替代 React/Vue：无构建链，桌面与调试共用一套文件"),
    ("urllib 标准库", "替代 OpenAI SDK：省 15~20MB 打包体积"),
    ("pytest + Ruff", "20 个测试文件 3,365 行 + 静态检查"),
]
for i, (t, d) in enumerate(tech):
    y = 2.2 + i * 0.62
    add_rect(s, 0.7, y, 6.0, 0.52, fill=LIGHT if i % 2 == 0 else PANEL, radius=0.12)
    add_text(s, 0.92, y + 0.02, 2.35, 0.48, t, size=12.5, bold=True, color=GREEN,
             anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.0)
    add_text(s, 3.3, y + 0.02, 3.3, 0.48, d, size=10.5, color=INK,
             anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.05)

# 右侧分层架构图
add_text(s, 7.15, 1.7, 5.5, 0.4, "四层架构（自底向上构建）", size=15, bold=True, color=GREEN)
layers = [
    ("桌面壳层", "Tauri / Rust — Sidecar 生命周期 · 健康检查 · 窗口管理", RGBColor(0xE8, 0xF5, 0xE9)),
    ("路由层 routes/", "4 个蓝图 — template / generation / style / corpora", RGBColor(0xEF, 0xEB, 0xE3)),
    ("服务层 services/", "生成编排 · 提示词组装 · LLM 适配 · 文风检索分析 · 并发守卫", RGBColor(0xE3, 0xF2, 0xFD)),
    ("数据层 database/", "8 张 ORM 模型表 · 幂等迁移 · SQLite (data/flora.db)", RGBColor(0xFC, 0xE4, 0xEC)),
]
for i, (name, desc, col) in enumerate(layers):
    y = 2.2 + i * 0.98
    add_rect(s, 7.15, y, 5.5, 0.8, fill=col, radius=0.1, line_color=LINE)
    add_text(s, 7.35, y + 0.08, 5.1, 0.35, name, size=13, bold=True, color=INK)
    add_text(s, 7.35, y + 0.44, 5.1, 0.3, desc, size=10.5, color=GRAY)
    if i < 3:
        add_text(s, 9.6, y + 0.78, 0.6, 0.22, "▼", size=10, color=GRAY, align=PP_ALIGN.CENTER,
                 line_spacing=1.0, space_after=0)

add_text(s, 7.15, 6.25, 5.5, 0.9,
         [("契约：路由层不写业务、服务层不碰 HTTP，", {"size": 11.5, "color": GRAY}),
          ("新增 LLM 厂商只需在 api_client.py 增加一个适配函数", {"size": 11.5, "bold": True, "color": GREEN})],
         line_spacing=1.25)

# ================= 第 4 页：核心功能实现 =================
s = prs.slides.add_slide(BLANK)
page_header(s, 4, "三、核心功能：六阶段生成流水线", "SSE 先连接后干活 · 逐字流式输出 · 一份记录存全套版本")

stages = [
    ("① 组装\n提示词", "模板按 9 段\n顺序拼接"),
    ("② 初稿\n生成", "SSE 流式\n逐字输出"),
    ("③ RAG\n检索", "本地混合检索\nTop-4 片段"),
    ("④ 风格\n重写", "参考片段\n二次改写"),
    ("⑤ 去AI味\n处理", "消灭\u201c然而\u201d\n式机械腔"),
    ("⑥ 落盘\n存档", "六版本写入\nSQLite"),
]
for i, (t, d) in enumerate(stages):
    x = 0.7 + i * 2.02
    add_rect(s, x, 1.85, 1.82, 1.75, fill=GREEN if i in (1,) else LIGHT, radius=0.1)
    add_text(s, x, 1.98, 1.82, 0.8, t, align=PP_ALIGN.CENTER, size=13.5, bold=True,
             color=WHITE if i == 1 else GREEN, line_spacing=1.1)
    add_text(s, x, 2.85, 1.82, 0.65, d, align=PP_ALIGN.CENTER, size=10.5,
             color=RGBColor(0xE8, 0xF5, 0xE9) if i == 1 else GRAY, line_spacing=1.15)
    if i < 5:
        add_text(s, x + 1.80, 2.35, 0.26, 0.4, "→", size=16, bold=True, color=ACCENT,
                 align=PP_ALIGN.CENTER, line_spacing=1.0, space_after=0)

add_rect(s, 0.7, 3.85, 12.0, 0.75, fill=PANEL, radius=0.1)
add_text(s, 0.95, 3.92, 11.5, 0.6,
         [("关键机制：", {"size": 12.5, "bold": True, "color": GREEN}),
          ("SSE 先建立连接再执行耗时操作，前端不误判超时；operation_guard 并发守卫防止连点请求风暴；"
           "初稿/重写/去味/最终版 全部落入 GenerationRecord", {"size": 12, "color": INK})],
         anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.2)

add_text(s, 0.7, 4.85, 12.0, 0.4, "三大功能联动闭环", size=15, bold=True, color=GREEN)
loops = [
    ("创作闭环", "生成 → 记录 → 满意段落回写模板 → 复用", "提示词资产越用越厚"),
    ("文风闭环", "范例文章 → Style Card + 语料库双路注入 → 生成", "AI 写出\u201c像你\u201d的文字"),
    ("质量闭环", "初稿 → 风格重写 → 去AI味 → 版本对比 → 定稿", "每步可审计、可回退"),
]
for i, (t, path, val) in enumerate(loops):
    x = 0.7 + i * 4.13
    add_rect(s, x, 5.3, 3.85, 1.5, fill=LIGHT, radius=0.08)
    add_text(s, x + 0.22, 5.42, 3.4, 0.4, f"{i+1}. {t}", size=13, bold=True, color=GREEN)
    add_text(s, x + 0.22, 5.82, 3.4, 0.6, path, size=11, color=INK, line_spacing=1.2)
    add_text(s, x + 0.22, 6.42, 3.4, 0.35, "→ " + val, size=11, bold=True, color=GRAY)

# ================= 第 5 页：开发过程与 AI 协同 =================
s = prs.slides.add_slide(BLANK)
page_header(s, 5, "四、开发过程：21 天六阶段 + AI 协同", "单人开发 · Vibe Coding · 先验证后优化")

# 时间线甘特
add_text(s, 0.7, 1.65, 8.0, 0.35, "时间线（7.31 — 8.20）", size=14, bold=True, color=GREEN)
phases = [
    ("MVP 原型", 3, "3天", "跑通生成最小闭环", 0),
    ("桌面化转型", 5, "5天", "Tauri 壳 + 打包 + 多厂商", 3),
    ("Style RAG", 2, "2天", "语料导入 + 混合检索", 8),
    ("架构重构", 4, "4天", "分层规范 + 安全加固", 10),
    ("Style Engine", 3, "3天", "44 特征本地文风分析", 14),
    ("收尾发布", 4, "4天", "修复 + 文档 + v1.0.0", 17),
]
G_X, G_W, TOTAL = 2.75, 6.6, 21
for i, (name, days, label, goal, start) in enumerate(phases):
    y = 2.1 + i * 0.62
    add_text(s, 0.7, y + 0.02, 1.95, 0.45, name, size=11.5, bold=True, color=INK,
             anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.0)
    bx = G_X + G_W * start / TOTAL
    bw = G_W * days / TOTAL
    add_rect(s, bx, y + 0.06, bw, 0.38, fill=GREEN if days >= 4 else ACCENT, radius=0.3)
    add_text(s, bx, y + 0.06, bw, 0.38, label, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
             size=9.5, bold=True, color=WHITE, line_spacing=1.0, space_after=0)
    add_text(s, 9.55, y + 0.02, 3.1, 0.45, goal, size=10.5, color=GRAY,
             anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.05)

add_rect(s, 0.7, 5.95, 12.0, 1.1, fill=PANEL, radius=0.08)
add_text(s, 0.95, 6.05, 5.6, 0.9,
         [("AI 工具协同", {"size": 12.5, "bold": True, "color": GREEN}),
          ("Trae + DeepSeek V3 Pro：主力编码，生成 80%+ 业务代码", {"size": 11, "color": INK}),
          ("VSCode + Codex：第二视角审查、Bug 定位、Lint 把关", {"size": 11, "color": INK})],
         line_spacing=1.2, space_after=2)
add_text(s, 6.9, 6.05, 5.5, 0.9,
         [("人机分工：AI 是\u201c高级码农\u201d，我是\u201c产品经理 + 审查者\u201d", {"size": 12, "bold": True, "color": GREEN}),
          ("架构决策我来拍板 · 每行代码我都读过 · 三道质量防线：", {"size": 11, "color": INK}),
          ("人工逐行审查 → 双 AI 交叉验证 → 3,365 行自动化测试", {"size": 11, "color": INK})],
         line_spacing=1.2, space_after=2)

# ================= 第 6 页：创新与落地价值 =================
s = prs.slides.add_slide(BLANK)
page_header(s, 6, "五、创新点与落地价值", "把\u201c创作流程\u201d当一等公民，而不是又一个聊天壳")

add_text(s, 0.7, 1.7, 6.0, 0.35, "对比 GitHub 同类开源项目", size=14, bold=True, color=GREEN)
cmp_rows = [
    ("提示词组织", "平铺列表/文件夹", "五类模板 + 版本树"),
    ("文风控制", "无，或仅靠 prompt", "Style Card + RAG 双路注入"),
    ("生成结果", "单次对话即弃", "六版本链，可审计可回退"),
    ("模型接入", "通常单厂商", "8 家厂商运行时切换"),
    ("数据归属", "云端存储", "本机 SQLite，Key 不落盘"),
]
for i, (dim, other, mine) in enumerate(cmp_rows):
    y = 2.15 + i * 0.56
    add_rect(s, 0.7, y, 6.0, 0.48, fill=LIGHT if i % 2 == 0 else PANEL, radius=0.1)
    add_text(s, 0.9, y, 1.5, 0.48, dim, size=11, bold=True, color=INK,
             anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.0)
    add_text(s, 2.45, y, 1.9, 0.48, other, size=10, color=GRAY,
             anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.05)
    add_text(s, 4.4, y, 2.2, 0.48, mine, size=10.5, bold=True, color=GREEN,
             anchor=MSO_ANCHOR.MIDDLE, line_spacing=1.05)

add_text(s, 7.15, 1.7, 5.5, 0.35, "三个原创设计", size=14, bold=True, color=GREEN)
orig = [
    ("去 AI 味流水线", "把\u201cAI 味\u201d作为独立质量维度管理，三段式处理各版本独立保存"),
    ("模板版本树", "旧版自动入版本表可回滚，源自网文作者维护设定集的真实习惯"),
    ("本地 Style Engine", "44 特征 CPU 本地计算 + 混合检索 + 三道内容复用防线，断网可用"),
]
for i, (t, d) in enumerate(orig):
    y = 2.15 + i * 1.0
    add_rect(s, 7.15, y, 5.5, 0.85, fill=LIGHT, radius=0.08)
    add_text(s, 7.35, y + 0.06, 5.1, 0.35, f"{i+1}. {t}", size=12.5, bold=True, color=GREEN)
    add_text(s, 7.35, y + 0.42, 5.1, 0.4, d, size=10.5, color=INK, line_spacing=1.15)

add_rect(s, 0.7, 5.5, 12.0, 1.5, fill=GREEN, radius=0.08)
add_text(s, 1.0, 5.62, 11.4, 0.4, "落地价值", size=14, bold=True, color=WHITE)
vals = [
    "双击 EXE 即用，非技术写作者零门槛",
    "生成一章成本 < 1 分钱 vs 平台订阅 30~50 元/月",
    "数据不出本机 + MIT 开源可审计",
    "网文/同人/隐私敏感/成本敏感四类用户全覆盖",
]
for i, v in enumerate(vals):
    x = 1.0 + (i % 2) * 5.8
    y = 6.08 + (i // 2) * 0.42
    add_text(s, x, y, 5.6, 0.38, "● " + v, size=11.5, color=RGBColor(0xE8, 0xF5, 0xE9),
             line_spacing=1.0, space_after=0)

# ================= 第 7 页：总结与迭代 =================
s = prs.slides.add_slide(BLANK)
page_header(s, 7, "六、总结与迭代规划", "成果一览 · 演进路线 · 致谢")

add_text(s, 0.7, 1.7, 5.8, 0.35, "项目成果", size=14, bold=True, color=GREEN)
results = [
    "9 大功能模块 100% 完成，v1.0.1 已发布",
    "18,425 行代码：后端 50.8% / 前端 19.7% / 测试 18.3%",
    "13 篇设计文档 + 20 个测试文件 + CI 流水线",
    "CloudStudio 云端演示部署（start.sh 一键启动）",
    "AI 双重样本：AI 开发（Vibe Coding）× AI 交付（产品能力）",
]
for i, r in enumerate(results):
    add_text(s, 0.75, 2.15 + i * 0.5, 5.8, 0.45, "✓ " + r, size=12.5, color=INK,
             line_spacing=1.0, space_after=0)

add_text(s, 7.0, 1.7, 5.7, 0.35, "迭代路线（延续本地优先原则）", size=14, bold=True, color=GREEN)
roadmap = [
    ("P0", "Ollama 本地模型接入", "补全\u201c完全离线\u201d最后一块拼图"),
    ("P1", "Style Engine 扩展 + 导出格式", "EPUB/docx，写完即发"),
    ("P2", "端到端加密同步 / 模板市场", "可选云能力，社区共建"),
]
for i, (p, t, d) in enumerate(roadmap):
    y = 2.15 + i * 1.05
    add_rect(s, 7.0, y, 5.7, 0.9, fill=LIGHT, radius=0.08)
    add_arrow_text(s, 7.2, y + 0.2, 0.7, 0.5, p, size=13)
    add_text(s, 8.1, y + 0.08, 4.4, 0.4, t, size=12.5, bold=True, color=INK)
    add_text(s, 8.1, y + 0.46, 4.4, 0.35, d, size=10.5, color=GRAY)

add_rect(s, 0.7, 5.6, 12.0, 1.3, fill=GREEN, radius=0.08)
add_text(s, 1.0, 5.85, 11.4, 0.5, "谢谢观看 · 欢迎提问", align=PP_ALIGN.CENTER,
         size=22, bold=True, color=WHITE)
add_text(s, 1.0, 6.4, 11.4, 0.4, "雨生编辑器 Flora Editor ·  GitHub: YorkShaw123/FE-T ·  CloudStudio 云端演示已部署",
         align=PP_ALIGN.CENTER, size=12, color=RGBColor(0xC8, 0xE6, 0xC9))

out = r"D:\2026_Summer_HEIMA\Flora_Editor\docs\defense\07_答辩PPT.pptx"
prs.save(out)
print("saved:", out)
