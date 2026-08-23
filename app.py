"""织叙-NexTale FastAPI 后端入口。

运行：uvicorn app:app --host 127.0.0.1 --port 8000 --reload
"""
import asyncio
import base64
import json
import queue
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import generators
import storage
from ai_client import AIClientError, PRESET_BASE_URLS, list_models, test_connection

BASE_DIR = Path(__file__).resolve().parent
app = FastAPI(title="织叙-NexTale", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================= 用户认证 =================
# 会话 token 集合（内存态，进程重启后需重新登录）
_SESSIONS: set[str] = set()

# 无需登录即可访问的路径前缀
_PUBLIC_PREFIXES = ("/api/auth/",)

# 无需登录即可访问的路径（静态资源由 StaticFiles 处理，不走此中间件逻辑）
_PUBLIC_EXACT = ()


def _issue_token() -> str:
    token = secrets.token_urlsafe(32)
    _SESSIONS.add(token)
    return token


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """保护所有 /api/* 接口（除登录相关），未携带有效 token 返回 401；HTML 禁用缓存。"""
    path = request.url.path
    if path.startswith("/api/") and not path.startswith(_PUBLIC_PREFIXES):
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if token not in _SESSIONS:
            return JSONResponse(status_code=401, content={"detail": "未登录或登录已过期"})
    response = await call_next(request)
    # 对 HTML 页面禁用缓存，确保前端改动及时生效
    if not path.startswith("/api/") and (path == "/" or path.endswith(".html")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/api/auth/status")
def auth_status():
    """返回是否已设置密码（用于前端决定显示登录还是首次设置密码）。"""
    return {"has_password": storage.has_password(), "authenticated": False}


@app.post("/api/auth/login")
def auth_login(body: dict):
    """登录：校验密码，返回 session token。"""
    password = (body or {}).get("password", "")
    if not storage.has_password():
        # 首次使用：此密码即为初始密码
        if not password:
            raise HTTPException(400, "请设置初始密码")
        storage.set_password(password)
        return {"token": _issue_token(), "first_setup": True}
    if not storage.verify_password(password):
        raise HTTPException(401, "密码错误")
    return {"token": _issue_token(), "first_setup": False}


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    """退出登录：使当前 token 失效。"""
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    _SESSIONS.discard(token)
    return {"ok": True}


# ---------- 上下文 ----------
def _ctx(novel: dict | None = None):
    settings = storage.get_settings()
    # 小说级模型选择：若该小说指定了 text_model_id，则覆盖全局默认
    if novel and novel.get("text_model_id"):
        settings = {**settings, "text_model_id": novel["text_model_id"]}
    return {
        "providers": storage.list_providers(),
        "settings": settings,
        "characters": storage.list_characters(),
    }


def _err(e: Exception) -> HTTPException:
    if isinstance(e, AIClientError):
        return HTTPException(status_code=400, detail=str(e))
    return HTTPException(status_code=500, detail=f"服务器错误：{e}")


# ================= 服务商 =================
class ProviderIn(BaseModel):
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    proxy: str = "direct"


class ConnectIn(BaseModel):
    base_url: str = ""
    api_key: str = ""
    proxy: str = "direct"


class ModelIn(BaseModel):
    name: str = ""
    type: str = "text"  # "text" 或 "vision"，二选一
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    context_length: Optional[int] = None  # 模型上下文窗口长度（token），用于截断超长输入


@app.get("/api/providers")
def get_providers():
    return {"providers": storage.list_providers(),
            "presets": PRESET_BASE_URLS}


@app.post("/api/providers/connect")
def connect_provider(c: ConnectIn):
    """用给定配置连接服务商并拉取模型列表（无需先保存）。"""
    if not c.base_url.strip():
        raise HTTPException(400, "base_url 不能为空")
    provider = {
        "base_url": c.base_url.strip(),
        "api_key": c.api_key.strip(),
        "proxy": (c.proxy or "direct").strip(),
    }
    try:
        models = list_models(provider)
        return {"ok": True, "models": models}
    except AIClientError as e:
        return {"ok": False, "message": str(e)}


def _provider_dict(p: ProviderIn) -> dict:
    return {
        "name": p.name.strip() or p.base_url.strip(),
        "base_url": p.base_url.strip(),
        "api_key": p.api_key.strip(),
        "proxy": (p.proxy or "direct").strip(),
        "models": [],
    }


def _find_provider(pid):
    for p in storage.list_providers():
        if p.get("id") == pid:
            return p
    return None


@app.post("/api/providers")
def upsert_provider(p: ProviderIn):
    if not p.base_url.strip():
        raise HTTPException(400, "base_url 不能为空")
    providers = storage.list_providers()
    providers.append({"id": storage.new_id(), **_provider_dict(p)})
    storage.save_providers(providers)
    return {"providers": providers}


@app.put("/api/providers/{pid}")
def update_provider(pid: str, p: ProviderIn):
    if not p.base_url.strip():
        raise HTTPException(400, "base_url 不能为空")
    providers = storage.list_providers()
    for i, pr in enumerate(providers):
        if pr.get("id") == pid:
            existing_models = pr.get("models", [])
            providers[i] = {"id": pid, **_provider_dict(p)}
            providers[i]["models"] = existing_models
            storage.save_providers(providers)
            return {"providers": providers}
    raise HTTPException(404, "服务商不存在")


@app.delete("/api/providers/{pid}")
def delete_provider(pid: str):
    target = _find_provider(pid)
    providers = [p for p in storage.list_providers() if p.get("id") != pid]
    storage.save_providers(providers)
    if target:
        model_ids = {m.get("id") for m in target.get("models", [])}
        s = storage.get_settings()
        changed = False
        for key in ("text_model_id", "vision_model_id"):
            if s.get(key) in model_ids:
                s[key] = ""
                changed = True
        if changed:
            storage.save_settings(s)
    return {"providers": providers}


# ================= 模型（挂在服务商下） =================
def _model_dict(m: ModelIn) -> dict:
    return {
        "id": storage.new_id(),
        "name": m.name.strip(),
        "type": m.type,
        "temperature": m.temperature,
        "max_tokens": m.max_tokens,
        "context_length": m.context_length,
    }


@app.post("/api/providers/{pid}/models")
def add_model(pid: str, m: ModelIn):
    if not m.name.strip():
        raise HTTPException(400, "模型名不能为空")
    if m.type not in ("text", "vision"):
        raise HTTPException(400, "模型类型必须为 text 或 vision")
    providers = storage.list_providers()
    for p in providers:
        if p.get("id") == pid:
            p.setdefault("models", []).append(_model_dict(m))
            storage.save_providers(providers)
            return {"providers": providers}
    raise HTTPException(404, "服务商不存在")


@app.put("/api/providers/{pid}/models/{mid}")
def update_model(pid: str, mid: str, m: ModelIn):
    if not m.name.strip():
        raise HTTPException(400, "模型名不能为空")
    if m.type not in ("text", "vision"):
        raise HTTPException(400, "模型类型必须为 text 或 vision")
    providers = storage.list_providers()
    for p in providers:
        if p.get("id") == pid:
            for i, mm in enumerate(p.get("models", [])):
                if mm.get("id") == mid:
                    new = _model_dict(m)
                    new["id"] = mid
                    p["models"][i] = new
                    storage.save_providers(providers)
                    return {"providers": providers}
    raise HTTPException(404, "模型不存在")


@app.delete("/api/providers/{pid}/models/{mid}")
def delete_model(pid: str, mid: str):
    providers = storage.list_providers()
    for p in providers:
        if p.get("id") == pid:
            p["models"] = [m for m in p.get("models", []) if m.get("id") != mid]
            storage.save_providers(providers)
            s = storage.get_settings()
            changed = False
            for key in ("text_model_id", "vision_model_id"):
                if s.get(key) == mid:
                    s[key] = ""
                    changed = True
            if changed:
                storage.save_settings(s)
            return {"providers": providers}
    raise HTTPException(404, "服务商不存在")


@app.post("/api/providers/{pid}/models/{mid}/test")
def test_model(pid: str, mid: str):
    provider = _find_provider(pid)
    if not provider:
        raise HTTPException(404, "服务商不存在")
    model = next((m for m in provider.get("models", []) if m.get("id") == mid), None)
    if not model:
        raise HTTPException(404, "模型不存在")
    vision = model.get("type") == "vision"
    ok, msg = test_connection(provider, model.get("name", ""), vision=vision)
    return {"ok": ok, "message": msg}


# ================= 设置 =================
@app.get("/api/settings")
def get_settings():
    return storage.get_settings()


@app.post("/api/settings")
def save_settings(body: dict):
    allowed = {"text_model_id", "vision_model_id",
               "token_ratio", "temperature", "global_prompt"}
    cur = storage.get_settings()
    for k in allowed:
        if k in body:
            cur[k] = body[k]
    storage.save_settings(cur)
    return cur


# ================= AI 请求日志 =================
@app.get("/api/logs")
def get_logs(page: int = 1, page_size: int = 20):
    """分页返回日志：page 从 1 开始。"""
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    total = storage.count_logs()
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    offset = (page - 1) * page_size
    return {
        "logs": storage.list_logs(page_size, offset),
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


# ================= 题材库 =================
@app.get("/api/genres")
def get_genres():
    return {"genres": storage.list_genres()}


@app.post("/api/genres")
def create_genre(body: dict):
    name = (body or {}).get("name", "").strip()
    if not name:
        raise HTTPException(400, "题材名称不能为空")
    gid = storage.save_genre({
        "name": name,
        "style": (body or {}).get("style", ""),
        "reference_text": (body or {}).get("reference_text", ""),
        "description": (body or {}).get("description", ""),
        "created_at": time.time(),
    })
    return {"genres": storage.list_genres(), "id": gid}


@app.put("/api/genres/{gid}")
def update_genre(gid: str, body: dict):
    g = storage.get_genre(gid)
    if not g:
        raise HTTPException(404, "题材不存在")
    for k in ("name", "style", "reference_text", "description"):
        if k in body:
            g[k] = body[k]
    storage.save_genre(g)
    return {"genres": storage.list_genres()}


@app.delete("/api/genres/{gid}")
def delete_genre(gid: str):
    storage.delete_genre(gid)
    return {"genres": storage.list_genres()}


@app.post("/api/genres/import")
def import_genres(body: dict):
    """批量导入题材库：body 为 {genres: [{name, style, reference_text, description}, ...]}。"""
    items = (body or {}).get("genres", [])
    if not isinstance(items, list) or not items:
        raise HTTPException(400, "没有可导入的题材数据")
    valid = []
    for it in items:
        if isinstance(it, dict) and (it.get("name") or "").strip():
            valid.append({
                "name": it["name"].strip(),
                "style": it.get("style", ""),
                "reference_text": it.get("reference_text", ""),
                "description": it.get("description", ""),
            })
    if not valid:
        raise HTTPException(400, "导入数据中没有有效的题材（缺少 name 字段）")
    count = storage.save_genres(valid)
    return {"genres": storage.list_genres(), "imported": count}


# ================= 角色 =================
@app.get("/api/characters")
def get_characters():
    return {"characters": storage.list_characters()}


@app.post("/api/characters")
def create_character(body: dict):
    characters = storage.list_characters()
    c = {
        "id": storage.new_id(),
        "name": body.get("name", "").strip(),
        "appearance": body.get("appearance", ""),
        "personality": body.get("personality", ""),
        "background": body.get("background", ""),
        "notes": body.get("notes", ""),
        "photo_path": "",
    }
    characters.append(c)
    storage.save_characters(characters)
    return {"character": c}


@app.put("/api/characters/{cid}")
def update_character(cid: str, body: dict):
    chars = storage.list_characters()
    for c in chars:
        if c.get("id") == cid:
            for k in ("name", "appearance", "personality", "background", "notes"):
                if k in body:
                    c[k] = body[k]
            storage.save_characters(chars)
            return {"character": c}
    raise HTTPException(404, "角色不存在")


@app.delete("/api/characters/{cid}")
def delete_character(cid: str):
    chars = [c for c in storage.list_characters() if c.get("id") != cid]
    storage.save_characters(chars)
    return {"characters": chars}


@app.post("/api/characters/{cid}/photo")
async def upload_photo(cid: str, file: UploadFile = File(...)):
    """上传照片并（可选）用视觉模型分析外貌性格。analyze 参数控制是否分析。"""
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    ext = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".jpg"
    fname = f"{cid}_{int(time.time())}{ext}"
    fpath = storage.UPLOAD_DIR / fname
    fpath.write_bytes(data)

    chars = storage.list_characters()
    target = None
    for c in chars:
        if c.get("id") == cid:
            c["photo_path"] = f"uploads/{fname}"
            target = c
            break
    if not target:
        raise HTTPException(404, "角色不存在")
    storage.save_characters(chars)

    result = {"character": target}
    # 若配置了视觉模型，则自动分析外貌与性格
    try:
        ctx = _ctx()
        if ctx["settings"].get("vision_model_id"):
            b64 = base64.b64encode(data).decode()
            analysis = generators.analyze_photo(ctx, b64)
            for c in chars:
                if c.get("id") == cid:
                    c["appearance"] = analysis["appearance"]
                    c["personality"] = analysis["personality"]
            storage.save_characters(chars)
            target.update(analysis)
            result["character"] = target
            result["analyzed"] = True
        else:
            result["analyzed"] = False
            result["analyze_error"] = "未配置视觉模型"
    except AIClientError as e:
        result["analyzed"] = False
        result["analyze_error"] = str(e)
    return result


# ================= 小说 =================
def _ensure_not_finished(n: dict):
    """完结的小说不可再修改，任何写操作前调用此守卫。"""
    if n.get("status") == "finished":
        raise HTTPException(409, "该小说已完结，如需修改请先「重开」")


@app.get("/api/novels")
def get_novels():
    return {"novels": storage.list_novels()}


@app.get("/api/novels/trash")
def get_trashed_novels():
    return {"novels": storage.list_deleted_novels()}


@app.post("/api/novels")
def create_novel(body: dict):
    novels = storage.list_novels()
    n = {
        "id": storage.new_id(),
        "title": body.get("title", "").strip() or "未命名",
        "genre": body.get("genre", "").strip(),
        "style": body.get("style", "").strip(),
        "reference_text": body.get("reference_text", ""),
        "character_ids": body.get("character_ids", []),
        "relationships": body.get("relationships", []),
        "chapter_count": max(1, int(body.get("chapter_count", 10))),
        "words_per_chapter": max(200, int(body.get("words_per_chapter", 2000))),
        "summary": "",
        "worldbuilding": "",
        "background": body.get("background", ""),
        "chapters": [],
        "progress_summary": "",
        "status": "draft",
        "text_model_id": body.get("text_model_id", "").strip(),
        "mode": body.get("mode", "outline"),
        "created_at": time.time(),
    }
    novels.append(n)
    storage.save_novels(novels)
    return {"novel": n}


@app.get("/api/novels/{nid}")
def get_novel(nid: str):
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")
    return {"novel": n}


@app.delete("/api/novels/{nid}")
def delete_novel(nid: str):
    """软删除：小说进入垃圾箱，可恢复。"""
    if not storage.trash_novel(nid):
        raise HTTPException(404, "小说不存在")
    return {"ok": True}


@app.post("/api/novels/{nid}/restore")
def restore_novel(nid: str):
    """从垃圾箱恢复小说。"""
    if not storage.restore_novel(nid):
        raise HTTPException(404, "垃圾箱中未找到该小说")
    return {"ok": True}


@app.delete("/api/novels/{nid}/destroy")
def destroy_novel(nid: str):
    """彻底删除小说（不可恢复）。"""
    if not storage.destroy_novel(nid):
        raise HTTPException(404, "小说不存在")
    return {"ok": True}


@app.put("/api/novels/{nid}")
def update_novel(nid: str, body: dict):
    _ensure_not_finished(storage.get_novel(nid) or {})
    editable = {"title", "genre", "style", "reference_text", "character_ids",
                "relationships", "chapter_count", "words_per_chapter",
                "text_model_id", "summary", "worldbuilding", "background", "mode"}
    def mut(n):
        for k in editable:
            if k in body:
                n[k] = body[k]
        if "chapter_count" in body:
            n["chapter_count"] = max(1, int(body["chapter_count"]))
        if "words_per_chapter" in body:
            n["words_per_chapter"] = max(200, int(body["words_per_chapter"]))
        # 支持整体替换章节大纲（编辑修改）
        if "chapters" in body:
            new_chapters = body["chapters"]
            # 保留已生成正文：按 index 合并，仅更新标题/概要，不覆盖 content
            old_by_idx = {c.get("index"): c for c in (n.get("chapters") or [])}
            merged = []
            for c in new_chapters:
                idx = c.get("index")
                merged.append({
                    "index": idx,
                    "title": c.get("title", ""),
                    "summary": c.get("summary", ""),
                    "content": (old_by_idx.get(idx) or {}).get("content", ""),
                    "word_count": (old_by_idx.get(idx) or {}).get("word_count", 0),
                })
            n["chapters"] = merged
    n = storage.update_novel(nid, mut)
    if not n:
        raise HTTPException(404, "小说不存在")
    return {"novel": n}


@app.post("/api/novels/{nid}/finish")
def finish_novel(nid: str):
    """将小说标记为完结，完结后不可再修改。"""
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")
    if n.get("status") == "finished":
        raise HTTPException(409, "该小说已完结")

    def mut(m):
        m["status"] = "finished"

    return {"novel": storage.update_novel(nid, mut)}


@app.post("/api/novels/{nid}/reopen")
def reopen_novel(nid: str):
    """重新打开已完结的小说，恢复可编辑状态（重算状态）。"""
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")

    def mut(m):
        chs = m.get("chapters", [])
        all_done = bool(chs) and all(c.get("content") for c in chs)
        m["status"] = "done" if all_done else ("generating" if any(c.get("content") for c in chs) else "outlined")

    return {"novel": storage.update_novel(nid, mut)}


@app.post("/api/novels/{nid}/prepare")
def prepare_novel(nid: str):
    """生成故事梗概 + 世界观 + 章节大纲。"""
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    ctx = _ctx(n)
    try:
        # 1. 若有参考文本，先分析风格并合并
        if n.get("reference_text"):
            style_analysis = generators.analyze_style(ctx, n["reference_text"])
            if style_analysis:
                n["style"] = (n.get("style", "") + "\n\n【参考风格分析】\n" +
                              style_analysis).strip()
        # 2. 生成大纲
        outline = generators.generate_outline(ctx, n)
        def mut(m):
            m["summary"] = outline["summary"]
            m["worldbuilding"] = outline["worldbuilding"]
            m["chapters"] = outline["chapters"]
            m["style"] = n.get("style", m.get("style", ""))
            m["status"] = "outlined"
            m["progress_summary"] = ""
        n = storage.update_novel(nid, mut)
        return {"novel": n}
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.put("/api/novels/{nid}/chapter/{index}")
def update_one_chapter(nid: str, index: int, body: dict):
    """编辑单章内容（标题/概要/正文）。"""
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    if not n.get("chapters"):
        raise HTTPException(400, "尚未生成大纲")
    if index < 1 or index > len(n["chapters"]):
        raise HTTPException(400, f"章节序号越界（1~{len(n['chapters'])}）")
    editable = {"title", "summary", "content"}
    def mut(m):
        for ch in m["chapters"]:
            if ch.get("index") == index:
                for k in editable:
                    if k in body:
                        ch[k] = body[k]
                if "content" in body:
                    ch["word_count"] = generators._count_chinese(body["content"])
                break
    n = storage.update_novel(nid, mut)
    return {"novel": n}


@app.post("/api/novels/{nid}/chapter/{index}/summary")
def summarize_chapter(nid: str, index: int):
    """为指定章节单独生成摘要，保存到章节 summary 字段。"""
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    chapters = n.get("chapters", [])
    if index < 1 or index > len(chapters):
        raise HTTPException(400, f"章节序号越界（1~{len(chapters)}）")
    chapter = next((c for c in chapters if c.get("index") == index), None)
    if not chapter or not chapter.get("content"):
        raise HTTPException(400, "该章节暂无正文，无法生成摘要")
    ctx = _ctx(n)
    try:
        summary = generators.summarize_chapter_content(ctx, chapter["content"], index)
    except AIClientError as e:
        raise HTTPException(400, str(e))
    if not summary or not summary.strip():
        raise HTTPException(400, "摘要生成失败：模型未返回内容，请重试")

    def mut(m):
        for ch in m["chapters"]:
            if ch.get("index") == index:
                ch["summary"] = summary
                break

    storage.update_novel(nid, mut)
    return {"novel": storage.get_novel(nid), "summary": summary}


@app.delete("/api/novels/{nid}/chapter/{index}")
def delete_one_chapter(nid: str, index: int):
    """删除指定章节，后续章节重新编号。"""
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    chapters = n.get("chapters", [])
    if index < 1 or index > len(chapters):
        raise HTTPException(400, f"章节序号越界（1~{len(chapters)}）")

    def mut(m):
        chs = [c for c in m["chapters"] if c.get("index") != index]
        # 重新编号：按原顺序，index 从 1 开始连续
        for i, c in enumerate(sorted(chs, key=lambda x: x.get("index", 0)), start=1):
            c["index"] = i
        m["chapters"] = chs
        # 清理前情提要：删除被删章节的摘要，并重写后续章节编号
        m["progress_summary"] = _renumber_progress(m.get("progress_summary", ""), index, len(chs))
        # 重新计算状态
        all_done = bool(chs) and all(c.get("content") for c in chs)
        m["status"] = "done" if all_done else ("generating" if any(c.get("content") for c in chs) else "outlined")

    storage.update_novel(nid, mut)
    return {"novel": storage.get_novel(nid)}


def _renumber_progress(progress_summary, deleted_index, remain_count):
    """删除章节后重写前情提要的章节编号。

    - 删除被删章节的摘要条目
    - 后续章节（> deleted_index）的编号前移一位
    """
    import re as _re
    if not progress_summary:
        return ""
    entries = []
    for ln in progress_summary.split("\n"):
        s = ln.strip()
        m = _re.match(r"^第(\d+)章[:：]", s)
        if not m:
            continue  # 丢弃不规范条目
        old_idx = int(m.group(1))
        if old_idx == deleted_index:
            continue  # 删除该章摘要
        new_idx = old_idx if old_idx < deleted_index else old_idx - 1
        body = s[len(m.group(0)):]
        entries.append(f"第{new_idx}章：{body}")
    return "\n".join(entries)


@app.post("/api/novels/{nid}/chapter/{index}")
def generate_one_chapter(nid: str, index: int):
    """生成单章，并更新前情提要。"""
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    if not n.get("chapters"):
        raise HTTPException(400, "尚未生成大纲，请先点击「生成大纲」")
    if index < 1 or index > len(n["chapters"]):
        raise HTTPException(400, f"章节序号越界（1~{len(n['chapters'])}）")
    ctx = _ctx(n)
    try:
        chapter, csummary = generators.generate_chapter(ctx, n, index)

        def mut(m):
            for i, ch in enumerate(m["chapters"]):
                if ch["index"] == index:
                    m["chapters"][i] = chapter
                    break
            # 替换（而非追加）本章前情提要，避免重新生成时旧摘要残留
            if csummary:
                m["progress_summary"] = generators.replace_progress_entry(
                    m.get("progress_summary", ""), index, csummary)
            # 全部章节生成完成则标记 done
            all_done = all(ch.get("content") for ch in m["chapters"])
            m["status"] = "done" if all_done else "generating"
        n = storage.update_novel(nid, mut)

        # 前情提要过长时浓缩（异步判断，超过 3000 字触发）
        if len(n.get("progress_summary", "")) > 3000:
            try:
                condensed = generators.condense_progress(ctx, n["progress_summary"])
                storage.update_novel(nid, lambda m: m.update({"progress_summary": condensed}))
            except AIClientError:
                pass
        return {"chapter": chapter, "summary": csummary}
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.post("/api/novels/{nid}/chapter/{index}/stream")
async def stream_one_chapter(nid: str, index: int):
    """流式生成单章（SSE）：实时推送正文增量，边生成边显示。"""
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    if not n.get("chapters"):
        raise HTTPException(400, "尚未生成大纲，请先点击「生成大纲」")
    if index < 1 or index > len(n["chapters"]):
        raise HTTPException(400, f"章节序号越界（1~{len(n['chapters'])}）")
    ctx = _ctx(n)

    def sse(event: dict) -> str:
        return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    # 同步 stream 迭代器放在后台线程，事件通过 q 推送给 async gen
    q: queue.Queue = queue.Queue(maxsize=1024)
    loop = asyncio.get_running_loop()
    stream_error: dict = {}

    def _persist_chapter_done(content: str, word_count: int):
        chapter = {
            "index": index,
            "title": n["chapters"][index - 1].get("title", ""),
            "summary": n["chapters"][index - 1].get("summary", ""),
            "content": content,
            "word_count": word_count,
        }

        def mut(m):
            for i, ch in enumerate(m["chapters"]):
                if ch["index"] == index:
                    m["chapters"][i] = chapter
                    break
            # 全部章节生成完成则标记 done
            all_done = all(ch.get("content") for ch in m["chapters"])
            m["status"] = "done" if all_done else "generating"

        storage.update_novel(nid, mut)

    def _persist_summary(summary: str):
        if not summary:
            return

        def mut(m):
            # 替换（而非追加）本章前情提要，避免重新生成时旧摘要残留
            m["progress_summary"] = generators.replace_progress_entry(
                m.get("progress_summary", ""), index, summary)

        storage.update_novel(nid, mut)

    def _producer():
        """在后台线程中运行同步的 stream_chapter，每产出一个事件就推入队列。"""
        try:
            for event in generators.stream_chapter(ctx, n, index):
                if event["type"] == "chapter_done":
                    _persist_chapter_done(event["content"], event["word_count"])
                elif event["type"] == "summary":
                    _persist_summary(event["summary"])
                q.put(event)
            q.put(None)  # 结束标记
        except Exception as e:  # noqa: BLE001
            stream_error["err"] = e
            q.put(None)

    threading.Thread(target=_producer, daemon=True).start()

    async def gen():
        try:
            while True:
                # 用 run_in_executor 把阻塞的 q.get() 放到线程池，不阻塞事件循环
                item = await loop.run_in_executor(None, q.get)
                if item is None:
                    break
                yield sse(item)
                # 主动让出控制权，确保 uvicorn 立即 flush
                await asyncio.sleep(0)

            n2 = storage.get_novel(nid)
            if n2 and len(n2.get("progress_summary", "")) > 3000:
                try:
                    condensed = generators.condense_progress(ctx, n2["progress_summary"])
                    storage.update_novel(nid, lambda m: m.update({"progress_summary": condensed}))
                    n2 = storage.get_novel(nid)
                except AIClientError:
                    pass
            yield sse({"type": "done", "novel": n2})

            if "err" in stream_error:
                yield sse({"type": "error", "message": str(_err(stream_error["err"]).detail)})
        except Exception as e:  # noqa: BLE001
            yield sse({"type": "error", "message": str(_err(e).detail)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/novels/{nid}/improv/stream")
async def improv_stream(nid: str, body: dict):
    """即兴交互式：根据写作指引流式生成新章节。body: {instruction, title?, regenerate_index?}

    regenerate_index 存在时：重新生成该章（替换正文与写作指引，保留标题），
    引用章节只允许取该章之前的内容，避免把原章节内容发给 AI。
    """
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    instruction = (body or {}).get("instruction", "").strip()
    if not instruction:
        raise HTTPException(400, "请填写本章写作指引")
    title = (body or {}).get("title", "").strip()
    context_chapters = (body or {}).get("context_chapters", [])
    if not isinstance(context_chapters, list):
        context_chapters = []
    ctx = _ctx(n)

    regenerate_index = (body or {}).get("regenerate_index")
    if regenerate_index is not None:
        try:
            index = int(regenerate_index)
        except (TypeError, ValueError):
            raise HTTPException(400, "章节序号无效")
        if index < 1 or index > len(n.get("chapters", [])):
            raise HTTPException(400, f"章节序号越界（1~{len(n.get('chapters', []))}）")
        # 重新生成时只允许引用本章之前的章节（防止把本章/后文内容带入）
        context_chapters = [
            r for r in context_chapters
            if isinstance(r, dict) and isinstance(r.get("index"), int) and r["index"] < index
        ]
    else:
        index = len(n.get("chapters", [])) + 1  # 新章节号

    def sse(event: dict) -> str:
        return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    q: queue.Queue = queue.Queue(maxsize=1024)
    loop = asyncio.get_running_loop()
    stream_error: dict = {}

    def _persist_done(content: str, word_count: int):
        if regenerate_index is not None:
            # 重新生成：替换该章正文与写作指引，保留原标题；不带旧正文参与
            def mut(m):
                for i, ch in enumerate(m["chapters"]):
                    if ch["index"] == index:
                        m["chapters"][i] = {
                            "index": index,
                            "title": title or ch.get("title") or f"第{index}章",
                            "summary": ch.get("summary", ""),
                            "content": content,
                            "word_count": word_count,
                            "instruction": instruction,
                        }
                        break
                m["status"] = "generating"

            storage.update_novel(nid, mut)
            return

        chapter = {
            "index": index,
            "title": title or f"第{index}章",
            "summary": "",
            "content": content,
            "word_count": word_count,
            "instruction": instruction,  # 保存本章写作提示
        }

        def mut(m):
            m["chapters"].append(chapter)
            m["status"] = "generating"

        storage.update_novel(nid, mut)

    def _persist_summary(summary: str):
        if not summary:
            return

        def mut(m):
            m["progress_summary"] = generators.replace_progress_entry(
                m.get("progress_summary", ""), index, summary)

        storage.update_novel(nid, mut)

    def _producer():
        try:
            for event in generators.improv_chapter_stream(ctx, n, index, instruction, context_chapters):
                if event["type"] == "chapter_done":
                    _persist_done(event["content"], event["word_count"])
                elif event["type"] == "summary":
                    _persist_summary(event["summary"])
                q.put(event)
            q.put(None)
        except Exception as e:  # noqa: BLE001
            stream_error["err"] = e
            q.put(None)

    threading.Thread(target=_producer, daemon=True).start()

    async def gen():
        try:
            while True:
                item = await loop.run_in_executor(None, q.get)
                if item is None:
                    break
                yield sse(item)
                await asyncio.sleep(0)

            n2 = storage.get_novel(nid)
            if n2 and len(n2.get("progress_summary", "")) > 3000:
                try:
                    condensed = generators.condense_progress(ctx, n2["progress_summary"])
                    storage.update_novel(nid, lambda m: m.update({"progress_summary": condensed}))
                    n2 = storage.get_novel(nid)
                except AIClientError:
                    pass
            yield sse({"type": "done", "novel": n2})

            if "err" in stream_error:
                yield sse({"type": "error", "message": str(_err(stream_error["err"]).detail)})
        except Exception as e:  # noqa: BLE001
            yield sse({"type": "error", "message": str(_err(e).detail)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.get("/api/novels/{nid}/export")
def export_novel(nid: str):
    n = storage.get_novel(nid)
    if not n:
        raise HTTPException(404, "小说不存在")
    lines = [f"# {n.get('title')}", ""]
    if n.get("summary"):
        lines += ["## 故事梗概", n["summary"], ""]
    if n.get("worldbuilding"):
        lines += ["## 世界观", n["worldbuilding"], ""]
    lines += [f"题材：{n.get('genre') or '不限'}",
              f"章节数：{n.get('chapter_count')}",
              f"每章字数目标：{n.get('words_per_chapter')}", ""]
    for ch in n.get("chapters", []):
        if ch.get("content"):
            lines += [f"## 第{ch['index']}章 {ch.get('title','').strip()}", "",
                      ch["content"], ""]
    text = "\n".join(lines)
    fname = f"{n.get('title','novel')}_v{int(time.time())}.md"
    out_path = storage.OUTPUT_DIR / fname
    out_path.write_text(text, encoding="utf-8")
    return FileResponse(out_path, filename=fname,
                        media_type="text/markdown")


# ================= 静态资源 =================
# 先挂载 uploads（更具体路径优先），再挂载根静态目录
app.mount("/uploads", StaticFiles(directory=str(storage.UPLOAD_DIR)), name="uploads")
app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
