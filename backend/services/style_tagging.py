"""规则打标（零成本、不依赖模型）：场景 / 节奏 / 人称 / 情绪 / 对话占比。

从 ``server/services/style_rag_service.py`` 第 55–155 行原样切出，关键词表与
推断口径一字未改。切片工具只切一次，之后维护以本文件为准。
"""

import hashlib
import re
SCENE_TYPES = {'dialogue', 'action', 'psychology', 'environment', 'transition', 'narration', 'mixed'}
PACES = {'slow', 'medium', 'fast'}
SCENE_LABELS = {
    'dialogue': '对话', 'action': '动作', 'psychology': '心理',
    'environment': '环境', 'transition': '转场', 'narration': '叙述', 'mixed': '综合',
}
PACE_LABELS = {'slow': '舒缓', 'medium': '中等', 'fast': '紧凑'}

# ---------- 规则打标关键词库（零成本，不依赖 LLM） ----------
_SCENE_KEYWORDS = {
    'dialogue': ('他说', '她说', '他道', '她道', '笑道', '问道', '回答', '开口', '台词', '说：', '道：', '低语', '喊道', '答道', '“', '”'),
    'action': ('战斗', '追逐', '逃跑', '袭击', '搏斗', '追杀', '拳头', '刀锋', '冲了', '扑向', '挥拳', '猛地', '闪身', '躲避', '厮杀'),
    'psychology': ('心理', '内心', '回忆', '思考', '犹豫', '梦境', '意识', '念头', '思绪', '盘算', '暗自', '觉得', '想道', '浮现', '纠结'),
    'environment': ('环境', '景色', '清晨', '黄昏', '夜晚', '房间', '街道', '天气', '月光', '雨水', '风声', '树影', '远山', '灯火', '窗帘'),
    'transition': ('转场', '数日后', '第二天', '多年后', '与此同时', '离开', '抵达', '回到', '转眼', '片刻后', '良久', '从此'),
}
_POV_PATTERNS = {
    '第一人称': ('我', '我们'),
    '第二人称': ('你', '你们'),
    '第三人称': ('他', '她', '他们', '她们'),
}
_EMOTION_KEYWORDS = {
    '愤怒': ('愤怒', '恼火', '怒', '恨', '咬牙切齿', '暴怒'),
    '悲伤': ('悲伤', '难过', '伤心', '泪', '哽咽', '哀', '痛'),
    '恐惧': ('恐惧', '害怕', '惊慌', '颤抖', '冷汗', '惊惧'),
    '紧张': ('紧张', '紧绷', '攥紧', '屏息', '心跳', '窒息'),
    '温柔': ('温柔', '轻柔', '轻声', '温和', '暖意'),
    '喜悦': ('喜悦', '笑', '开心', '雀跃', '欢喜', '愉快'),
    '压抑': ('压抑', '沉闷', '沉重', '窒息感', '阴郁', '窒息'),
    '宁静': ('宁静', '安静', '静谧', '安然', '平和'),
}

_EMOTION_LABELS = {
    '愤怒': '愤怒', '悲伤': '悲伤', '恐惧': '恐惧', '紧张': '紧张',
    '温柔': '温柔', '喜悦': '喜悦', '压抑': '压抑', '宁静': '宁静',
}
_EMOTION_ORDER = ['愤怒', '悲伤', '恐惧', '紧张', '温柔', '喜悦', '压抑', '宁静']


def _content_hash(content):
    return hashlib.sha256((content or '').encode('utf-8')).hexdigest()


def _dialogue_ratio(content):
    quoted = ''.join(re.findall(r'[“\"]([^”\"]+)[”\"]', content or ''))
    return round(min(1.0, len(quoted) / max(1, len(content or ''))), 3)


def _infer_scene_type(content):
    """关键词计数推断场景类型；命中为 0 时回退 mixed。"""
    scores = {}
    for key, words in _SCENE_KEYWORDS.items():
        scores[key] = sum(content.count(word) for word in words)
    winner = max(scores, key=scores.get)
    return winner if scores.get(winner, 0) > 0 else 'mixed'


def _infer_pacing(content):
    """按平均句长与标点密度推断节奏：<18 字/句为紧凑，>32 字/句为舒缓。"""
    sentences = [s for s in re.split(r'[。！？!?]', content or '') if s.strip()]
    if not sentences:
        return 'medium'
    avg = len(content) / len(sentences)
    if avg < 18:
        return 'fast'
    if avg > 32:
        return 'slow'
    return 'medium'


def _infer_pov(content):
    """按人称代词频次推断叙述视角（第一/第二/第三人称）。"""
    scores = {}
    for name, words in _POV_PATTERNS.items():
        scores[name] = sum(content.count(word) for word in words)
    winner = max(scores, key=scores.get)
    return winner if scores.get(winner, 0) > 0 else ''


def _infer_emotion(content):
    """情绪词计数，输出最多两个情绪标签（顿号连接）。"""
    hits = {}
    for name, words in _EMOTION_KEYWORDS.items():
        count = sum(content.count(word) for word in words)
        if count > 0:
            hits[name] = count
    if not hits:
        return ''
    top = sorted(hits, key=lambda key: -hits[key])[:2]
    return '、'.join(_EMOTION_LABELS[name] for name in top)


def rule_tag_chunk(content):
    """规则打标：推断 scene_type / pacing / pov / emotion / dialogue_ratio。"""
    return {
        'scene_type': _infer_scene_type(content),
        'pacing': _infer_pacing(content),
        'pov': _infer_pov(content),
        'emotion': _infer_emotion(content),
        'dialogue_ratio': _dialogue_ratio(content),
    }
