"""提示词模板集中管理。

所有 AI 生成使用的提示词都集中在此定义，可在「提示词配置」页面修改后
持久化到 settings.prompts（覆盖默认值）。

模板使用 Python str.format 占位符（如 {title}、{content} 等）。
变量说明见 PROMPT_DEFS 中每个条目的 vars 字段（供前端展示）。
"""
import copy


# 每个提示词的元信息：key -> {label, desc, vars, default}
# default 为默认模板文本；vars 为该模板可用的占位符变量及说明。
PROMPT_DEFS = {
    "analyze_photo": {
        "label": "人物照片分析",
        "desc": "用视觉模型分析人物照片的外貌与性格",
        "vars": {},
        "default": (
            "你是一位小说角色设定师。请仔细观察这张人物照片，从两个维度分析：\n"
            "1. 外貌特征：年龄、五官、脸型、发型、身材、气质、穿着风格等。\n"
            "2. 性格推测：从神态、表情、眼神、穿着风格推测其性格气质。\n"
            "请严格按下面格式输出，不要输出其他内容：\n"
            "【外貌】具体生动的描述，80~150字\n"
            "【性格】具体生动的描述，80~150字"
        ),
    },
    "analyze_style": {
        "label": "写作风格分析",
        "desc": "从参考小说文本中提炼写作风格要点",
        "vars": {"ref": "参考小说片段文本"},
        "default": (
            "你是一位资深小说编辑。请分析下面这部小说片段的写作风格，"
            "提炼出可以指导 AI 模仿的要点，涵盖：\n"
            "1. 叙事视角（第一人称/第三人称等）\n"
            "2. 语言风格（简洁/华丽/口语化/文艺/冷峻等）\n"
            "3. 叙事节奏与段落结构\n"
            "4. 描写与修辞特点\n"
            "5. 情绪基调\n"
            "请用要点式输出，控制在 250 字以内，直接给出可执行的风格要求。\n\n"
            "参考小说片段：\n"
            "{ref}"
        ),
    },
    "generate_outline": {
        "label": "大纲生成",
        "desc": "生成故事梗概、世界观与章节大纲",
        "vars": {
            "title": "小说标题", "genre": "题材类型", "style": "写作风格",
            "chapter_count": "目标章节数", "words_per_chapter": "每章字数",
            "characters": "人物设定", "relationships": "人物关系",
        },
        "default": (
            "你是一位经验丰富的小说家。请根据以下设定，为一部小说创作完整大纲。\n\n"
            "【小说标题】{title}\n"
            "【题材类型】{genre}\n"
            "【写作风格】{style}\n"
            "【目标章节数】{chapter_count} 章\n"
            "【每章字数】约 {words_per_chapter} 字\n\n"
            "【人物设定】\n{characters}\n\n"
            "【人物关系】\n{relationships}\n\n"
            "请输出以下三部分，严格按格式：\n"
            "【故事梗概】200 字以内的完整故事脉络\n"
            "【世界观】150 字以内（现实题材可简述时代背景）\n"
            "【章节大纲】共 N 章，每章一行，格式：第1章 标题｜一句话内容概要"
        ),
    },
    "generate_chapter": {
        "label": "章节正文生成（大纲式）",
        "desc": "按设定与大纲生成单章正文",
        "vars": {
            "title": "小说标题", "n": "当前章节序号", "genre": "题材类型",
            "summary": "全书故事梗概", "world": "世界观设定", "outline": "全书章节大纲",
            "ctitle": "当前章节标题", "csummary": "当前章节概要",
            "chars": "人物设定", "rels": "人物关系", "style": "写作风格",
            "reference": "参考原文片段", "prev": "前情提要", "words": "本章目标字数",
        },
        "default": (
            "你是一位小说家。请撰写小说《{title}》的第 {n} 章，严格遵循以下全部设定。\n\n"
            "【小说标题】{title}\n"
            "【题材类型】{genre}\n"
            "【全书故事梗概】\n{summary}\n\n"
            "【世界观设定】\n{world}\n\n"
            "【全书章节大纲】\n{outline}\n\n"
            "【当前章节】第 {n} 章 {ctitle}｜{csummary}\n\n"
            "【人物设定】\n{chars}\n\n"
            "【人物关系】\n{rels}\n\n"
            "【写作风格要求】\n{style}\n"
            "【参考原文片段】\n{reference}\n\n"
            "【前情提要】\n{prev}\n\n"
            "【本章要求】\n"
            "1. 正文约 {words} 字，结构完整，有起承转合。\n"
            "2. 严格遵循人物设定、关系与世界观，不得擅自新增重要角色或改变设定。\n"
            "3. 与前情提要保持连贯，承接上一章结尾。\n"
            "4. 直接输出正文内容，不要输出章节标题、不要任何解释说明。"
        ),
    },
    "improv_chapter": {
        "label": "章节正文生成（即兴式）",
        "desc": "按写作指引（无预置大纲）生成单章正文",
        "vars": {
            "title": "小说标题", "n": "当前章节序号", "genre": "题材类型",
            "summary": "故事梗概", "background": "故事背景", "world": "世界观设定",
            "chars": "人物设定", "rels": "人物关系", "style": "写作风格",
            "reference": "参考原文片段", "prev": "前情提要",
            "referenced": "引用的前文章节", "instruction": "本章写作指引", "words": "本章目标字数",
        },
        "default": (
            "你是一位小说家，正在以「边写边定」的方式创作小说《{title}》的第 {n} 章。\n"
            "本章没有预置大纲，请根据用户的写作指引来推进情节。\n\n"
            "【小说标题】{title}\n"
            "【题材类型】{genre}\n"
            "【故事梗概】\n{summary}\n\n"
            "【故事背景】\n{background}\n\n"
            "【世界观设定】\n{world}\n\n"
            "【人物设定】\n{chars}\n\n"
            "【人物关系】\n{rels}\n\n"
            "【写作风格要求】\n{style}\n"
            "【参考原文片段】\n{reference}\n\n"
            "【前情提要】\n{prev}\n\n"
            "【引用的前文章节】\n{referenced}\n\n"
            "【本章写作指引】\n{instruction}\n\n"
            "【本章要求】\n"
            "1. 严格按写作指引推进情节，正文约 {words} 字，结构完整，有起承转合。\n"
            "2. 遵循人物设定、关系与世界观，不得擅自新增重要角色或改变设定。\n"
            "3. 与前情提要及引用的前文保持连贯，承接上一章结尾。\n"
            "4. 直接输出正文内容，不要输出章节标题、不要任何解释说明。"
        ),
    },
    "summarize_chapter": {
        "label": "章节摘要",
        "desc": "概括单章核心情节（80~120 字）",
        "vars": {"chapter_index": "章节序号", "content": "章节正文（自动截取末尾）"},
        "default": (
            "请用 80~120 字概括下面这段小说第 {chapter_index} 章的核心情节，"
            "保留关键人物与转折。只输出摘要正文本身，"
            "不要加「摘要：」等任何前缀标题，也不要在末尾标注字数：\n\n{content}"
        ),
    },
    "condense_progress": {
        "label": "前情提要浓缩",
        "desc": "前情提要过长时浓缩为连贯摘要",
        "vars": {"content": "前情提要文本（自动截取末尾）"},
        "default": (
            "请把下面这段小说的前情提要浓缩为 1200 字以内的连贯摘要，"
            "保留主线脉络和关键人物关系，直接输出：\n\n{content}"
        ),
    },
    "polish_fragment": {
        "label": "片段润色",
        "desc": "润色选中文字片段",
        "vars": {
            "title": "小说标题", "chapter_index": "章节序号", "style": "写作风格",
            "world": "世界观设定", "chars": "人物设定", "prev": "前情提要", "text": "待处理片段",
        },
        "default": (
            "你是一位小说家，正在处理小说《{title}》第 {chapter_index} 章的片段。\n\n"
            "【写作风格要求】\n{style}\n\n"
            "【世界观设定】\n{world}\n\n"
            "【人物设定】\n{chars}\n\n"
            "【前情提要】\n{prev}\n\n"
            "请在保持原意、情节与人物关系不变的前提下，对下面这段小说片段进行润色：\n"
            "1. 优化措辞与句式，使语言更流畅、更有文学性；\n"
            "2. 修正语病、逻辑不通与重复啰嗦之处；\n"
            "3. 保持原有篇幅，不擅自增删情节、不改变人物与设定；\n"
            "4. 直接输出润色后的完整片段，不要任何解释说明。\n\n"
            "【待处理片段】\n{text}"
        ),
    },
    "expand_fragment": {
        "label": "片段扩写",
        "desc": "扩写选中文字片段",
        "vars": {
            "title": "小说标题", "chapter_index": "章节序号", "style": "写作风格",
            "world": "世界观设定", "chars": "人物设定", "prev": "前情提要", "text": "待处理片段",
        },
        "default": (
            "你是一位小说家，正在处理小说《{title}》第 {chapter_index} 章的片段。\n\n"
            "【写作风格要求】\n{style}\n\n"
            "【世界观设定】\n{world}\n\n"
            "【人物设定】\n{chars}\n\n"
            "【前情提要】\n{prev}\n\n"
            "请在保持原有情节走向与人物设定的前提下，对下面这段小说片段进行扩写：\n"
            "1. 丰富细节：补充动作、神态、心理、环境描写，使画面更生动；\n"
            "2. 适当延展对话与情节，但不得新增关键角色或改变既定结局；\n"
            "3. 篇幅扩充到原文的 2~3 倍左右；\n"
            "4. 直接输出扩写后的完整片段，不要任何解释说明。\n\n"
            "【待处理片段】\n{text}"
        ),
    },
    "dialog": {
        "label": "对话模式推进",
        "desc": "对话模式中 AI 的剧情推进回应",
        "vars": {
            "title": "小说标题", "genre": "题材类型", "summary": "故事梗概",
            "background": "故事背景", "world": "世界观设定", "chars": "人物设定",
            "rels": "人物关系", "style": "写作风格", "prev": "前情提要",
            "history": "已发生的对话", "user": "作者本轮发言", "limit": "本轮期望字数",
        },
        "default": (
            "你是一位小说家，正在与作者以「对话」的方式共同创作小说《{title}》。\n"
            "作者每发一句话，你就以一段小说正文片段回应，双方像 IM 聊天一样交替推进剧情。\n\n"
            "【题材类型】{genre}\n"
            "【故事梗概】\n{summary}\n\n"
            "【故事背景】\n{background}\n\n"
            "【世界观设定】\n{world}\n\n"
            "【人物设定】\n{chars}\n\n"
            "【人物关系】\n{rels}\n\n"
            "【写作风格要求】\n{style}\n\n"
            "【前情提要】\n{prev}\n\n"
            "【已发生的对话】\n{history}\n\n"
            "【作者本轮发言】\n{user}\n\n"
            "【本轮要求】\n"
            "1. 以一段连贯的小说正文片段回应，承接作者发言与前情，推进剧情。\n"
            "2. 严格控制在 {limit} 字左右，只写本轮进展，不要一次性写完整个故事。\n"
            "3. 遵循人物设定、关系与世界观，不得擅自新增重要角色或改变设定。\n"
            "4. 直接输出正文片段，不要任何解释、不要标注「AI：」等前缀。"
        ),
    },
}


def default_prompts():
    """返回所有提示词的默认模板（key -> 模板文本）。"""
    return {k: v["default"] for k, v in PROMPT_DEFS.items()}


def get_prompt(context, key):
    """获取指定 key 的提示词模板。

    优先使用 settings.prompts 中的自定义值，否则用默认值。
    """
    custom = (context.get("settings", {}) or {}).get("prompts") or {}
    if key in custom and custom[key] and custom[key].strip():
        return custom[key]
    return PROMPT_DEFS.get(key, {}).get("default", "")


def get_all_defs():
    """返回所有提示词定义（供 API 返回元信息）。"""
    return {k: {"label": v["label"], "desc": v["desc"], "vars": v["vars"], "default": v["default"]}
            for k, v in PROMPT_DEFS.items()}
