"""小说生成引擎：风格分析、大纲生成、逐章创作、前情提要维护。"""
import re

from ai_client import chat_text, chat_text_stream, chat_vision, AIClientError


def _resolve(context, role):
    """解析当前指定使用的模型，返回 (provider, model_name, model_config)。

    role 为 "text" 或 "vision"，根据 settings 中的 text_model_id / vision_model_id
    在所有服务商的 models 列表里定位模型条目；model_config 含 type/temperature/max_tokens。
    """
    settings = context["settings"]
    providers = context["providers"]
    model_id = settings.get(f"{role}_model_id", "")
    for p in providers:
        for m in p.get("models", []):
            if m.get("id") == model_id:
                return p, m.get("name", "").strip(), m
    label = "视觉分析" if role == "vision" else "文本生成"
    raise AIClientError(
        f"未指定{label}使用的模型，请在「API 配置」页为服务商添加模型并点「设为当前」。"
    )


def _temperature(context, mcfg=None):
    """模型条目配置的 temperature 优先，否则用全局默认。"""
    v = (mcfg or {}).get("temperature")
    if v in (None, ""):
        v = context["settings"].get("temperature", 0.8)
    return float(v)


def _global_prompt(context):
    """全局前置提示词（附加到所有生成请求）。"""
    return (context.get("settings", {}).get("global_prompt") or "").strip()


def _messages(context, prompt):
    """构造 messages：若配置了全局前置提示词，则作为 system 消息前置。"""
    gp = _global_prompt(context)
    if gp:
        return [
            {"role": "system", "content": gp},
            {"role": "user", "content": prompt},
        ]
    return [{"role": "user", "content": prompt}]


def _prepend_global(context, prompt):
    """把全局前置提示词拼到 prompt 文本前（用于视觉等不支持 system 的场景）。"""
    gp = _global_prompt(context)
    if gp:
        return f"{gp}\n\n{prompt}"
    return prompt


def _context_limit(context, mcfg=None, max_tokens=None):
    """计算可用于「输入」的 token 上限 = 模型上下文长度 - 保留给输出的 token。

    未配置 context_length 时返回 None（不截断）。
    """
    cl = (mcfg or {}).get("context_length")
    if not cl:
        return None
    cl = int(cl)
    reserve = max_tokens or 2048
    return max(cl - reserve, 1024)


def _truncate_text(text, max_chars):
    """按字符数粗略截断文本（中文 1 字 ≈ 1 token，保守截断）。"""
    if not text or max_chars is None:
        return text
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n……（因上下文长度限制已截断）"


def analyze_photo(context, image_base64):
    """用视觉模型分析人物照片，返回 {appearance, personality}。"""
    provider, model, mcfg = _resolve(context, "vision")
    prompt = (
        "你是一位小说角色设定师。请仔细观察这张人物照片，从两个维度分析：\n"
        "1. 外貌特征：年龄、五官、脸型、发型、身材、气质、穿着风格等。\n"
        "2. 性格推测：从神态、表情、眼神、穿着风格推测其性格气质。\n"
        "请严格按下面格式输出，不要输出其他内容：\n"
        "【外貌】具体生动的描述，80~150字\n"
        "【性格】具体生动的描述，80~150字"
    )
    content, _ = chat_vision(provider, model, _prepend_global(context, prompt), image_base64,
                             temperature=_temperature(context, mcfg), name="分析照片")
    appearance, personality = _parse_two_fields(content)
    return {"appearance": appearance, "personality": personality}


def analyze_style(context, reference_text):
    """从参考小说文本中提炼写作风格要点。"""
    provider, model, mcfg = _resolve(context, "text")
    # 根据模型上下文长度截断参考文本（默认最多 6000 字）
    limit = _context_limit(context, mcfg)
    ref = reference_text[: limit if limit else 6000]
    prompt = (
        "你是一位资深小说编辑。请分析下面这部小说片段的写作风格，"
        "提炼出可以指导 AI 模仿的要点，涵盖：\n"
        "1. 叙事视角（第一人称/第三人称等）\n"
        "2. 语言风格（简洁/华丽/口语化/文艺/冷峻等）\n"
        "3. 叙事节奏与段落结构\n"
        "4. 描写与修辞特点\n"
        "5. 情绪基调\n"
        "请用要点式输出，控制在 250 字以内，直接给出可执行的风格要求。\n\n"
        "参考小说片段：\n"
        f"{ref}"
    )
    content, _ = chat_text(provider, model, _messages(context, prompt),
                           temperature=_temperature(context, mcfg), name="分析风格")
    return content.strip()


def generate_outline(context, novel):
    """生成故事梗概 + 世界观 + 章节大纲，返回 dict。"""
    provider, model, mcfg = _resolve(context, "text")
    characters_info = _format_characters(context, novel)
    relationships_info = _format_relationships(context, novel)
    style = novel.get("style") or "文笔流畅自然，情节紧凑，人物鲜明。"

    prompt = (
        "你是一位经验丰富的小说家。请根据以下设定，为一部小说创作完整大纲。\n\n"
        f"【小说标题】{novel.get('title') or '未命名'}\n"
        f"【题材类型】{novel.get('genre') or '不限'}\n"
        f"【写作风格】{style}\n"
        f"【目标章节数】{novel.get('chapter_count', 10)} 章\n"
        f"【每章字数】约 {novel.get('words_per_chapter', 2000)} 字\n\n"
        f"【人物设定】\n{characters_info}\n\n"
        f"【人物关系】\n{relationships_info}\n\n"
        "请输出以下三部分，严格按格式：\n"
        "【故事梗概】200 字以内的完整故事脉络\n"
        "【世界观】150 字以内（现实题材可简述时代背景）\n"
        "【章节大纲】共 N 章，每章一行，格式：第1章 标题｜一句话内容概要"
    )
    content, _ = chat_text(provider, model, _messages(context, prompt),
                           temperature=_temperature(context, mcfg), name="生成大纲")
    return _parse_outline(content, novel.get("chapter_count", 10))


def _chapter_prompt_and_params(context, novel, chapter_index):
    """构造单章生成的 prompt、目标字数、max_tokens（供同步/流式共用）。"""
    provider, model, mcfg = _resolve(context, "text")
    chapters = novel.get("chapters", [])
    chapter = chapters[chapter_index - 1]
    words = int(novel.get("words_per_chapter", 2000))
    # max_tokens：模型条目显式配置优先，否则按目标字数×系数估算
    max_tokens = mcfg.get("max_tokens")
    if not max_tokens:
        max_tokens = max(512, int(words * float(context["settings"].get("token_ratio", 1.6))))

    characters_info = _format_characters(context, novel)
    relationships_info = _format_relationships(context, novel)
    style = novel.get("style") or "文笔流畅自然，情节紧凑，人物鲜明。"

    # 前情提要：净化（只保留规范摘要条目）并排除当前章节自己的旧摘要，
    # 避免已删除/旧章节内容残留后被上传给模型。
    limit = _context_limit(context, mcfg, max_tokens)
    prev = _clean_progress(novel.get("progress_summary"))
    if chapter_index > 1 and prev:
        # 排除当前章节（及之后章节）的旧摘要，只保留前文的规范摘要
        prev_lines = [ln for ln in prev.split("\n")
                      if not ln.startswith(f"第{chapter_index}章：")]
        prev = "\n".join(prev_lines)
    if not prev:
        prev = "（这是第一章，无前情。）" if chapter_index == 1 else "（暂无前情提要）"
    if limit:
        # 前情提要占用预留一半的输入空间（人物/大纲等也占空间）
        prev = _truncate_text(prev, max(int(limit * 0.6), 500))

    genre = novel.get("genre") or "不限"
    worldbuilding = novel.get("worldbuilding") or ""

    # 参考文本（原著片段）：截断到 2000 字，避免撑爆上下文
    reference = novel.get("reference_text") or ""
    if reference:
        reference = _truncate_text(reference, 2000)

    prompt = (
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
    ).format(
        title=novel.get("title") or "未命名",
        n=chapter_index,
        genre=genre,
        summary=novel.get("summary") or "（暂无）",
        world=worldbuilding or "（暂无世界观设定）",
        outline=_format_outline(chapters),
        ctitle=chapter.get("title", ""),
        csummary=chapter.get("summary", ""),
        chars=characters_info,
        rels=relationships_info,
        style=style,
        reference=reference or "（无）",
        prev=prev,
        words=words,
    )
    return provider, model, mcfg, prompt, words, max_tokens


def generate_chapter(context, novel, chapter_index):
    """生成指定章节，返回 (chapter_dict, chapter_summary)。"""
    provider, model, mcfg, prompt, words, max_tokens = _chapter_prompt_and_params(
        context, novel, chapter_index)
    chapters = novel.get("chapters", [])
    chapter = chapters[chapter_index - 1]

    content, usage = chat_text(
        provider, model,
        _messages(context, prompt),
        temperature=_temperature(context, mcfg),
        max_tokens=max_tokens,
        name="生成章节",
    )
    content = content.strip()

    # 生成本章摘要（用于前情提要）
    summary = _summarize_chapter(context, content, chapter_index)
    return {"index": chapter_index,
            "title": chapter.get("title", ""),
            "summary": chapter.get("summary", ""),
            "content": content, "word_count": _count_chinese(content)}, summary


def stream_chapter(context, novel, chapter_index):
    """流式生成指定章节，yield 事件 dict：
        {"type":"delta","content":...}            正文实时增量
        {"type":"chapter_done","content":...,"word_count":...}  正文完成
        {"type":"summary","summary":...}          章节摘要（供前情提要）
    """
    provider, model, mcfg, prompt, words, max_tokens = _chapter_prompt_and_params(
        context, novel, chapter_index)

    parts = []
    for delta in chat_text_stream(
            provider, model, _messages(context, prompt),
            temperature=_temperature(context, mcfg),
            max_tokens=max_tokens, name="生成章节"):
        parts.append(delta)
        yield {"type": "delta", "content": delta}

    content = "".join(parts).strip()
    yield {"type": "chapter_done", "content": content, "word_count": _count_chinese(content)}
    yield {"type": "summary", "summary": _summarize_chapter(context, content, chapter_index)}


def _improv_chapter_prompt_and_params(context, novel, chapter_index, instruction, context_chapters=None):
    """构造「即兴交互式」章节的 prompt（无预置大纲，用用户写作指引）。

    context_chapters: 用户选择引用的前文章节列表，形如
        [{"index": 1, "mode": "full"|"summary"}, ...]
    生成时把选中章节的完整内容或摘要拼入 prompt。
    """
    provider, model, mcfg = _resolve(context, "text")
    words = int(novel.get("words_per_chapter", 2000))
    max_tokens = mcfg.get("max_tokens")
    if not max_tokens:
        max_tokens = max(512, int(words * float(context["settings"].get("token_ratio", 1.6))))

    characters_info = _format_characters(context, novel)
    relationships_info = _format_relationships(context, novel)
    style = novel.get("style") or "文笔流畅自然，情节紧凑，人物鲜明。"

    limit = _context_limit(context, mcfg, max_tokens)
    prev = _clean_progress(novel.get("progress_summary"))
    if not prev:
        prev = "（这是第一章，无前情。）"
    if limit:
        prev = _truncate_text(prev, max(int(limit * 0.6), 500))

    genre = novel.get("genre") or "不限"
    worldbuilding = novel.get("worldbuilding") or ""
    background = novel.get("background") or ""
    reference = novel.get("reference_text") or ""
    if reference:
        reference = _truncate_text(reference, 2000)

    # 构造引用的前文章节内容
    referenced = ""
    if context_chapters:
        all_chapters = novel.get("chapters", [])
        parts = []
        for ref in context_chapters:
            idx = ref.get("index")
            mode = ref.get("mode", "summary")
            ch = next((c for c in all_chapters if c.get("index") == idx), None)
            if not ch:
                continue
            if mode == "full" and ch.get("content"):
                parts.append(f"【第{idx}章 完整内容】\n{ch['content']}")
            elif ch.get("summary"):
                parts.append(f"【第{idx}章 摘要】\n{ch['summary']}")
            elif ch.get("content"):
                # 无摘要时用正文尾部片段作为摘要
                parts.append(f"【第{idx}章 内容节选】\n{ch['content'][-1500:]}")
        if parts:
            referenced = "\n\n".join(parts)
    if referenced and limit:
        referenced = _truncate_text(referenced, int(limit * 0.5))

    prompt = (
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
    ).format(
        title=novel.get("title") or "未命名",
        n=chapter_index,
        genre=genre,
        summary=novel.get("summary") or "（暂无）",
        background=background or "（暂无背景设定）",
        world=worldbuilding or "（暂无世界观设定）",
        chars=characters_info,
        rels=relationships_info,
        style=style,
        reference=reference or "（无）",
        prev=prev,
        referenced=referenced or "（无）",
        instruction=instruction or "（无特别指引，请自然推进剧情）",
        words=words,
    )
    return provider, model, mcfg, prompt, words, max_tokens


def improv_chapter_stream(context, novel, chapter_index, instruction, context_chapters=None):
    """即兴交互式：流式生成章节（无预置大纲），yield 事件同 stream_chapter。"""
    provider, model, mcfg, prompt, words, max_tokens = _improv_chapter_prompt_and_params(
        context, novel, chapter_index, instruction, context_chapters)

    parts = []
    for delta in chat_text_stream(
            provider, model, _messages(context, prompt),
            temperature=_temperature(context, mcfg),
            max_tokens=max_tokens, name="生成章节"):
        parts.append(delta)
        yield {"type": "delta", "content": delta}

    content = "".join(parts).strip()
    yield {"type": "chapter_done", "content": content, "word_count": _count_chinese(content)}
    yield {"type": "summary", "summary": _summarize_chapter(context, content, chapter_index)}


def _summarize_chapter(context, content, chapter_index):
    """生成单章 100 字左右摘要（失败静默返回空，供生成流程用）。"""
    try:
        return summarize_chapter_content(context, content, chapter_index)
    except AIClientError:
        # 摘要失败不阻断主流程
        return ""


def summarize_chapter_content(context, content, chapter_index, max_retries=2):
    """生成单章 100 字左右摘要（失败抛异常，供独立摘要接口用）。

    模型偶发空响应时自动重试（最多 max_retries 次）。
    """
    provider, model, mcfg = _resolve(context, "text")
    prompt = (
        f"请用 80~120 字概括下面这段小说第 {chapter_index} 章的核心情节，"
        "保留关键人物与转折。只输出摘要正文本身，"
        "不要加「摘要：」等任何前缀标题，也不要在末尾标注字数：\n\n" + content[-4000:]
    )
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            s, _ = chat_text(provider, model, _messages(context, prompt),
                             temperature=_temperature(context, mcfg), max_tokens=300,
                             name="生成摘要")
            if s and s.strip():
                return s.strip()
            last_err = "模型返回空内容"
        except AIClientError as e:
            last_err = str(e)
    raise AIClientError(f"摘要生成失败（重试 {max_retries + 1} 次仍失败）：{last_err}")


def condense_progress(context, progress_summary):
    """当前情提要过长时，浓缩为连贯摘要。"""
    provider, model, mcfg = _resolve(context, "text")
    prompt = (
        "请把下面这段小说的前情提要浓缩为 1200 字以内的连贯摘要，"
        "保留主线脉络和关键人物关系，直接输出：\n\n" + progress_summary[-8000:]
    )
    s, _ = chat_text(provider, model, _messages(context, prompt),
                     temperature=_temperature(context, mcfg), max_tokens=2000, name="浓缩前情")
    return s.strip()


def _clean_progress(progress_summary):
    """净化前情提要：只保留规范格式「第N章：摘要」的条目。

    丢弃所有不规范内容（AI 拒绝文本、无前缀段落、空行等），
    避免旧内容残留并被重复上传给模型。
    """
    import re as _re
    if not progress_summary:
        return ""
    entries = []
    for ln in progress_summary.split("\n"):
        s = ln.strip()
        if not s:
            continue
        # 只保留「第N章：...」格式的规范摘要
        if _re.match(r"^第\d+章[:：]", s):
            entries.append(s)
    return "\n".join(entries)


def replace_progress_entry(progress_summary, chapter_index, new_summary):
    """替换前情提要中指定章节的摘要条目（重新生成时避免重复累积旧内容）。

    前情提要按行组织，每行形如「第N章：摘要」。重新生成第 N 章时，
    先净化（丢弃垃圾内容）、移除旧的「第N章：...」行，再追加新摘要，
    确保旧章节内容不会残留在前情提要中被后续章节或重生成引用。
    """
    marker = f"第{chapter_index}章："
    kept = []
    for ln in _clean_progress(progress_summary).split("\n"):
        if ln and not ln.startswith(marker):
            kept.append(ln)
    if new_summary and new_summary.strip():
        kept.append(f"第{chapter_index}章：{new_summary.strip()}")
    return "\n".join(kept).strip()


# ---------- 格式化与解析辅助 ----------

def _format_characters(context, novel):
    chars = []
    for c in context["characters"]:
        if c.get("id") in novel.get("character_ids", []):
            parts = [f"· {c.get('name') or '未命名'}"]
            if c.get("appearance"):
                parts.append(f"  外貌：{c['appearance']}")
            if c.get("personality"):
                parts.append(f"  性格：{c['personality']}")
            if c.get("background"):
                parts.append(f"  背景：{c['background']}")
            if c.get("notes"):
                parts.append(f"  补充：{c['notes']}")
            chars.append("\n".join(parts))
    return "\n".join(chars) if chars else "（暂无人物设定）"


def _format_relationships(context, novel):
    rels = novel.get("relationships", []) or []
    if not rels:
        return "（暂无关系设定）"
    name_map = {c.get("id"): c.get("name") for c in context["characters"]}
    lines = []
    for r in rels:
        a = name_map.get(r.get("char1_id"), "?")
        b = name_map.get(r.get("char2_id"), "?")
        lines.append(f"· {a} ↔ {b}：{r.get('type') or '关系'} —— {r.get('description') or ''}")
    return "\n".join(lines)


def _format_outline(chapters):
    if not chapters:
        return "（暂无大纲）"
    return "\n".join(f"第{c['index']}章 {c.get('title','')}｜{c.get('summary','')}"
                     for c in chapters)


def _parse_two_fields(text):
    appearance, personality = "", ""
    m = re.search(r"【外貌】([\s\S]*?)(?=【性格】|$)", text)
    if m:
        appearance = m.group(1).strip()
    m = re.search(r"【性格】([\s\S]*)", text)
    if m:
        personality = m.group(1).strip()
    # 兜底：如果模型没按格式输出，整段当作外貌+性格拆分
    if not appearance and not personality:
        appearance, personality = text.strip(), ""
    return appearance, personality


def _parse_outline(text, chapter_count):
    summary, worldbuilding = "", ""
    m = re.search(r"【故事梗概】([\s\S]*?)(?=【世界观】|【章节大纲】|$)", text)
    if m:
        summary = m.group(1).strip()
    m = re.search(r"【世界观】([\s\S]*?)(?=【章节大纲】|$)", text)
    if m:
        worldbuilding = m.group(1).strip()

    outline_block = ""
    m = re.search(r"【章节大纲】([\s\S]*)", text)
    if m:
        outline_block = m.group(1)

    chapters = []
    # 匹配 "第N章 标题｜概要" 或 "第N章 标题：概要"
    pat = re.compile(r"第\s*(\d+)\s*章[\.、\s:：]*(.*?)(?=第\s*\d+\s*章|$)", re.S)
    for m in pat.finditer(outline_block):
        idx = int(m.group(1))
        raw = m.group(2).strip()
        title, sep, csummary = raw.partition("｜")
        if not sep:
            title, sep, csummary = raw.partition("：")
        if not sep:
            title, sep, csummary = raw.partition(":")
        chapters.append({
            "index": idx,
            "title": (title or "").strip(),
            "summary": (csummary or "").strip(),
        })

    # 数量不足时补齐占位章节
    if len(chapters) < chapter_count:
        existing = {c["index"] for c in chapters}
        for i in range(1, chapter_count + 1):
            if i not in existing:
                chapters.append({"index": i, "title": f"第{i}章", "summary": ""})
        chapters.sort(key=lambda c: c["index"])
    # 数量超过时截断
    chapters = chapters[:chapter_count]
    # 重新规整 index
    for i, c in enumerate(chapters, 1):
        c["index"] = i
    return {"summary": summary, "worldbuilding": worldbuilding, "chapters": chapters}


def _count_chinese(text):
    return len(re.findall(r"[\u4e00-\u9fff]", text))


# ---------- 节选片段润色 / 扩写 ----------

def _fragment_context(context, novel):
    """构造片段润色/扩写时的小说设定上下文（人物/风格/世界观/前情提要）。"""
    chars = _format_characters(context, novel)
    style = novel.get("style") or "文笔流畅自然，情节紧凑，人物鲜明。"
    worldbuilding = novel.get("worldbuilding") or "（暂无世界观设定）"
    prev = _clean_progress(novel.get("progress_summary")) or "（暂无前情）"
    return {
        "style": style,
        "worldbuilding": worldbuilding,
        "characters": chars,
        "prev": prev,
    }


def _fragment_prompt(context, novel, chapter_index, text, action):
    """构造润色 / 扩写 prompt。action: 'polish' | 'expand'。"""
    info = _fragment_context(context, novel)
    if action == "polish":
        task = (
            "请在保持原意、情节与人物关系不变的前提下，对下面这段小说片段进行润色：\n"
            "1. 优化措辞与句式，使语言更流畅、更有文学性；\n"
            "2. 修正语病、逻辑不通与重复啰嗦之处；\n"
            "3. 保持原有篇幅，不擅自增删情节、不改变人物与设定；\n"
            "4. 直接输出润色后的完整片段，不要任何解释说明。"
        )
    else:
        task = (
            "请在保持原有情节走向与人物设定的前提下，对下面这段小说片段进行扩写：\n"
            "1. 丰富细节：补充动作、神态、心理、环境描写，使画面更生动；\n"
            "2. 适当延展对话与情节，但不得新增关键角色或改变既定结局；\n"
            "3. 篇幅扩充到原文的 2~3 倍左右；\n"
            "4. 直接输出扩写后的完整片段，不要任何解释说明。"
        )
    return (
        f"你是一位小说家，正在处理小说《{novel.get('title') or '未命名'}》第 {chapter_index} 章的片段。\n\n"
        "【写作风格要求】\n{style}\n\n"
        "【世界观设定】\n{world}\n\n"
        "【人物设定】\n{chars}\n\n"
        "【前情提要】\n{prev}\n\n"
        "{task}\n\n"
        "【待处理片段】\n{text}"
    ).format(style=info["style"], world=info["worldbuilding"],
             chars=info["characters"], prev=info["prev"], task=task, text=text)


def _fragment_stream(context, novel, chapter_index, text, action):
    """流式生成润色/扩写结果，yield 增量。"""
    provider, model, mcfg = _resolve(context, "text")
    prompt = _fragment_prompt(context, novel, chapter_index, text, action)
    max_tokens = mcfg.get("max_tokens") or max(512, int(len(text) * 1.6 * 2))
    name = "润色片段" if action == "polish" else "扩写片段"
    for delta in chat_text_stream(
            provider, model, _messages(context, prompt),
            temperature=_temperature(context, mcfg),
            max_tokens=max_tokens, name=name):
        yield {"type": "delta", "content": delta}


def polish_fragment_stream(context, novel, chapter_index, text):
    """润色片段（流式）。"""
    return _fragment_stream(context, novel, chapter_index, text, "polish")


def expand_fragment_stream(context, novel, chapter_index, text):
    """扩写片段（流式）。"""
    return _fragment_stream(context, novel, chapter_index, text, "expand")


# ---------- 对话模式（IM 聊天式推进剧情） ----------

def _format_dialog_history(messages, max_turns=20):
    """把对话历史格式化为 prompt 文本（只取最近 max_turns 轮，控制长度）。"""
    if not messages:
        return "（尚无对话，这是第一轮，请根据设定开启故事。）"
    recent = messages[-max_turns:]
    lines = []
    for m in recent:
        role = "作者" if m.get("role") == "user" else "AI"
        lines.append(f"{role}：{m.get('content', '')}")
    return "\n".join(lines)


def _dialog_prompt(context, novel, user_text, history):
    """构造对话模式的 prompt：每次输出 ≤500 字，以剧情片段推进。"""
    chars = _format_characters(context, novel)
    rels = _format_relationships(context, novel)
    style = novel.get("style") or "文笔流畅自然，情节紧凑，人物鲜明。"
    worldbuilding = novel.get("worldbuilding") or "（暂无世界观设定）"
    background = novel.get("background") or "（暂无背景设定）"
    prev = _clean_progress(novel.get("progress_summary")) or "（暂无前情）"
    history_text = _format_dialog_history(history)

    return (
        f"你是一位小说家，正在与作者以「对话」的方式共同创作小说《{novel.get('title') or '未命名'}》。\n"
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
        "2. 严格控制在 500 字以内（约 300~500 字），只写本轮进展，不要一次性写完整个故事。\n"
        "3. 遵循人物设定、关系与世界观，不得擅自新增重要角色或改变设定。\n"
        "4. 直接输出正文片段，不要任何解释、不要标注「AI：」等前缀。"
    ).format(
        genre=novel.get("genre") or "不限",
        summary=novel.get("summary") or "（暂无）",
        background=background,
        world=worldbuilding,
        chars=chars,
        rels=rels,
        style=style,
        prev=prev,
        history=history_text,
        user=user_text,
    )


def dialog_stream(context, novel, user_text, history):
    """对话模式：流式生成一段 ≤500 字的剧情片段。"""
    provider, model, mcfg = _resolve(context, "text")
    prompt = _dialog_prompt(context, novel, user_text, history)
    # 500 字 ≈ 750 token（中文 1 字 ≈ 1.5 token），留足余量
    max_tokens = mcfg.get("max_tokens") or 900
    for delta in chat_text_stream(
            provider, model, _messages(context, prompt),
            temperature=_temperature(context, mcfg),
            max_tokens=max_tokens, name="对话推进"):
        yield {"type": "delta", "content": delta}



