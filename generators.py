"""小说生成引擎：风格分析、大纲生成、逐章创作、前情提要维护。"""
import re

from ai_client import chat_text, chat_text_stream, chat_vision, AIClientError
from prompts import get_prompt


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
    prompt = get_prompt(context, "analyze_photo")
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
    prompt = get_prompt(context, "analyze_style").format(ref=ref)
    content, _ = chat_text(provider, model, _messages(context, prompt),
                           temperature=_temperature(context, mcfg), name="分析风格")
    return content.strip()


def generate_outline(context, novel):
    """生成故事梗概 + 世界观 + 章节大纲，返回 dict。"""
    provider, model, mcfg = _resolve(context, "text")
    characters_info = _format_characters(context, novel)
    relationships_info = _format_relationships(context, novel)
    style = novel.get("style") or "文笔流畅自然，情节紧凑，人物鲜明。"
    background = novel.get("background") or ""
    worldbuilding = novel.get("worldbuilding") or ""
    reference = novel.get("reference_text") or ""
    # 参考文本只作补充素材，截断避免撑爆上下文
    if reference:
        reference = _truncate_text(reference, 6000)

    prompt = get_prompt(context, "generate_outline").format(
        title=novel.get("title") or "未命名",
        genre=novel.get("genre") or "不限",
        style=style,
        background=background or "（暂无背景设定）",
        world=worldbuilding or "（暂无世界观设定）",
        reference=reference or "（无）",
        chapter_count=novel.get("chapter_count", 10),
        words_per_chapter=novel.get("words_per_chapter", 2000),
        characters=characters_info,
        relationships=relationships_info,
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
    background = novel.get("background") or ""

    # 参考文本（原著片段）：截断到 2000 字，避免撑爆上下文
    reference = novel.get("reference_text") or ""
    if reference:
        reference = _truncate_text(reference, 2000)

    prompt = get_prompt(context, "generate_chapter").format(
        title=novel.get("title") or "未命名",
        n=chapter_index,
        genre=genre,
        summary=novel.get("summary") or "（暂无）",
        background=background or "（暂无背景设定）",
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
    # 注入世界书条目（动态匹配关键词）
    wb_context = f"{chapter.get('title', '')} {chapter.get('summary', '')} {prev}"
    if chapter_index > 1:
        prev_chapter = chapters[chapter_index - 2] if chapter_index - 2 < len(chapters) else None
        if prev_chapter and prev_chapter.get("content"):
            wb_context += " " + prev_chapter["content"][-500:]
    wb_text = _format_worldbooks(context, only_constant=False, context_text=wb_context)
    if wb_text:
        prompt += "\n\n【世界书设定】\n" + wb_text
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

    prompt = get_prompt(context, "improv_chapter").format(
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
    # 注入世界书条目（动态匹配关键词）
    wb_context = f"{instruction} {prev} {referenced}"
    wb_text = _format_worldbooks(context, only_constant=False, context_text=wb_context)
    if wb_text:
        prompt += "\n\n【世界书设定】\n" + wb_text
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
    prompt = get_prompt(context, "summarize_chapter").format(
        chapter_index=chapter_index, content=content[-4000:])
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
    prompt = get_prompt(context, "condense_progress").format(
        content=progress_summary[-8000:])
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

def _match_worldbook_entry(entry, context_text):
    """判断单条世界书条目是否应被注入当前上下文。

    匹配规则（SillyTavern 风格）：
    - constant=True → 无条件匹配
    - selective=True → key 中至少一个 AND keysecondary 中至少一个出现在 context_text
    - 其他 → key 中至少一个出现在 context_text
    匹配成功后按 probability 概率掷骰。
    """
    if not entry.get("enabled", True):
        return False
    if entry.get("constant"):
        return True
    if not context_text:
        return False

    case_sensitive = entry.get("case_sensitive", False)
    text = context_text if case_sensitive else context_text.lower()

    def _has_key(keys):
        for k in keys:
            k = k.strip()
            if not k:
                continue
            needle = k if case_sensitive else k.lower()
            if needle in text:
                return True
        return False

    keys = entry.get("key") or []
    if isinstance(keys, str):
        keys = [keys]
    keysecondary = entry.get("keysecondary") or []
    if isinstance(keysecondary, str):
        keysecondary = [keysecondary]

    if entry.get("selective"):
        matched = _has_key(keys) and _has_key(keysecondary)
    else:
        matched = _has_key(keys)

    if not matched:
        return False

    if entry.get("useProbability", True):
        prob = entry.get("probability", 100)
        if prob is not None and 0 <= prob < 100:
            import random
            if random.randint(1, 100) > prob:
                return False
    return True


def _format_worldbooks(context, only_constant=True, context_text=""):
    """把世界书条目格式化为 prompt 文本。

    only_constant=True 时只取「恒常注入」条目（constant=True 且 enabled），
    这些条目无条件加入上下文；False 时根据关键词匹配动态选择条目。
    返回空字符串表示没有可注入的条目。
    """
    wbs = context.get("worldbooks") or []
    matched = []
    for wb in wbs:
        entries = wb.get("entries") or []
        for e in entries:
            if e.get("enabled") is False:
                continue
            if only_constant:
                if not e.get("constant"):
                    continue
            else:
                if not _match_worldbook_entry(e, context_text):
                    continue
            content = (e.get("content") or "").strip()
            if not content:
                continue
            keys = e.get("key") or []
            key_str = "、".join(keys) if keys else ""
            line = content
            if key_str:
                line = f"（触发词：{key_str}）{content}"
            matched.append((e.get("insertion_order", 0) or 0, line))
    if not matched:
        return ""
    matched.sort(key=lambda x: x[0])
    return "\n\n".join(line for _, line in matched)


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
    key = "polish_fragment" if action == "polish" else "expand_fragment"
    return get_prompt(context, key).format(
        title=novel.get("title") or "未命名",
        chapter_index=chapter_index,
        style=info["style"],
        world=info["worldbuilding"],
        chars=info["characters"],
        prev=info["prev"],
        text=text,
    )


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


def _dialog_prompt(context, novel, user_text, history, word_limit=500):
    """构造对话模式的 prompt：每次输出约 word_limit 字，以剧情片段推进。"""
    chars = _format_characters(context, novel)
    rels = _format_relationships(context, novel)
    style = novel.get("style") or "文笔流畅自然，情节紧凑，人物鲜明。"
    worldbuilding = novel.get("worldbuilding") or "（暂无世界观设定）"
    background = novel.get("background") or "（暂无背景设定）"
    prev = _clean_progress(novel.get("progress_summary")) or "（暂无前情）"
    history_text = _format_dialog_history(history)

    prompt = get_prompt(context, "dialog").format(
        title=novel.get("title") or "未命名",
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
        limit=word_limit,
    )
    # 注入世界书条目（动态匹配关键词）
    wb_context = f"{history_text} {user_text}"
    wb_text = _format_worldbooks(context, only_constant=False, context_text=wb_context)
    if wb_text:
        prompt += "\n\n【世界书设定】\n" + wb_text
    return prompt


def dialog_stream(context, novel, user_text, history, word_limit=500):
    """对话模式：流式生成一段约 word_limit 字的剧情片段。"""
    provider, model, mcfg = _resolve(context, "text")
    prompt = _dialog_prompt(context, novel, user_text, history, word_limit)
    # 中文 1 字 ≈ 1.5 token，按字数换算并留足余量（至少 256）
    max_tokens = mcfg.get("max_tokens") or max(256, int(word_limit * 1.5 * 1.4))
    for delta in chat_text_stream(
            provider, model, _messages(context, prompt),
            temperature=_temperature(context, mcfg),
            max_tokens=max_tokens, name="对话推进"):
        yield {"type": "delta", "content": delta}


# ---------- 改写 / 续写模式（导入已有小说） ----------

_CHAPTER_MARKER = re.compile(
    r"^\s*(第\s*[0-9零一二三四五六七八九十百千万两]+\s*[章回节卷部篇集])"
    r"|^\s*(?:[Cc]hapter\s+\d+|第\s*\d+\s*[章回节卷部篇集])",
    re.M,
)


def split_source_chapters(source_text, words_per_chapter=2000):
    """把导入的原文切分为章节列表。

    优先按章节标记（第X章 / 第X回 / Chapter X 等）切分，标记行作为标题；
    无标记时按每章目标字数切分。返回
        [{index, title, summary, content, word_count}, ...]
    """
    text = (source_text or "").strip()
    if not text:
        return []

    matches = list(_CHAPTER_MARKER.finditer(text))
    blocks = []
    if len(matches) >= 2:
        # 标记行之前的前言（若有）并入第一个章节正文之前
        preamble = text[:matches[0].start()].strip()
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block = text[start:end].strip()
            title_line, _, body = block.partition("\n")
            title = title_line.strip()
            if i == 0 and preamble:
                body = preamble + "\n\n" + body
            blocks.append({"title": title, "content": body.strip()})
    else:
        # 无章节标记，按目标字数切分
        step = max(int(words_per_chapter or 2000), 500)
        idx = 0
        while idx < len(text):
            blocks.append({"title": "", "content": text[idx:idx + step].strip()})
            idx += step

    chapters = []
    for i, b in enumerate(blocks, 1):
        chapters.append({
            "index": i,
            "title": b["title"] or f"第{i}段",
            "summary": "",
            "content": b["content"],
            "word_count": _count_chinese(b["content"]),
        })
    return chapters


def _rewrite_prompt(context, novel, chapter_index):
    """构造改写单章的 prompt（按任务要求改写该章原文）。"""
    provider, model, mcfg = _resolve(context, "text")
    chapters = novel.get("chapters", [])
    if chapter_index < 1 or chapter_index > len(chapters):
        raise AIClientError("章节序号越界")
    chapter = chapters[chapter_index - 1]
    instruction = (novel.get("task_instruction") or chapter.get("instruction") or "").strip() \
        or "保持原意，优化语言表达，提升文学性。"
    text = (chapter.get("content") or "").strip()
    if not text:
        raise AIClientError("本章原文为空，请先导入原文并完成切分")

    chars = _format_characters(context, novel)
    style = novel.get("style") or "文笔流畅自然。"
    worldbuilding = novel.get("worldbuilding") or "（暂无世界观设定）"
    background = novel.get("background") or "（暂无背景设定）"

    prompt = get_prompt(context, "rewrite_chapter").format(
        title=novel.get("title") or "未命名",
        n=chapter_index,
        instruction=instruction,
        text=_truncate_text(text, 8000),
        style=style,
        world=worldbuilding,
        chars=chars,
        background=background,
    )
    wb_context = f"{chapter.get('title', '')} {text[:500]} {instruction}"
    wb_text = _format_worldbooks(context, only_constant=False, context_text=wb_context)
    if wb_text:
        prompt += "\n\n【世界书设定】\n" + wb_text
    # 改写可能扩写或缩写，按原文长度预留余量
    max_tokens = mcfg.get("max_tokens") or max(512, int(len(text) * 1.6 * 1.5))
    return provider, model, mcfg, prompt, max_tokens


def rewrite_chapter_stream(context, novel, chapter_index):
    """改写模式：流式改写单章原文，yield 事件同 stream_chapter。"""
    provider, model, mcfg, prompt, max_tokens = _rewrite_prompt(context, novel, chapter_index)
    parts = []
    for delta in chat_text_stream(
            provider, model, _messages(context, prompt),
            temperature=_temperature(context, mcfg),
            max_tokens=max_tokens, name="改写章节"):
        parts.append(delta)
        yield {"type": "delta", "content": delta}
    content = "".join(parts).strip()
    yield {"type": "chapter_done", "content": content, "word_count": _count_chinese(content)}
    yield {"type": "summary", "summary": _summarize_chapter(context, content, chapter_index)}


def _continue_prompt(context, novel, chapter_index, instruction):
    """构造续写单章的 prompt（以导入原文为前情）。"""
    provider, model, mcfg = _resolve(context, "text")
    words = int(novel.get("words_per_chapter", 2000))
    max_tokens = mcfg.get("max_tokens")
    if not max_tokens:
        max_tokens = max(512, int(words * float(context["settings"].get("token_ratio", 1.6))))

    chars = _format_characters(context, novel)
    rels = _format_relationships(context, novel)
    style = novel.get("style") or "文笔流畅自然，情节紧凑，人物鲜明。"
    genre = novel.get("genre") or "不限"
    worldbuilding = novel.get("worldbuilding") or "（暂无世界观设定）"
    background = novel.get("background") or "（暂无背景设定）"

    limit = _context_limit(context, mcfg, max_tokens) or 12000
    # 原文保留「结尾」部分（续写需承接结尾），而非开头
    source = novel.get("source_text") or ""
    source = source[-int(limit * 0.5):]
    # 已续写章节的正文作为「续写前情」，同样保留末尾
    prev_parts = [f"【第{c['index']}章】\n{c['content']}"
                  for c in novel.get("chapters", []) if c.get("content")]
    prev = "\n\n".join(prev_parts) if prev_parts else "（尚无续写内容，请从原文结尾直接续写）"
    prev = prev[-int(limit * 0.4):]

    prompt = get_prompt(context, "continue_chapter").format(
        title=novel.get("title") or "未命名",
        n=chapter_index,
        genre=genre,
        instruction=instruction or "自然承接原文结尾，推进剧情。",
        source=source or "（无导入原文）",
        prev=prev,
        style=style,
        world=worldbuilding,
        chars=chars,
        rels=rels,
        background=background,
        words=words,
    )
    wb_context = f"{instruction} {source[-500:]} {prev[-500:]}"
    wb_text = _format_worldbooks(context, only_constant=False, context_text=wb_context)
    if wb_text:
        prompt += "\n\n【世界书设定】\n" + wb_text
    return provider, model, mcfg, prompt, max_tokens


def continue_chapter_stream(context, novel, chapter_index, instruction=""):
    """续写模式：流式生成下一章，yield 事件同 stream_chapter。"""
    provider, model, mcfg, prompt, max_tokens = _continue_prompt(
        context, novel, chapter_index, instruction)
    parts = []
    for delta in chat_text_stream(
            provider, model, _messages(context, prompt),
            temperature=_temperature(context, mcfg),
            max_tokens=max_tokens, name="续写章节"):
        parts.append(delta)
        yield {"type": "delta", "content": delta}
    content = "".join(parts).strip()
    yield {"type": "chapter_done", "content": content, "word_count": _count_chinese(content)}
    yield {"type": "summary", "summary": _summarize_chapter(context, content, chapter_index)}



