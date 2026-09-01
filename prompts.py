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
            "1. 外貌特征：年龄、五官、脸型、发型、气质，并给出具体的身材描写（如身高、体型、胸围、腰臀比例等可参考的细节）。\n"
            "2. 性格推测：从神态、表情、眼神、穿着风格推测其性格气质。\n"
            "注意：衣着部分请描述她/他「平时喜欢或习惯穿什么」的风格，而不是仅描述照片中这一件。\n"
            "请严格按下面格式输出，不要输出其他内容：\n"
            "【外貌】具体生动的描述（含具体身材描写与日常穿着习惯），100~200字\n"
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
            "background": "故事背景", "world": "世界观设定", "reference": "参考文本",
            "chapter_count": "目标章节数", "words_per_chapter": "每章字数",
            "characters": "人物设定", "relationships": "人物关系",
        },
        "default": (
            "你是一位经验丰富的小说家。请根据以下设定，为一部小说创作完整大纲。\n\n"
            "【小说标题】{title}\n"
            "【题材类型】{genre}\n"
            "【写作风格】{style}\n"
            "【故事背景】\n{background}\n\n"
            "【世界观设定】\n{world}\n\n"
            "【参考文本】\n{reference}\n\n"
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
            "summary": "全书故事梗概", "background": "故事背景", "world": "世界观设定", "outline": "全书章节大纲",
            "ctitle": "当前章节标题", "csummary": "当前章节概要",
            "chars": "人物设定", "rels": "人物关系", "style": "写作风格",
            "reference": "参考原文片段", "prev": "前情提要", "words": "本章目标字数",
        },
        "default": (
            "你是一位小说家。请撰写小说《{title}》的第 {n} 章，严格遵循以下全部设定。\n\n"
            "【小说标题】{title}\n"
            "【题材类型】{genre}\n"
            "【全书故事梗概】\n{summary}\n\n"
            "【故事背景】\n{background}\n\n"
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
    "rewrite_chapter": {
        "label": "改写章节（改写模式）",
        "desc": "按改写要求改写导入原文的单章/片段",
        "vars": {
            "title": "小说标题", "n": "当前章节序号", "instruction": "改写要求",
            "text": "本章原文", "style": "写作风格", "world": "世界观设定",
            "chars": "人物设定", "background": "故事背景",
        },
        "default": (
            "你是一位小说家，正在按要求改写小说《{title}》的第 {n} 章。\n\n"
            "【改写要求】\n{instruction}\n\n"
            "【写作风格要求】\n{style}\n\n"
            "【故事背景】\n{background}\n\n"
            "【世界观设定】\n{world}\n\n"
            "【人物设定】\n{chars}\n\n"
            "【本章原文】\n{text}\n\n"
            "请在保持原有情节脉络、人物与核心信息不变的前提下，严格按照上面的「改写要求」改写这段原文：\n"
            "1. 完整落实改写要求中的全部要点（如人称、文风、篇幅、时代背景等）；\n"
            "2. 语言流畅自然，结构完整；\n"
            "3. 直接输出改写后的完整正文，不要输出任何解释，不要标注「改写后」等前缀。"
        ),
    },
    "continue_chapter": {
        "label": "续写章节（续写模式）",
        "desc": "以导入原文为前情，续写后续章节",
        "vars": {
            "title": "小说标题", "n": "当前章节序号", "genre": "题材类型",
            "instruction": "续写要求", "source": "已有故事原文", "prev": "已续写前情",
            "chars": "人物设定", "rels": "人物关系", "words": "本章目标字数",
        },
        "default": (
            "你是一位小说家，正在为一部已有故事续写后续章节。\n\n"
            "【小说标题】{title}\n"
            "【题材类型】{genre}\n"
            "【人物设定】\n{chars}\n\n"
            "【人物关系】\n{rels}\n\n"
            "【已有故事原文】\n{source}\n\n"
            "【已续写的前情】\n{prev}\n\n"
            "【续写要求】\n{instruction}\n\n"
            "【本章要求】\n"
            "1. 严格承接原文的结尾与全部设定，续写第 {n} 章，正文约 {words} 字，结构完整，有起承转合。\n"
            "2. 故事背景、世界观、人物设定与写作风格一律继承原小说（从「已有故事原文」推断），不得擅自新增重要角色或改变既有设定。\n"
            "3. 直接输出续写的正文内容，不要输出章节标题、不要任何解释说明。"
        ),
    },
    "analyze_source": {
        "label": "原著结构化拆解（续写模式）",
        "desc": "分析整本原著全文，提取人物档案/世界观/主线框架/脉络摘要的严格 JSON",
        "vars": {"source": "原著全文文本"},
        "default": (
            "任务：分析下面整本小说原文，提取结构化故事档案，输出严格标准JSON，禁止额外解释文字。\n\n"
            "提取规则：\n"
            "1.人物档案 characters[]\n"
            "每一个人物包含：\n"
            "{{\n"
            "\"name\":\"角色名\",\n"
            "\"core_personality\":\"核心性格，不可动摇，3-8条短句\",\n"
            "\"speaking_style\":\"说话语气、口头禅、语言习惯\",\n"
            "\"key_history\":\"原著内该角色已经发生过的重大经历、恩怨、创伤\",\n"
            "\"relationship\":\"和其他关键人物的关系、立场、爱恨\",\n"
            "\"current_state\":\"截至原著结尾，该角色身体状态、拥有物品、所处位置、修为实力\",\n"
            "\"taboo\":\"该人物绝对不会做出的行为清单（防OOC核心）\"\n"
            "}}\n\n"
            "2.世界观设定 world_setting\n"
            "{{\n"
            "\"world_rules\":\"世界底层规则，修炼等级、魔法规则、社会制度、禁忌，后续续写不得违背\",\n"
            "\"geography\":\"重要地域以及对应的背景\",\n"
            "\"forces\":\"各大势力、阵营、立场、敌对关系\",\n"
            "\"noun_glossary\":\"全书专有名词清单，名词-含义对照表，续写不可重定义\"\n"
            "}}\n\n"
            "3.主线框架 main_frame\n"
            "{{\n"
            "\"core_theme\":\"小说核心主题\",\n"
            "\"protagonist_goal\":\"主角最终长期目标，续写不可随意废弃\",\n"
            "\"main_conflict\":\"全书核心矛盾冲突，大框架不能推翻\",\n"
            "\"foreshadowing_list\":[\"清单：原著埋下尚未回收的所有伏笔，后续续写需要优先记得回收\"],\n"
            "\"story_tone\":\"全书文风基调：严肃/轻松/暗黑/热血；叙事节奏、文笔风格特征\"\n"
            "}}\n\n"
            "4.全书脉络摘要 summary\n"
            "{{\n"
            "\"full_outline\":\"全书浓缩长摘要（2000字以内）\",\n"
            "\"chapter_summaries\":[{{\"chapter\":\"章节号\",\"brief\":\"本章发生关键事件摘要\"}}]\n"
            "}}\n\n"
            "约束：所有提取内容100%忠于原文，不得脑补原创设定。\n"
            "下面是小说原文：\n"
            "{source}"
        ),
    },
    "analyze_source_partial": {
        "label": "原著分块拆解（续写模式，超长原文按块拆分）",
        "desc": "对原著的其中一个片段做结构化拆解，输出同构的局部故事档案 JSON",
        "vars": {"block": "原著的某一个片段文本"},
        "default": (
            "任务：下面这段文本是整本小说的其中一个片段（可能不完整）。请只依据这段内容本身，提取这段内容涉及的故事档案，输出严格标准JSON，禁止额外解释文字。\n\n"
            "提取规则（结构与全书拆解一致，但每个字段只覆盖这段片段本身的信息）：\n"
            "1.人物档案 characters[]\n"
            "每一个人物包含：\n"
            "{{\n"
            "\"name\":\"角色名\",\n"
            "\"core_personality\":\"核心性格，不可动摇，3-8条短句\",\n"
            "\"speaking_style\":\"说话语气、口头禅、语言习惯\",\n"
            "\"key_history\":\"这段片段里该角色发生过的重大经历、恩怨、创伤\",\n"
            "\"relationship\":\"和其他关键人物的关系、立场、爱恨\",\n"
            "\"current_state\":\"这段片段结尾处，该角色身体状态、拥有物品、所处位置、修为实力\",\n"
            "\"taboo\":\"该人物绝对不会做出的行为清单（防OOC核心）\"\n"
            "}}\n\n"
            "2.世界观设定 world_setting\n"
            "{{\n"
            "\"world_rules\":\"这段片段涉及的世界底层规则、修炼等级、社会制度、禁忌\",\n"
            "\"geography\":\"这段片段涉及的重要地域及背景\",\n"
            "\"forces\":\"这段片段涉及的势力、阵营、立场\",\n"
            "\"noun_glossary\":\"这段片段涉及的专有名词及含义\"\n"
            "}}\n\n"
            "3.主线框架 main_frame\n"
            "{{\n"
            "\"core_theme\":\"这段片段体现的主题\",\n"
            "\"protagonist_goal\":\"主角在这段片段中的目标\",\n"
            "\"main_conflict\":\"这段片段的核心矛盾冲突\",\n"
            "\"foreshadowing_list\":[\"这段片段埋下的伏笔\"],\n"
            "\"story_tone\":\"这段片段的文风基调\"\n"
            "}}\n\n"
            "4.全书脉络摘要 summary\n"
            "{{\n"
            "\"full_outline\":\"这段片段的浓缩摘要（500字以内）\",\n"
            "\"chapter_summaries\":[{{\"chapter\":\"章节号\",\"brief\":\"本章发生关键事件摘要\"}}]\n"
            "}}\n\n"
            "约束：所有提取内容100%忠于这段原文，不得脑补原创设定。\n"
            "下面是这段小说原文：\n"
            "{block}"
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
