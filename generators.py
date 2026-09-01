"""小说生成引擎：风格分析、大纲生成、逐章创作、前情提要维护。"""
import json
import re

from ai_client import chat_text, chat_text_stream, chat_vision, AIClientError

def _uid(context):
    """从 context 提取 user_id（用于日志归属）。"""
    return context.get("_user_id", "") if isinstance(context, dict) else ""


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
                             temperature=_temperature(context, mcfg), name="分析照片", user_id=_uid(context))
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
                           temperature=_temperature(context, mcfg), name="分析风格", user_id=_uid(context))
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
                           temperature=_temperature(context, mcfg), name="生成大纲", user_id=_uid(context))
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
        user_id=_uid(context),
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
            max_tokens=max_tokens, name="生成章节", user_id=_uid(context)):
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
            max_tokens=max_tokens, name="生成章节", user_id=_uid(context)):
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
                             name="生成摘要", user_id=_uid(context))
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
                     temperature=_temperature(context, mcfg), max_tokens=2000, name="浓缩前情", user_id=_uid(context))
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
    # 背景设定跟随小说：优先用小说级 character_backgrounds，
    # 为空时回退角色卡自身的 background（兼容旧数据）
    char_bgs = novel.get("character_backgrounds") or {}
    chars = []
    for c in context["characters"]:
        if c.get("id") in novel.get("character_ids", []):
            parts = [f"· {c.get('name') or '未命名'}"]
            if c.get("appearance"):
                parts.append(f"  外貌：{c['appearance']}")
            if c.get("personality"):
                parts.append(f"  性格：{c['personality']}")
            bg = (char_bgs.get(c.get("id")) or "").strip() or (c.get("background") or "").strip()
            if bg:
                parts.append(f"  背景：{bg}")
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


def _extract_dialog_word_limit(user_text, word_limit=None):
    """提取对话模式本轮的字数要求。

    - word_limit 显式传入时直接使用；
    - 否则从作者发言中提取（支持「写300字」「20000字」「2万字」）；
    - 均无则默认 500。返回钳制到 [50, 100000] 的结果。
    """
    if word_limit is None:
        m = re.search(r"(\d+)\s*万字", user_text)
        if m:
            word_limit = int(m.group(1)) * 10000
        else:
            m = re.search(r"(\d+)\s*字", user_text)
            word_limit = int(m.group(1)) if m else 500
    return max(50, min(int(word_limit), 100000))


def _dialog_prompt(context, novel, user_text, history, word_limit=None):
    """构造对话模式的 prompt：每次输出约 word_limit 字，以剧情片段推进。

    word_limit 缺省时，从作者本轮发言中提取字数要求（如「写300字」「300字左右」），
    提取不到则默认 500 字。返回 (prompt, 最终字数)。
    """
    chars = _format_characters(context, novel)
    rels = _format_relationships(context, novel)
    style = novel.get("style") or "文笔流畅自然，情节紧凑，人物鲜明。"
    worldbuilding = novel.get("worldbuilding") or "（暂无世界观设定）"
    background = novel.get("background") or "（暂无背景设定）"
    prev = _clean_progress(novel.get("progress_summary")) or "（暂无前情）"
    history_text = _format_dialog_history(history)

    word_limit = _extract_dialog_word_limit(user_text, word_limit)

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
    return prompt, word_limit


def dialog_stream(context, novel, user_text, history, word_limit=None):
    """对话模式：流式生成一段约 word_limit 字的剧情片段。"""
    provider, model, mcfg = _resolve(context, "text")
    prompt, effective_limit = _dialog_prompt(context, novel, user_text, history, word_limit)
    # 中文 1 字 ≈ 1.5 token，按最终字数换算 max_tokens 并留足余量（至少 256）
    # 若模型显式配置了 max_tokens 且足够大，则取两者较大值，避免被模型配置卡住
    by_words = max(256, int(effective_limit * 1.5 * 1.4))
    configured = int(mcfg.get("max_tokens") or 0)
    max_tokens = max(by_words, configured) if configured else by_words
    for delta in chat_text_stream(
            provider, model, _messages(context, prompt),
            temperature=_temperature(context, mcfg),
            max_tokens=max_tokens, name="对话推进", user_id=_uid(context)):
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
            max_tokens=max_tokens, name="改写章节", user_id=_uid(context)):
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
    genre = novel.get("genre") or "不限"

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
        chars=chars,
        rels=rels,
        words=words,
    )
    # 已拆解的结构化故事档案优先注入，保证续写一致性（人物/世界观/主线/伏笔/摘要）
    profile_text = _format_profile(_load_profile(novel))
    if profile_text:
        prompt += "\n\n【原著故事档案（拆解结果，续写必须严格遵守，不得违背/重定义/新增设定）】\n" + profile_text
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
            max_tokens=max_tokens, name="续写章节", user_id=_uid(context)):
        parts.append(delta)
        yield {"type": "delta", "content": delta}
    content = "".join(parts).strip()
    yield {"type": "chapter_done", "content": content, "word_count": _count_chinese(content)}
    yield {"type": "summary", "summary": _summarize_chapter(context, content, chapter_index)}


# ---------- 原著结构化拆解（续写模式） ----------

def _extract_json(text):
    """从模型输出中提取 JSON 对象（剥掉代码围栏、修复常见格式问题）。"""
    text = (text or "").strip()
    if not text:
        raise AIClientError(
            "模型未返回任何内容（常见于推理类模型把输出额度全部用于思考过程）。"
            "请在「API 配置」中为该模型设置更大的 max_tokens（如 32768）后重试")

    candidates = [text]

    # 1. 剥掉 ```json ... ``` 代码围栏
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if m:
        candidates.append(m.group(1).strip())

    # 1b. 输出被截断时围栏可能未闭合：剥掉开头围栏行后再尝试解析
    m_open = re.match(r"\s*```(?:json)?\s*\n?", text)
    if m_open:
        stripped = re.sub(r"```\s*$", "", text[m_open.end():]).strip()
        if stripped:
            candidates.append(stripped)

    # 2. 用括号配对提取首个 { 到匹配的 }（比 rfind 更可靠）
    start = text.find("{")
    if start != -1:
        depth = 0
        in_str = False
        esc = False
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
        if end != -1:
            candidates.append(text[start:end + 1])

    # 3. 逐个候选尝试解析
    last_err = None
    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        # 3a. 直接解析
        try:
            return json.loads(cand)
        except ValueError as e:
            last_err = e
        # 3b. 去掉尾逗号（对象/数组内）
        fixed = re.sub(r",\s*([}\]])", r"\1", cand)
        if fixed != cand:
            try:
                return json.loads(fixed)
            except ValueError as e:
                last_err = e
        # 3c. 去掉注释（// 和 /* */）
        no_comment = re.sub(r"//[^\n]*", "", cand)
        no_comment = re.sub(r"/\*.*?\*/", "", no_comment, flags=re.S)
        if no_comment != cand:
            try:
                return json.loads(no_comment)
            except ValueError as e:
                last_err = e
                no_comment2 = re.sub(r",\s*([}\]])", r"\1", no_comment)
                try:
                    return json.loads(no_comment2)
                except ValueError as e2:
                    last_err = e2
        # 3d. 补全被截断的 JSON（仅缺少结尾的闭合括号，字符串未被截断时有效）
        completed = _try_complete_truncated_json(cand)
        if completed is not None:
            return completed

    if last_err is not None:
        raise AIClientError(f"拆解结果 JSON 解析失败：{last_err}")
    raise AIClientError("模型未返回有效的 JSON 结构")


def _extract_json_safe(content):
    """拆解结果解析：失败时给出更明确的可操作提示。"""
    try:
        return _extract_json(content)
    except AIClientError as e:
        # 判断是否疑似 token 截断（内容以逗号/冒号/未闭合引号结尾）
        tail = (content or "").rstrip()[-40:]
        if re.search(r"[,\"\[\{：:，]$", tail) or "Unterminated" in str(e):
            raise AIClientError(
                "拆解结果不完整（可能因模型输出长度被截断）。建议："
                "① 在配置里调大该模型的 max_tokens；"
                "② 对较长原文采用分块拆解。原始错误：" + str(e))
        raise


def _try_complete_truncated_json(text):
    """尝试补全因 max_tokens 截断而缺少结尾括号的 JSON。

    仅在字符串值未被截断（最后一个非空白字符是逗号/冒号/括号等）时，
    按括号配对补齐缺失的 ] 和 } 后重新解析。无法安全补全时返回 None。
    """
    text = (text or "").rstrip()
    if not text:
        return None
    # 统计 {} 和 [] 的未闭合深度（跳过字符串内字符）
    obj_depth = 0   # {
    arr_depth = 0   # [
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                obj_depth += 1
            elif ch == "}":
                obj_depth -= 1
            elif ch == "[":
                arr_depth += 1
            elif ch == "]":
                arr_depth -= 1
    if in_str:
        return None  # 字符串被截断，无法安全补全
    if obj_depth <= 0 and arr_depth <= 0:
        return None  # 括号已平衡，无需补全（说明是其他错误）
    # 去掉末尾可能残留的逗号（截断通常停在逗号后），再补上缺失的闭合括号
    base = text.rstrip()
    base = re.sub(r",\s*$", "", base)
    completed = base + ("]" * max(arr_depth, 0)) + ("}" * max(obj_depth, 0))
    try:
        return json.loads(completed)
    except ValueError:
        return None


def _load_profile(novel):
    """读取小说已保存的结构化档案（JSON 字符串 → dict），无则返回 None。"""
    raw = (novel or {}).get("structured_profile") or ""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _norm_text(v):
    """把模型偶尔输出的数组/对象字段归一化为可读文本（提示词要求字符串，
    但模型有时会返回 list/dict，直接拼接会得到 repr 或引发 AttributeError）。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return "；".join(x for x in (_norm_text(i) for i in v) if x)
    if isinstance(v, dict):
        return "；".join(f"{k}：{_norm_text(x)}" for k, x in v.items())
    return str(v).strip()


def _format_profile(profile):
    """把结构化故事档案格式化为续写 prompt 的上下文块（空档案返回空串）。"""
    if not isinstance(profile, dict):
        return ""
    parts = []

    chars = profile.get("characters") or []
    if chars:
        lines = ["【人物档案】"]
        for c in chars:
            if not isinstance(c, dict):
                continue
            fields = [
                f"性格：{_norm_text(c.get('core_personality'))}",
                f"说话：{_norm_text(c.get('speaking_style'))}",
                f"经历：{_norm_text(c.get('key_history'))}",
                f"关系：{_norm_text(c.get('relationship'))}",
                f"现状：{_norm_text(c.get('current_state'))}",
                f"禁忌：{_norm_text(c.get('taboo'))}",
            ]
            lines.append(f"· {c.get('name', '?')}｜" + "；".join(
                f for f in fields if f.split('：', 1)[-1].strip()))
        parts.append("\n".join(lines))

    ws = profile.get("world_setting") or {}
    if isinstance(ws, dict):
        ws_lines = []
        for k, label in [("world_rules", "世界规则"), ("geography", "重要地域"),
                         ("forces", "各大势力"), ("noun_glossary", "专有名词")]:
            v = _norm_text(ws.get(k))
            if v:
                ws_lines.append(f"{label}：{v}")
        if ws_lines:
            parts.append("【世界观设定】\n" + "\n".join(ws_lines))

    mf = profile.get("main_frame") or {}
    if isinstance(mf, dict):
        fg_txt = _norm_text(mf.get("foreshadowing_list"))
        mf_lines = [
            f"核心主题：{_norm_text(mf.get('core_theme'))}",
            f"主角长期目标：{_norm_text(mf.get('protagonist_goal'))}",
            f"核心矛盾：{_norm_text(mf.get('main_conflict'))}",
            f"文风基调：{_norm_text(mf.get('story_tone'))}",
            f"待回收伏笔：{fg_txt}",
        ]
        parts.append("【主线框架】\n" + "\n".join(mf_lines))

    sm = profile.get("summary") or {}
    if isinstance(sm, dict):
        outline = _norm_text(sm.get("full_outline"))
        if outline:
            parts.append("【全书脉络摘要】\n" + outline)

    return "\n\n".join(parts)


def _split_source_blocks(source, block_chars):
    """把原文切成若干块，尽量在段落边界切分（超长段落则硬切）。"""
    source = source.strip()
    if len(source) <= block_chars:
        return [source]
    blocks = []
    cur = ""
    for para in re.split(r"\n\s*\n", source):
        while len(para) > block_chars:
            if cur:
                blocks.append(cur)
                cur = ""
            blocks.append(para[:block_chars])
            para = para[block_chars:]
        if cur and len(cur) + len(para) + 2 > block_chars:
            blocks.append(cur)
            cur = para
        else:
            cur = (cur + "\n\n" + para) if cur else para
    if cur:
        blocks.append(cur)
    return [b for b in blocks if b.strip()]


def _merge_profiles(partials):
    """把多个分块拆解的局部档案合并为一份全局档案。"""
    merged = {
        "characters": [],
        "world_setting": {},
        "main_frame": {"foreshadowing_list": []},
        "summary": {"full_outline": "", "chapter_summaries": []},
    }
    char_by_name = {}
    ws = {}
    mf = {}
    fg = []
    fg_seen = set()
    outlines = []
    ch_sums = []
    ch_seen = set()

    for p in partials:
        if not isinstance(p, dict):
            continue
        # 人物：按 name 合并，同名字段拼接
        for c in (p.get("characters") or []):
            if not isinstance(c, dict) or not (c.get("name") or "").strip():
                continue
            name = c["name"].strip()
            if name not in char_by_name:
                char_by_name[name] = {
                    "name": name, "core_personality": "", "speaking_style": "",
                    "key_history": "", "relationship": "", "current_state": "", "taboo": "",
                }
            dst = char_by_name[name]
            for k in ["core_personality", "speaking_style", "key_history",
                      "relationship", "current_state", "taboo"]:
                v = _norm_text(c.get(k))
                if v and v not in dst[k]:
                    dst[k] = (dst[k] + "；" + v) if dst[k] else v
        # 世界观：各字段拼接（去重）
        w = p.get("world_setting") or {}
        for k in ["world_rules", "geography", "forces", "noun_glossary"]:
            v = _norm_text(w.get(k))
            if v and v not in ws.get(k, ""):
                ws[k] = (ws[k] + "；" + v) if ws.get(k) else v
        # 主线框架：核心字段取第一个非空（全书级），伏笔拼接去重
        m = p.get("main_frame") or {}
        for k in ["core_theme", "protagonist_goal", "main_conflict", "story_tone"]:
            v = _norm_text(m.get(k))
            if v and not mf.get(k):
                mf[k] = v
        fl = m.get("foreshadowing_list") or []
        if isinstance(fl, list):
            for x in fl:
                s = _norm_text(x)
                if s and s not in fg_seen:
                    fg_seen.add(s)
                    fg.append(s)
        # 摘要：outline 拼接，章节摘要去重
        s = p.get("summary") or {}
        if isinstance(s, dict):
            outline = _norm_text(s.get("full_outline"))
            if outline:
                outlines.append(outline)
            for cs in (s.get("chapter_summaries") or []):
                if not isinstance(cs, dict):
                    continue
                key = _norm_text(cs.get("chapter"))
                brief = _norm_text(cs.get("brief"))
                if brief and key not in ch_seen:
                    ch_seen.add(key)
                    ch_sums.append({"chapter": key, "brief": brief})

    merged["characters"] = list(char_by_name.values())
    merged["world_setting"] = ws
    if mf:
        mf["foreshadowing_list"] = fg
        merged["main_frame"] = mf
    merged["summary"]["full_outline"] = "\n".join(outlines)
    merged["summary"]["chapter_summaries"] = ch_sums
    return merged


def analyze_source_profile(context, novel, on_progress=None):
    """对原著全文做结构化拆解；超长时分块拆解再合并。

    on_progress(step, total, message) 用于进度反馈（可选）。
    返回 dict（characters/world_setting/main_frame/summary）。
    """
    provider, model, mcfg = _resolve(context, "text")
    source = (novel.get("source_text") or "").strip()
    if not source:
        raise AIClientError("尚未导入原文，无法拆解")
    # 拆解输出 JSON 较大（人物+世界观+主线+摘要）；推理类模型的思考过程也计入
    # max_tokens 额度，额度过小会导致结果被截断甚至返回空内容，默认预留 32768
    max_tokens = int(mcfg.get("max_tokens") or 32768)
    limit = _context_limit(context, mcfg, max_tokens)
    # 每块原文上限（字符）：留出提示词 + 输出 token 的余量；未配置上下文时用保守默认
    block_chars = max(limit - 3000, 6000) if limit else 50000

    if len(source) <= block_chars:
        if on_progress:
            on_progress(0, 1, "正在通读全文，提取故事档案…")
        prompt = get_prompt(context, "analyze_source").format(source=source)
        content, _ = chat_text(
            provider, model, _messages(context, prompt),
            temperature=0.3, max_tokens=max_tokens, name="原著结构化拆解", user_id=_uid(context))
        if on_progress:
            on_progress(1, 1, "拆解完成，正在整理结果…")
        return _extract_json_safe(content)

    # 超长：分块拆解 + 合并
    blocks = _split_source_blocks(source, block_chars)
    partials = []
    total = len(blocks)
    for i, blk in enumerate(blocks, 1):
        if on_progress:
            on_progress(i, total, f"正在拆解第 {i}/{total} 块（约 {_count_chinese(blk)} 字）…")
        prompt = get_prompt(context, "analyze_source_partial").format(block=blk)
        content, _ = chat_text(
            provider, model, _messages(context, prompt),
            temperature=0.3, max_tokens=max_tokens, name=f"原著分块拆解 {i}/{total}",
            user_id=_uid(context))
        partials.append(_extract_json_safe(content))
    if on_progress:
        on_progress(total, total, "正在合并各块档案…")
    return _merge_profiles(partials)



