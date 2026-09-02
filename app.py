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
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import generators
import prompts
import storage
from ai_client import AIClientError, PRESET_BASE_URLS, list_models, test_connection

BASE_DIR = Path(__file__).resolve().parent
APP_VERSION = (BASE_DIR / "VERSION").read_text(encoding="utf-8").strip()
app = FastAPI(title="织叙-NexTale", version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================= 用户认证 =================
# 无需登录即可访问的路径前缀
_PUBLIC_PREFIXES = ("/api/auth/", "/api/version")

# 简单的会话缓存：token -> user_id（减少 DB 查询）
_session_cache: dict[str, str] = {}


def _resolve_user(token: str) -> str | None:
    """从缓存或 DB 解析 token 对应的 user_id。"""
    if token in _session_cache:
        return _session_cache[token]
    uid = storage.get_session(token)
    if uid:
        _session_cache[token] = uid
    return uid


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """保护所有 /api/* 接口（除登录相关），未携带有效 token 返回 401；HTML 禁用缓存。"""
    path = request.url.path
    if path.startswith("/api/"):
        auth = request.headers.get("Authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        uid = _resolve_user(token)
        is_public = path.startswith(_PUBLIC_PREFIXES)
        if uid:
            request.state.user_id = uid
        elif not is_public:
            return JSONResponse(status_code=401, content={"detail": "未登录或登录已过期"})
    response = await call_next(request)
    if not path.startswith("/api/") and (path == "/" or path.endswith(".html")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/api/auth/status")
def auth_status():
    """返回是否已有用户（用于前端决定显示登录还是创建管理员）。"""
    return {"has_users": storage.has_users()}


@app.get("/api/version")
def get_version():
    """返回当前应用版本号。"""
    return {"version": APP_VERSION}


@app.post("/api/auth/login")
def auth_login(request: Request, body: dict):
    """登录：校验用户名+密码，返回 session token + 用户信息。"""
    b = body or {}
    username = b.get("username", "").strip()
    password = b.get("password", "")
    if not username or not password:
        raise HTTPException(400, "请输入用户名和密码")
    user = storage.verify_user_password(username, password)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    token = storage.create_session(user["id"])
    _session_cache[token] = user["id"]
    return {"token": token, "user": user}


@app.post("/api/auth/register")
def auth_register(body: dict):
    """首次创建管理员账号。"""
    b = body or {}
    if storage.has_users():
        raise HTTPException(400, "已有用户，无法注册")
    username = b.get("username", "").strip()
    password = b.get("password", "")
    if not username or not password:
        raise HTTPException(400, "请输入用户名和密码")
    if len(password) < 4:
        raise HTTPException(400, "密码至少 4 个字符")
    user = storage.create_user(username, password, role="admin")
    token = storage.create_session(user["id"])
    _session_cache[token] = user["id"]
    return {"token": token, "user": user}


@app.get("/api/auth/me")
def auth_me(request: Request):
    """返回当前登录用户信息。"""
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(401, "未登录")
    return storage.get_user(uid)


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    """退出登录：使当前 token 失效。"""
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    storage.delete_session(token)
    _session_cache.pop(token, None)
    return {"ok": True}


# ================= 用户管理（仅管理员） =================

def _require_admin(request: Request):
    user = storage.get_user(request.state.user_id)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "仅管理员可操作")
    return user


@app.get("/api/users")
def list_users_api(request: Request):
    _require_admin(request)
    return storage.list_users()


@app.post("/api/users")
def create_user_api(request: Request, body: dict):
    _require_admin(request)
    b = body or {}
    username = b.get("username", "").strip()
    password = b.get("password", "")
    role = b.get("role", "user")
    if not username or not password:
        raise HTTPException(400, "请输入用户名和密码")
    if role not in ("admin", "user"):
        raise HTTPException(400, "角色无效")
    try:
        return storage.create_user(username, password, role)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/users/{uid}")
def delete_user_api(request: Request, uid: str):
    me = _require_admin(request)
    if uid == me["id"]:
        raise HTTPException(400, "不能删除自己")
    storage.delete_user(uid)
    return {"ok": True}


@app.put("/api/users/{uid}/password")
def change_password_api(request: Request, uid: str, body: dict):
    me = _require_admin(request)
    new_pw = (body or {}).get("new_password", "")
    if not new_pw or len(new_pw) < 4:
        raise HTTPException(400, "密码至少 4 个字符")
    storage.update_user_password(uid, new_pw)
    return {"ok": True}


@app.put("/api/users/{uid}/role")
def change_role_api(request: Request, uid: str, body: dict):
    me = _require_admin(request)
    new_role = (body or {}).get("role", "")
    if new_role not in ("admin", "user"):
        raise HTTPException(400, "角色无效")
    if uid == me["id"] and new_role != "admin":
        raise HTTPException(400, "不能取消自己的管理员权限")
    storage.update_user_role(uid, new_role)
    return {"ok": True}


# ---------- 上下文 ----------
def _ctx(novel: dict | None = None, user_id: str = ""):
    settings = storage.get_settings(user_id)
    if novel and novel.get("text_model_id"):
        settings = {**settings, "text_model_id": novel["text_model_id"]}
    # 世界书：仅注入该小说选择的世界书（未选择任何世界书时为空）
    all_worldbooks = storage.list_worldbooks(user_id)
    selected_ids = set((novel or {}).get("worldbook_ids") or [])
    worldbooks = [wb for wb in all_worldbooks if wb.get("id") in selected_ids] if selected_ids else []
    return {
        "providers": storage.list_providers(user_id),
        "settings": settings,
        "characters": storage.list_characters(user_id),
        "worldbooks": worldbooks,
        "_user_id": user_id,
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
    type: str = "text"  # "text" / "vision" / "image"
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    context_length: Optional[int] = None  # 模型上下文窗口长度（token），用于截断超长输入


@app.get("/api/providers")
def get_providers(request: Request):
    uid = request.state.user_id
    return {"providers": storage.list_providers(uid),
            "presets": PRESET_BASE_URLS}


@app.post("/api/providers/connect")
def connect_provider(request: Request, c: ConnectIn):
    uid = request.state.user_id
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


def _find_provider(pid, user_id=""):
    for p in storage.list_providers(user_id):
        if p.get("id") == pid:
            return p
    return None


@app.post("/api/providers")
def upsert_provider(request: Request, p: ProviderIn):
    uid = request.state.user_id
    if not p.base_url.strip():
        raise HTTPException(400, "base_url 不能为空")
    providers = storage.list_providers(uid)
    providers.append({"id": storage.new_id(), **_provider_dict(p)})
    storage.save_providers(providers, uid)
    return {"providers": providers}


@app.put("/api/providers/{pid}")
def update_provider(request: Request, pid: str, p: ProviderIn):
    uid = request.state.user_id
    if not p.base_url.strip():
        raise HTTPException(400, "base_url 不能为空")
    providers = storage.list_providers(uid)
    for i, pr in enumerate(providers):
        if pr.get("id") == pid:
            existing_models = pr.get("models", [])
            providers[i] = {"id": pid, **_provider_dict(p)}
            providers[i]["models"] = existing_models
            storage.save_providers(providers, uid)
            return {"providers": providers}
    raise HTTPException(404, "服务商不存在")


@app.delete("/api/providers/{pid}")
def delete_provider(request: Request, pid: str):
    uid = request.state.user_id
    target = _find_provider(pid, uid)
    providers = [p for p in storage.list_providers(uid) if p.get("id") != pid]
    storage.save_providers(providers, uid)
    if target:
        model_ids = {m.get("id") for m in target.get("models", [])}
        s = storage.get_settings(uid)
        changed = False
        for key in ("text_model_id", "vision_model_id", "image_model_id"):
            if s.get(key) in model_ids:
                s[key] = ""
                changed = True
        if changed:
            storage.save_settings(s, uid)
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
def add_model(request: Request, pid: str, m: ModelIn):
    uid = request.state.user_id
    if not m.name.strip():
        raise HTTPException(400, "模型名不能为空")
    if m.type not in ("text", "vision", "image"):
        raise HTTPException(400, "模型类型必须为 text、vision 或 image")
    providers = storage.list_providers(uid)
    for p in providers:
        if p.get("id") == pid:
            p.setdefault("models", []).append(_model_dict(m))
            storage.save_providers(providers, uid)
            return {"providers": providers}
    raise HTTPException(404, "服务商不存在")


@app.put("/api/providers/{pid}/models/{mid}")
def update_model(request: Request, pid: str, mid: str, m: ModelIn):
    uid = request.state.user_id
    if not m.name.strip():
        raise HTTPException(400, "模型名不能为空")
    if m.type not in ("text", "vision", "image"):
        raise HTTPException(400, "模型类型必须为 text、vision 或 image")
    providers = storage.list_providers(uid)
    for p in providers:
        if p.get("id") == pid:
            for i, mm in enumerate(p.get("models", [])):
                if mm.get("id") == mid:
                    new = _model_dict(m)
                    new["id"] = mid
                    p["models"][i] = new
                    storage.save_providers(providers, uid)
                    return {"providers": providers}
    raise HTTPException(404, "模型不存在")


@app.delete("/api/providers/{pid}/models/{mid}")
def delete_model(request: Request, pid: str, mid: str):
    uid = request.state.user_id
    providers = storage.list_providers(uid)
    for p in providers:
        if p.get("id") == pid:
            p["models"] = [m for m in p.get("models", []) if m.get("id") != mid]
            storage.save_providers(providers, uid)
            s = storage.get_settings(uid)
            changed = False
            for key in ("text_model_id", "vision_model_id", "image_model_id"):
                if s.get(key) == mid:
                    s[key] = ""
                    changed = True
            if changed:
                storage.save_settings(s, uid)
            return {"providers": providers}
    raise HTTPException(404, "服务商不存在")


@app.post("/api/providers/{pid}/models/{mid}/test")
def test_model(request: Request, pid: str, mid: str):
    uid = request.state.user_id
    provider = _find_provider(pid, uid)
    if not provider:
        raise HTTPException(404, "服务商不存在")
    model = next((m for m in provider.get("models", []) if m.get("id") == mid), None)
    if not model:
        raise HTTPException(404, "模型不存在")
    vision = model.get("type") == "vision"
    image = model.get("type") == "image"
    ok, msg = test_connection(provider, model.get("name", ""), vision=vision, image=image)
    return {"ok": ok, "message": msg}


# ================= 设置 =================
@app.get("/api/settings")
def get_settings(request: Request):
    uid = request.state.user_id
    return storage.get_settings(uid)


@app.post("/api/settings")
def save_settings(request: Request, body: dict):
    uid = request.state.user_id
    allowed = {"text_model_id", "vision_model_id", "image_model_id",
               "token_ratio", "temperature", "global_prompt", "prompts",
               "max_tokens", "context_length"}
    cur = storage.get_settings(uid)
    for k in allowed:
        if k in body:
            cur[k] = body[k]
    storage.save_settings(cur, uid)
    return cur


# ================= 提示词配置 =================
@app.get("/api/prompts")
def get_prompts(request: Request):
    uid = request.state.user_id
    """返回所有提示词的定义（含默认值）与当前自定义值。"""
    custom = storage.get_settings(uid).get("prompts") or {}
    return {
        "defs": prompts.get_all_defs(),
        "custom": custom,
    }


@app.post("/api/prompts")
def save_prompts(request: Request, body: dict):
    uid = request.state.user_id
    """保存提示词自定义值。body: {prompts: {key: 模板文本, ...}}。"""
    new_prompts = (body or {}).get("prompts")
    if not isinstance(new_prompts, dict):
        raise HTTPException(400, "参数格式错误")
    # 只接受已知 key，且过滤空值（空值表示恢复默认）
    valid_keys = set(prompts.default_prompts().keys())
    cleaned = {}
    for k, v in new_prompts.items():
        if k not in valid_keys:
            continue
        if v and str(v).strip():
            cleaned[k] = str(v).strip()
    cur = storage.get_settings(uid)
    cur["prompts"] = cleaned
    storage.save_settings(cur, uid)
    return {"prompts": cleaned}


# ================= AI 请求日志 =================
@app.get("/api/logs")
def get_logs(request: Request, page: int = 1, page_size: int = 20):
    uid = request.state.user_id
    """分页返回日志：page 从 1 开始。"""
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 200))
    total = storage.count_logs(uid)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    offset = (page - 1) * page_size
    return {
        "logs": storage.list_logs(uid, page_size, offset),
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


# ================= 题材库 =================
@app.get("/api/genres")
def get_genres(request: Request):
    uid = request.state.user_id
    return {"genres": storage.list_genres(uid)}


@app.post("/api/genres")
def create_genre(request: Request, body: dict):
    uid = request.state.user_id
    name = (body or {}).get("name", "").strip()
    if not name:
        raise HTTPException(400, "题材名称不能为空")
    gid = storage.save_genre({
        "name": name,
        "style": (body or {}).get("style", ""),
        "reference_text": (body or {}).get("reference_text", ""),
        "description": (body or {}).get("description", ""),
        "created_at": time.time(),
    }, uid)
    return {"genres": storage.list_genres(uid), "id": gid}


@app.put("/api/genres/{gid}")
def update_genre(request: Request, gid: str, body: dict):
    uid = request.state.user_id
    g = storage.get_genre(gid, uid)
    if not g:
        raise HTTPException(404, "题材不存在")
    for k in ("name", "style", "reference_text", "description"):
        if k in body:
            g[k] = body[k]
    storage.save_genre(g, uid)
    return {"genres": storage.list_genres(uid)}


@app.delete("/api/genres/{gid}")
def delete_genre(request: Request, gid: str):
    uid = request.state.user_id
    storage.delete_genre(gid, uid)
    return {"genres": storage.list_genres(uid)}


@app.post("/api/genres/import")
def import_genres(request: Request, body: dict):
    uid = request.state.user_id
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
    count = storage.save_genres(valid, uid)
    return {"genres": storage.list_genres(uid), "imported": count}


# ================= 世界书 =================
def _normalize_worldbook_entry(e: dict) -> dict:
    """把 SillyTavern 世界书条目规范化为内部结构。"""
    keys = e.get("key") or e.get("keys") or []
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.split(",") if k.strip()]
    else:
        keys = [str(k).strip() for k in keys if str(k).strip()]
    keysecondary = e.get("keysecondary") or []
    if isinstance(keysecondary, str):
        keysecondary = [k.strip() for k in keysecondary.split(",") if k.strip()]
    else:
        keysecondary = [str(k).strip() for k in keysecondary if str(k).strip()]
    return {
        "uid": e.get("uid", 0),
        "key": keys,
        "keysecondary": keysecondary,
        "comment": e.get("comment", ""),
        "content": e.get("content", ""),
        "constant": bool(e.get("constant", False)),
        "selective": bool(e.get("selective", False)),
        "insertion_order": e.get("insertion_order", 0) or 0,
        "enabled": bool(e.get("enabled", True)),
        "position": e.get("position", "before_char") or "before_char",
        "depth": e.get("depth", 4) or 4,
        "group": e.get("group", "") or "",
        "group_weight": e.get("group_weight", 100) if e.get("group_weight") is not None else 100,
        "case_sensitive": bool(e.get("case_sensitive", False)),
        "probability": e.get("probability", 100) if e.get("probability") is not None else 100,
        "useProbability": bool(e.get("useProbability", True)),
        "logic": e.get("logic", "AND_ANY") or "AND_ANY",
        "exclude_recursion": bool(e.get("exclude_recursion", False)),
        "prevent_recursion": bool(e.get("prevent_recursion", False)),
        "delay_until_recursion": bool(e.get("delay_until_recursion", False)),
    }


def _parse_sillytavern_worldbook(data: dict) -> dict:
    """解析 SillyTavern 世界书 JSON，返回 {name, description, entries}。

    兼容 entries 为对象（key 为 uid 字符串）或数组两种形式。
    """
    if not isinstance(data, dict):
        raise HTTPException(400, "世界书 JSON 格式错误（顶层应为对象）")
    raw_entries = data.get("entries")
    entries = []
    if isinstance(raw_entries, dict):
        for k, e in raw_entries.items():
            if isinstance(e, dict):
                entries.append(_normalize_worldbook_entry(e))
    elif isinstance(raw_entries, list):
        for e in raw_entries:
            if isinstance(e, dict):
                entries.append(_normalize_worldbook_entry(e))
    else:
        raise HTTPException(400, "世界书缺少有效的 entries 字段")
    if not entries:
        raise HTTPException(400, "世界书 entries 为空，没有可导入的条目")
    name = data.get("worldName") or data.get("name") or ""
    description = data.get("description") or ""
    return {"name": name, "description": description, "entries": entries}


@app.get("/api/worldbooks")
def get_worldbooks(request: Request):
    uid = request.state.user_id
    return {"worldbooks": storage.list_worldbooks(uid)}


@app.post("/api/worldbooks")
def create_worldbook(request: Request, body: dict):
    uid = request.state.user_id
    name = (body or {}).get("name", "").strip()
    if not name:
        raise HTTPException(400, "世界书名称不能为空")
    entries = (body or {}).get("entries", [])
    if not isinstance(entries, list):
        entries = []
    wb_id = storage.save_worldbook({
        "name": name,
        "description": (body or {}).get("description", ""),
        "entries": entries,
        "created_at": time.time(),
    }, uid)
    return {"worldbooks": storage.list_worldbooks(uid), "id": wb_id}


@app.put("/api/worldbooks/{wid}")
def update_worldbook(request: Request, wid: str, body: dict):
    uid = request.state.user_id
    wb = storage.get_worldbook(wid, uid)
    if not wb:
        raise HTTPException(404, "世界书不存在")
    if "name" in body:
        wb["name"] = body["name"]
    if "description" in body:
        wb["description"] = body["description"]
    if "entries" in body:
        entries = body["entries"]
        if not isinstance(entries, list):
            raise HTTPException(400, "entries 应为数组")
        wb["entries"] = entries
    storage.save_worldbook(wb, uid)
    return {"worldbooks": storage.list_worldbooks(uid)}


@app.delete("/api/worldbooks/{wid}")
def delete_worldbook(request: Request, wid: str):
    uid = request.state.user_id
    storage.delete_worldbook(wid, uid)
    return {"worldbooks": storage.list_worldbooks(uid)}


@app.post("/api/worldbooks/import")
def import_worldbook(request: Request, body: dict):
    uid = request.state.user_id
    """导入 SillyTavern 世界书 JSON。body: {name?, description?, data: {...}}。"""
    data = (body or {}).get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            raise HTTPException(400, "JSON 解析失败，请检查格式")
    if not isinstance(data, dict):
        raise HTTPException(400, "缺少有效的世界书数据")
    parsed = _parse_sillytavern_worldbook(data)
    name = (body or {}).get("name", "").strip() or parsed["name"] or "未命名世界书"
    wb_id = storage.save_worldbook({
        "name": name,
        "description": (body or {}).get("description", "").strip() or parsed["description"],
        "entries": parsed["entries"],
        "created_at": time.time(),
    }, uid)
    return {"worldbooks": storage.list_worldbooks(uid), "id": wb_id,
            "imported": len(parsed["entries"])}


# ================= 角色 =================
@app.get("/api/characters")
def get_characters(request: Request, novel_id: str = "", limit: int = 20):
    uid = request.state.user_id
    """按需返回角色。

    - 传 novel_id：只返回该小说关联的角色（按 created_at 倒序）
    - 不传 novel_id：返回最新的 limit 个角色（默认 20）
    """
    all_chars = storage.list_characters(uid)  # 已按 created_at 倒序
    if novel_id:
        novel = storage.get_novel(novel_id, uid)
        ids = set((novel or {}).get("character_ids") or [])
        characters = [c for c in all_chars if c.get("id") in ids]
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20
        characters = all_chars[:limit]
    return {"characters": characters}


@app.get("/api/characters/novels")
def get_character_novels(request: Request):
    uid = request.state.user_id
    """返回小说列表（供角色库筛选下拉使用）。"""
    novels = storage.list_novels(uid)
    novel_map = [{"id": n.get("id"), "title": n.get("title", ""),
                  "character_ids": n.get("character_ids", [])} for n in novels]
    return {"novels": novel_map}


@app.post("/api/characters")
def create_character(request: Request, body: dict):
    uid = request.state.user_id
    characters = storage.list_characters(uid)
    c = {
        "id": storage.new_id(),
        "name": body.get("name", "").strip(),
        "appearance": body.get("appearance", ""),
        "personality": body.get("personality", ""),
        "background": body.get("background", ""),
        "notes": body.get("notes", ""),
        "photo_path": "",
        "created_at": time.time(),
    }
    characters.append(c)
    storage.save_characters(characters, uid)
    return {"character": c}


@app.put("/api/characters/{cid}")
def update_character(request: Request, cid: str, body: dict):
    uid = request.state.user_id
    chars = storage.list_characters(uid)
    for c in chars:
        if c.get("id") == cid:
            for k in ("name", "appearance", "personality", "background", "notes"):
                if k in body:
                    c[k] = body[k]
            storage.save_characters(chars, uid)
            return {"character": c}
    raise HTTPException(404, "角色不存在")


@app.delete("/api/characters/{cid}")
def delete_character(request: Request, cid: str):
    uid = request.state.user_id
    # 检查角色是否被任何未删除的小说关联，若关联则不允许删除
    linked_novels = []
    for n in storage.list_novels(uid):  # 默认只返回未删除（deleted_at=0）的小说
        ids = n.get("character_ids") or []
        if cid in ids:
            linked_novels.append(n.get("title") or "未命名")
    if linked_novels:
        titles = "、".join(linked_novels)
        raise HTTPException(
            409,
            f"该角色已被小说《{titles}》关联，无法删除。请先在小说中移除该角色，或删除对应小说后再试。",
        )
    chars = [c for c in storage.list_characters(uid) if c.get("id") != cid]
    storage.save_characters(chars, uid)
    return {"characters": chars}


@app.post("/api/characters/{cid}/photo")
async def upload_photo(request: Request, cid: str, file: UploadFile = File(...)):
    """上传角色照片（仅保存，不做 AI 分析）。AI 分析请调用 /api/analyze-character-photo。"""
    uid = request.state.user_id
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    ext = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".jpg"
    fname = f"{cid}_{int(time.time())}{ext}"
    fpath = storage.UPLOAD_DIR / fname
    fpath.write_bytes(data)

    chars = storage.list_characters(uid)
    target = None
    for c in chars:
        if c.get("id") == cid:
            c["photo_path"] = f"uploads/{fname}"
            target = c
            break
    if not target:
        raise HTTPException(404, "角色不存在")
    storage.save_characters(chars, uid)
    return {"character": target}


@app.post("/api/analyze-character-photo")
async def analyze_character_photo(request: Request, file: UploadFile = File(...)):
    """分析人物照片（外貌/穿着/性格），返回 {appearance, personality}，不落库、不保存照片，由前端确认后自行保存。"""
    uid = request.state.user_id
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    ctx = _ctx(user_id=uid)
    if not ctx["settings"].get("vision_model_id"):
        raise HTTPException(400, "未配置视觉模型，请先在「配置」页添加并选用视觉模型")
    try:
        b64 = base64.b64encode(data).decode()
        analysis = generators.analyze_photo(ctx, b64)
    except AIClientError as e:
        raise HTTPException(400, f"AI 分析失败：{e}")
    return {"appearance": analysis["appearance"], "personality": analysis["personality"]}


@app.post("/api/generate-character-photo")
def generate_character_photo(request: Request, body: dict):
    """AI 文生图：按提示词生成角色照片，直接返回图片字节流，由前端预览确认后随角色保存。"""
    uid = request.state.user_id
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(400, "生图提示词不能为空")
    ctx = _ctx(user_id=uid)
    if not ctx["settings"].get("image_model_id"):
        raise HTTPException(400, "未配置图片生成模型，请先在「配置」页添加图片模型并点「设为当前」")
    try:
        data = generators.generate_character_photo(ctx, prompt)
    except AIClientError as e:
        raise HTTPException(400, f"图片生成失败：{e}")
    if not data:
        raise HTTPException(400, "图片生成失败：服务商返回空图片")
    media = "image/png" if data[:8].startswith(b"\x89PNG") else "image/jpeg"
    return Response(content=data, media_type=media)


# ================= 小说 =================
def _ensure_not_finished(n: dict):
    """完结的小说不可再修改，任何写操作前调用此守卫。"""
    if n.get("status") == "finished":
        raise HTTPException(409, "该小说已完结，如需修改请先「重开」")


@app.get("/api/novels")
def get_novels(request: Request):
    uid = request.state.user_id
    return {"novels": storage.list_novels(uid)}


@app.get("/api/novels/trash")
def get_trashed_novels(request: Request):
    uid = request.state.user_id
    return {"novels": storage.list_deleted_novels(uid)}


@app.post("/api/novels")
def create_novel(request: Request, body: dict):
    uid = request.state.user_id
    novels = storage.list_novels(uid)
    mode = body.get("mode", "outline")
    source_text = body.get("source_text", "")
    task_instruction = body.get("task_instruction", "")
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
        "worldbuilding": body.get("worldbuilding", "").strip(),
        "worldbuilding_source": "manual",
        "background": body.get("background", ""),
        "chapters": [],
        "progress_summary": "",
        "status": "draft",
        "text_model_id": body.get("text_model_id", "").strip(),
        "mode": mode,
        "source_text": source_text,
        "task_instruction": task_instruction,
        "structured_profile": body.get("structured_profile", ""),
        "dialog_messages": [],
        "worldbook_ids": body.get("worldbook_ids", []),
        "created_at": time.time(),
    }
    # 改写模式：导入原文后立即切分为章节（每章内容 = 原文片段）
    if mode == "rewrite" and source_text.strip():
        n["chapters"] = generators.split_source_chapters(
            source_text, int(n["words_per_chapter"]))
    novels.append(n)
    storage.save_novels(novels, uid)
    return {"novel": n}


@app.get("/api/novels/{nid}")
def get_novel(request: Request, nid: str):
    uid = request.state.user_id
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    return {"novel": n}


@app.delete("/api/novels/{nid}")
def delete_novel(request: Request, nid: str):
    uid = request.state.user_id
    """软删除：小说进入垃圾箱，可恢复。"""
    if not storage.trash_novel(nid, uid):
        raise HTTPException(404, "小说不存在")
    return {"ok": True}


@app.post("/api/novels/{nid}/restore")
def restore_novel(request: Request, nid: str):
    uid = request.state.user_id
    """从垃圾箱恢复小说。"""
    if not storage.restore_novel(nid, uid):
        raise HTTPException(404, "垃圾箱中未找到该小说")
    return {"ok": True}


@app.delete("/api/novels/{nid}/destroy")
def destroy_novel(request: Request, nid: str):
    uid = request.state.user_id
    """彻底删除小说（不可恢复）。"""
    if not storage.destroy_novel(nid, uid):
        raise HTTPException(404, "小说不存在")
    return {"ok": True}


@app.put("/api/novels/{nid}")
def update_novel(request: Request, nid: str, body: dict):
    uid = request.state.user_id
    _ensure_not_finished(storage.get_novel(nid, uid) or {})
    editable = {"title", "genre", "style", "reference_text", "character_ids",
                "relationships", "chapter_count", "words_per_chapter",
                "text_model_id", "summary", "worldbuilding", "background", "mode",
                "source_text", "task_instruction", "structured_profile",
                "worldbook_ids", "character_backgrounds"}
    def mut(n):
        for k in editable:
            if k in body:
                n[k] = body[k]
        if "worldbuilding" in body:
            # 用户手动编辑/填写世界观 → 标记为 manual，生成大纲时不再被 AI 覆盖
            n["worldbuilding_source"] = "manual"
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
    n = storage.update_novel(nid, uid, mut)
    if not n:
        raise HTTPException(404, "小说不存在")
    return {"novel": n}


@app.post("/api/novels/{nid}/finish")
def finish_novel(request: Request, nid: str):
    uid = request.state.user_id
    """将小说标记为完结，完结后不可再修改。"""
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    if n.get("status") == "finished":
        raise HTTPException(409, "该小说已完结")

    def mut(m):
        m["status"] = "finished"

    return {"novel": storage.update_novel(nid, uid, mut)}


@app.post("/api/novels/{nid}/reopen")
def reopen_novel(request: Request, nid: str):
    uid = request.state.user_id
    """重新打开已完结的小说，恢复可编辑状态（重算状态）。"""
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")

    def mut(m):
        chs = m.get("chapters", [])
        all_done = bool(chs) and all(c.get("content") for c in chs)
        m["status"] = "done" if all_done else ("generating" if any(c.get("content") for c in chs) else "outlined")

    return {"novel": storage.update_novel(nid, uid, mut)}


@app.post("/api/novels/{nid}/prepare")
def prepare_novel(request: Request, nid: str):
    uid = request.state.user_id
    """生成故事梗概 + 世界观 + 章节大纲。"""
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    ctx = _ctx(n, uid)
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
            # 世界观覆盖规则：
            #   - 用户手动填写过（source=manual 且非空）→ 保留用户内容，不被 AI 覆盖
            #   - 空世界观 或 由 AI 生成过（source=ai）→ 使用（或更新为）AI 新生成的世界观
            if (m.get("worldbuilding_source") != "manual" or not (m.get("worldbuilding") or "").strip()):
                m["worldbuilding"] = outline["worldbuilding"]
                m["worldbuilding_source"] = "ai"
            m["chapters"] = outline["chapters"]
            m["style"] = n.get("style", m.get("style", ""))
            m["status"] = "outlined"
            m["progress_summary"] = ""
        n = storage.update_novel(nid, uid, mut)
        return {"novel": n}
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.put("/api/novels/{nid}/chapter/{index}")
def update_one_chapter(request: Request, nid: str, index: int, body: dict):
    uid = request.state.user_id
    """编辑单章内容（标题/概要/正文）。"""
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    if not n.get("chapters"):
        raise HTTPException(400, "尚未生成大纲")
    if index < 1 or index > len(n["chapters"]):
        raise HTTPException(400, f"章节序号越界（1~{len(n['chapters'])}）")
    # 快照旧版本
    storage.snapshot_chapter(nid, index, "manual", user_id=uid)
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
    n = storage.update_novel(nid, uid, mut)
    return {"novel": n}


@app.post("/api/novels/{nid}/chapter/{index}/summary")
def summarize_chapter(request: Request, nid: str, index: int):
    uid = request.state.user_id
    """为指定章节单独生成摘要，保存到章节 summary 字段。"""
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    chapters = n.get("chapters", [])
    if index < 1 or index > len(chapters):
        raise HTTPException(400, f"章节序号越界（1~{len(chapters)}）")
    chapter = next((c for c in chapters if c.get("index") == index), None)
    if not chapter or not chapter.get("content"):
        raise HTTPException(400, "该章节暂无正文，无法生成摘要")
    ctx = _ctx(n, uid)
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

    storage.update_novel(nid, uid, mut)
    return {"novel": storage.get_novel(nid, uid), "summary": summary}


@app.delete("/api/novels/{nid}/chapter/{index}")
def delete_one_chapter(request: Request, nid: str, index: int):
    uid = request.state.user_id
    """删除指定章节，后续章节重新编号。"""
    n = storage.get_novel(nid, uid)
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

    storage.update_novel(nid, uid, mut)
    return {"novel": storage.get_novel(nid, uid)}


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
def generate_one_chapter(request: Request, nid: str, index: int):
    uid = request.state.user_id
    """生成单章，并更新前情提要。"""
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    if not n.get("chapters"):
        raise HTTPException(400, "尚未生成大纲，请先点击「生成大纲」")
    if index < 1 or index > len(n["chapters"]):
        raise HTTPException(400, f"章节序号越界（1~{len(n['chapters'])}）")
    # 生成前快照旧版本
    storage.snapshot_chapter(nid, index, source="ai", user_id=uid)
    ctx = _ctx(n, uid)
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
        n = storage.update_novel(nid, uid, mut)

        # 前情提要过长时浓缩（异步判断，超过 3000 字触发）
        if len(n.get("progress_summary", "")) > 3000:
            try:
                condensed = generators.condense_progress(ctx, n["progress_summary"])
                storage.update_novel(nid, uid, lambda m: m.update({"progress_summary": condensed}))
            except AIClientError:
                pass
        return {"chapter": chapter, "summary": csummary}
    except Exception as e:  # noqa: BLE001
        raise _err(e)


@app.post("/api/novels/{nid}/chapter/{index}/stream")
async def stream_one_chapter(request: Request, nid: str, index: int):
    """流式生成单章（SSE）：实时推送正文增量，边生成边显示。"""
    uid = request.state.user_id
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    if not n.get("chapters"):
        raise HTTPException(400, "尚未生成大纲，请先点击「生成大纲」")
    if index < 1 or index > len(n["chapters"]):
        raise HTTPException(400, f"章节序号越界（1~{len(n['chapters'])}）")
    # 生成前快照旧版本
    storage.snapshot_chapter(nid, index, source="ai", user_id=uid)
    ctx = _ctx(n, uid)

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

        storage.update_novel(nid, uid, mut)

    def _persist_summary(summary: str):
        if not summary:
            return

        def mut(m):
            # 替换（而非追加）本章前情提要，避免重新生成时旧摘要残留
            m["progress_summary"] = generators.replace_progress_entry(
                m.get("progress_summary", ""), index, summary)

        storage.update_novel(nid, uid, mut)

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

            n2 = storage.get_novel(nid, uid)
            if n2 and len(n2.get("progress_summary", "")) > 3000:
                try:
                    condensed = generators.condense_progress(ctx, n2["progress_summary"])
                    storage.update_novel(nid, uid, lambda m: m.update({"progress_summary": condensed}))
                    n2 = storage.get_novel(nid, uid)
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
async def improv_stream(request: Request, nid: str, body: dict):
    """即兴交互式：根据写作指引流式生成新章节。body: {instruction, title?, regenerate_index?}

    regenerate_index 存在时：重新生成该章（替换正文与写作指引，保留标题），
    引用章节只允许取该章之前的内容，避免把原章节内容发给 AI。
    """
    uid = request.state.user_id
    n = storage.get_novel(nid, uid)
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
    ctx = _ctx(n, uid)

    regenerate_index = (body or {}).get("regenerate_index")
    if regenerate_index is not None:
        try:
            index = int(regenerate_index)
        except (TypeError, ValueError):
            raise HTTPException(400, "章节序号无效")
        if index < 1 or index > len(n.get("chapters", [])):
            raise HTTPException(400, f"章节序号越界（1~{len(n.get('chapters', []))}）")
        # 重新生成前快照旧版本
        storage.snapshot_chapter(nid, index, source="ai", user_id=uid)
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

            storage.update_novel(nid, uid, mut)
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

        storage.update_novel(nid, uid, mut)

    def _persist_summary(summary: str):
        if not summary:
            return

        def mut(m):
            m["progress_summary"] = generators.replace_progress_entry(
                m.get("progress_summary", ""), index, summary)

        storage.update_novel(nid, uid, mut)

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

            n2 = storage.get_novel(nid, uid)
            if n2 and len(n2.get("progress_summary", "")) > 3000:
                try:
                    condensed = generators.condense_progress(ctx, n2["progress_summary"])
                    storage.update_novel(nid, uid, lambda m: m.update({"progress_summary": condensed}))
                    n2 = storage.get_novel(nid, uid)
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


@app.post("/api/novels/{nid}/chapter/{index}/polish")
async def polish_fragment(request: Request, nid: str, index: int, body: dict):
    """润色章节中的节选片段（SSE 流式）。body: {text}。"""
    uid = request.state.user_id
    return _fragment_sse(nid, index, body, "polish", uid)


@app.post("/api/novels/{nid}/chapter/{index}/expand")
async def expand_fragment(request: Request, nid: str, index: int, body: dict):
    """扩写章节中的节选片段（SSE 流式）。body: {text}。"""
    uid = request.state.user_id
    return _fragment_sse(nid, index, body, "expand", uid)


def _fragment_sse(nid: str, index: int, body: dict, action: str, uid: str):
    """润色/扩写片段的通用 SSE 处理。"""
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    text = (body or {}).get("text", "").strip()
    if not text:
        raise HTTPException(400, "请先选中要处理的文字片段")
    if len(text) < 10:
        raise HTTPException(400, "片段过短（至少 10 字），请选中更完整的文字")
    chapters = n.get("chapters", [])
    if index < 1 or index > len(chapters):
        raise HTTPException(400, f"章节序号越界（1~{len(chapters)}）")
    ctx = _ctx(n, uid)

    stream_fn = (generators.polish_fragment_stream if action == "polish"
                 else generators.expand_fragment_stream)

    def sse(event: dict) -> str:
        return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    q: queue.Queue = queue.Queue(maxsize=1024)
    loop = asyncio.get_running_loop()
    stream_error: dict = {}

    def _producer():
        try:
            for event in stream_fn(ctx, n, index, text):
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
            if "err" in stream_error:
                yield sse({"type": "error", "message": str(_err(stream_error["err"]).detail)})
            else:
                yield sse({"type": "done"})
        except Exception as e:  # noqa: BLE001
            yield sse({"type": "error", "message": str(_err(e).detail)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/novels/{nid}/dialog/stream")
async def dialog_stream(request: Request, nid: str, body: dict):
    """对话模式：作者发言 → AI 流式返回一段约 word_limit 字的剧情片段（SSE）。

    body:
      text        作者本轮发言（必填）
      word_limit  可选，本轮期望字数（默认 500）。作者可自行指定。
      history     可选，编辑重生成时前端传入的对话历史（截断到编辑点）。
                  省略时默认读取 novel.dialog_messages。

    重生成场景：前端把历史截断到被编辑消息之前，把编辑后的内容作为 text 传入，
    后端用新历史生成，并在保存时替换（而非追加）该历史之后的旧消息。
    """
    uid = request.state.user_id
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    user_text = (body or {}).get("text", "").strip()
    if not user_text:
        raise HTTPException(400, "请先输入内容")
    # 本轮期望字数：作者可在发言中指定（如「写300字」），或通过 word_limit 显式传入。
    # 均未指定时由 generators 默认 500 字。
    word_limit = (body or {}).get("word_limit")
    if word_limit not in (None, ""):
        try:
            word_limit = max(50, min(int(word_limit), 100000))
        except (TypeError, ValueError):
            word_limit = None
    else:
        word_limit = None
    ctx = _ctx(n, uid)
    history = (body or {}).get("history")
    if history is None:
        history = n.get("dialog_messages", []) or []
    elif not isinstance(history, list):
        history = []

    def sse(event: dict) -> str:
        return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    q: queue.Queue = queue.Queue(maxsize=1024)
    loop = asyncio.get_running_loop()
    stream_error: dict = {}
    result: dict = {"content": ""}

    def _producer():
        try:
            for event in generators.dialog_stream(ctx, n, user_text, history, word_limit):
                if event["type"] == "delta":
                    result["content"] += event["content"]
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

            if "err" in stream_error:
                yield sse({"type": "error", "message": str(_err(stream_error["err"]).detail)})
                return

            content = result["content"].strip()
            if content:
                # 用「传入历史 + 本轮」作为新的完整历史（重生成场景自动截断旧消息）
                def mut(m):
                    msgs = list(history)
                    msgs.append({"role": "user", "content": user_text})
                    msgs.append({"role": "assistant", "content": content})
                    # 控制历史长度，避免无限膨胀（保留最近 200 条）
                    m["dialog_messages"] = msgs[-200:]
                    m["status"] = "generating"
                storage.update_novel(nid, uid, mut)

            yield sse({"type": "done", "content": content})
        except Exception as e:  # noqa: BLE001
            yield sse({"type": "error", "message": str(_err(e).detail)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/novels/{nid}/dialog/update")
def update_dialog_message(request: Request, nid: str, body: dict):
    uid = request.state.user_id
    """直接更新某条对话消息内容（不触发 AI 重新生成）。

    body: {index, content}  index 从 0 起。
    """
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    index = (body or {}).get("index")
    content = (body or {}).get("content", "")
    try:
        index = int(index)
    except (TypeError, ValueError):
        raise HTTPException(400, "缺少有效的消息索引")
    msgs = n.get("dialog_messages", []) or []
    if index < 0 or index >= len(msgs):
        raise HTTPException(400, "消息索引越界")
    if not content.strip():
        raise HTTPException(400, "内容不能为空")

    def mut(m):
        ms = m.get("dialog_messages", []) or []
        if index < len(ms):
            ms[index]["content"] = content.strip()
        m["dialog_messages"] = ms

    storage.update_novel(nid, uid, mut)
    return {"novel": storage.get_novel(nid, uid)}


@app.post("/api/novels/{nid}/dialog/delete")
def delete_dialog_message(request: Request, nid: str, body: dict):
    """删除对话消息。body: {index} 删除单条；或 {indexes: [..]} 批量删除。"""
    uid = request.state.user_id
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    # 支持批量删除：indexes 数组优先
    indexes = (body or {}).get("indexes")
    if indexes is not None:
        if not isinstance(indexes, list):
            raise HTTPException(400, "indexes 应为数组")
        try:
            indexes = sorted({int(i) for i in indexes})
        except (TypeError, ValueError):
            raise HTTPException(400, "消息索引无效")
    else:
        index = (body or {}).get("index")
        try:
            index = int(index)
        except (TypeError, ValueError):
            raise HTTPException(400, "缺少有效的消息索引")
        indexes = [index]

    msgs = n.get("dialog_messages", []) or []
    if any(i < 0 or i >= len(msgs) for i in indexes):
        raise HTTPException(400, "消息索引越界")

    def mut(m):
        ms = m.get("dialog_messages", []) or []
        # 从大到小删除，避免索引偏移
        for i in sorted(indexes, reverse=True):
            if i < len(ms):
                ms.pop(i)
        m["dialog_messages"] = ms

    storage.update_novel(nid, uid, mut)
    return {"novel": storage.get_novel(nid, uid)}


@app.post("/api/novels/{nid}/dialog/chapter")
async def dialog_to_chapter(request: Request, nid: str, body: dict):
    """把某次对话（含该消息之前的全部 AI 输出）合并成正式章节并保存。

    正文不重新生成——直接把之前的 AI 输出内容按顺序合并；
    摘要通过 AI 提取（仅摘要调用 AI，正文不调用）。

    body:
      up_to  结束索引（从 0 起，含该消息），取前 up_to+1 条消息中的 AI 内容。
      title  可选章节标题，缺省用「第N章」。
    """
    uid = request.state.user_id
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    history = n.get("dialog_messages", []) or []
    up_to = (body or {}).get("up_to")
    try:
        up_to = int(up_to)
    except (TypeError, ValueError):
        raise HTTPException(400, "缺少有效的消息索引")
    if up_to < 0 or up_to >= len(history):
        raise HTTPException(400, "消息索引越界")
    title = (body or {}).get("title", "").strip()

    selected = history[:up_to + 1]
    # 直接合并所有 AI 输出内容（role == assistant），不调用 AI 重新生成正文
    ai_parts = [m.get("content", "").strip()
                for m in selected if m.get("role") == "assistant" and m.get("content", "").strip()]
    content = "\n\n".join(ai_parts)
    if not content:
        raise HTTPException(400, "该段对话还没有 AI 生成的内容，无法生成章节")

    ctx = _ctx(n, uid)
    chapter_index = len(n.get("chapters", [])) + 1

    # 提取摘要（仅此步调用 AI）
    summary = ""
    try:
        summary = generators.summarize_chapter_content(ctx, content, chapter_index)
        # 清理模型可能附加的前缀（如「**摘要：**」「**第N章核心情节摘要：**」）与末尾字数标注
        import re as _re
        summary = _re.sub(r"^[\*\#\s]*[^\n]{0,20}?摘要[:：]?[\*\#\s]*", "", summary)
        summary = _re.sub(r"（共?\s*\d+\s*字）\s*$", "", summary).strip()
    except AIClientError:
        summary = ""  # 摘要失败不阻断章节保存

    chapter = {
        "index": chapter_index,
        "title": title or f"第{chapter_index}章",
        "summary": summary or "",
        "content": content,
        "word_count": generators._count_chinese(content),
    }

    def mut(m):
        m.setdefault("chapters", []).append(chapter)
        # 删除已合并的对话消息（up_to 及之前），后续合并只针对剩余新消息
        m["dialog_messages"] = history[up_to + 1:]
        # 同步前情提要
        if summary:
            m["progress_summary"] = generators.replace_progress_entry(
                m.get("progress_summary", ""), chapter_index, summary)
        m["status"] = "generating"

    storage.update_novel(nid, uid, mut)

    return {"chapter_index": chapter_index, "title": chapter["title"],
            "content": content, "summary": summary, "word_count": chapter["word_count"]}


# ================= 章节版本历史 =================

@app.get("/api/novels/{nid}/chapter/{index}/history")
def get_chapter_history(request: Request, nid: str, index: int):
    uid = request.state.user_id
    """返回某章节的历史版本列表。"""
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    versions = storage.list_chapter_versions(nid, index, uid)
    return {"versions": versions}


@app.get("/api/novels/{nid}/chapter/{index}/history/{vid}")
def get_chapter_version_detail(request: Request, nid: str, index: int, vid: str):
    uid = request.state.user_id
    """返回单个历史版本详情。"""
    v = storage.get_chapter_version(vid, uid)
    if not v or v["novel_id"] != nid or v["chapter_idx"] != index:
        raise HTTPException(404, "版本不存在")
    return {"version": v}


@app.post("/api/novels/{nid}/chapter/{index}/revert")
def revert_chapter(request: Request, nid: str, index: int, body: dict):
    uid = request.state.user_id
    """回退到指定历史版本。body: {version_id}"""
    vid = (body or {}).get("version_id", "")
    if not vid:
        raise HTTPException(400, "缺少 version_id")
    v = storage.get_chapter_version(vid, uid)
    if not v or v["novel_id"] != nid or v["chapter_idx"] != index:
        raise HTTPException(404, "版本不存在")

    def mut(m):
        for ch in m["chapters"]:
            if ch.get("index") == index:
                ch["title"] = v["title"]
                ch["summary"] = v["summary"]
                ch["content"] = v["content"]
                ch["word_count"] = v["word_count"]
                break

    n = storage.update_novel(nid, uid, mut)
    if not n:
        raise HTTPException(404, "小说不存在")
    return {"novel": n}


# ================= 改写 / 续写模式（导入已有小说） =================

@app.post("/api/novels/{nid}/rewrite/stream")
async def rewrite_stream(request: Request, nid: str, body: dict):
    """改写模式：按任务要求流式改写某章原文。body: {index}。"""
    uid = request.state.user_id
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    index = int((body or {}).get("index", 0))
    if index < 1 or index > len(n.get("chapters", [])):
        raise HTTPException(400, f"章节序号越界（1~{len(n.get('chapters', []))}）")
    storage.snapshot_chapter(nid, index, source="ai", user_id=uid)
    ctx = _ctx(n, uid)

    def sse(event: dict) -> str:
        return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    q: queue.Queue = queue.Queue(maxsize=1024)
    loop = asyncio.get_running_loop()
    stream_error: dict = {}

    def _persist_done(content: str, word_count: int):
        def mut(m):
            for i, ch in enumerate(m["chapters"]):
                if ch["index"] == index:
                    m["chapters"][i] = {**ch, "content": content, "word_count": word_count}
                    break
        storage.update_novel(nid, uid, mut)

    def _persist_summary(summary: str):
        if not summary:
            return
        def mut(m):
            for i, ch in enumerate(m["chapters"]):
                if ch["index"] == index:
                    ch["summary"] = summary
                    break
        storage.update_novel(nid, uid, mut)

    def _producer():
        try:
            for event in generators.rewrite_chapter_stream(ctx, n, index):
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
            n2 = storage.get_novel(nid, uid)
            yield sse({"type": "done", "novel": n2})
            if "err" in stream_error:
                yield sse({"type": "error", "message": str(_err(stream_error["err"]).detail)})
        except Exception as e:  # noqa: BLE001
            yield sse({"type": "error", "message": str(_err(e).detail)})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/novels/{nid}/continue/stream")
async def continue_stream(request: Request, nid: str, body: dict):
    """续写模式：以导入原文为前情流式生成下一章。body: {instruction}。"""
    uid = request.state.user_id
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    instruction = (body or {}).get("instruction", "").strip()
    if not instruction:
        raise HTTPException(400, "请填写本章续写要求")
    index = len(n.get("chapters", [])) + 1
    ctx = _ctx(n, uid)

    def sse(event: dict) -> str:
        return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    q: queue.Queue = queue.Queue(maxsize=1024)
    loop = asyncio.get_running_loop()
    stream_error: dict = {}

    def _persist_done(content: str, word_count: int):
        chapter = {
            "index": index,
            "title": f"第{index}章",
            "summary": "",
            "content": content,
            "word_count": word_count,
            "instruction": instruction,
        }
        def mut(m):
            m["chapters"].append(chapter)
            m["status"] = "generating"
        storage.update_novel(nid, uid, mut)

    def _persist_summary(summary: str):
        if not summary:
            return
        def mut(m):
            for ch in m["chapters"]:
                if ch["index"] == index:
                    ch["summary"] = summary
                    break
        storage.update_novel(nid, uid, mut)

    def _producer():
        try:
            for event in generators.continue_chapter_stream(ctx, n, index, instruction):
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
            n2 = storage.get_novel(nid, uid)
            yield sse({"type": "done", "novel": n2})
            if "err" in stream_error:
                yield sse({"type": "error", "message": str(_err(stream_error["err"]).detail)})
        except Exception as e:  # noqa: BLE001
            yield sse({"type": "error", "message": str(_err(e).detail)})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/analyze-source")
async def analyze_source_text(request: Request, body: dict):
    """无状态原著结构化拆解（SSE）：接收原文文本，返回故事档案（不持久化）。"""
    uid = request.state.user_id
    source_text = (body or {}).get("source_text", "").strip()
    if not source_text:
        raise HTTPException(400, "请先导入原文")
    n = {"source_text": source_text,
         "text_model_id": (body or {}).get("text_model_id", "")}
    ctx = _ctx(n, uid)

    def sse(event: dict) -> str:
        return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    q: queue.Queue = queue.Queue(maxsize=16)
    loop = asyncio.get_running_loop()
    heartbeat_stop = threading.Event()

    def _producer():
        try:
            # 立即发一条初始进度，让连接有数据
            q.put({"type": "progress", "step": 0, "total": 1, "message": "开始拆解原著…"})
            profile = generators.analyze_source_profile(
                ctx, n,
                on_progress=lambda step, total, msg: q.put(
                    {"type": "progress", "step": step, "total": total, "message": msg}))
            q.put({"type": "profile", "profile": profile})
        except Exception as e:  # noqa: BLE001
            q.put({"type": "error", "message": str(_err(e).detail)})
        finally:
            heartbeat_stop.set()
            q.put(None)

    threading.Thread(target=_producer, daemon=True).start()

    def _heartbeat():
        """定期发心跳，避免 LLM 长调用期间 SSE 静默被中断。"""
        while not heartbeat_stop.is_set():
            heartbeat_stop.wait(15)
            if not heartbeat_stop.is_set():
                q.put({"type": "progress", "step": -1, "total": -1, "message": "仍在拆解中，请稍候…"})

    threading.Thread(target=_heartbeat, daemon=True).start()

    async def gen():
        try:
            while True:
                item = await loop.run_in_executor(None, q.get)
                if item is None:
                    break
                yield sse(item)
                await asyncio.sleep(0)
        except Exception as e:  # noqa: BLE001
            yield sse({"type": "error", "message": str(_err(e).detail)})

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/novels/{nid}/resplit")
def resplit_source(request: Request, nid: str):
    uid = request.state.user_id
    """改写模式：按 source_text 重新切分章节（丢弃已有改写结果）。"""
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")
    _ensure_not_finished(n)
    source_text = (n.get("source_text") or "").strip()
    if not source_text:
        raise HTTPException(400, "尚未导入原文")
    chapters = generators.split_source_chapters(
        source_text, int(n.get("words_per_chapter", 2000)))

    def mut(m):
        m["chapters"] = chapters
    n = storage.update_novel(nid, uid, mut)
    if not n:
        raise HTTPException(404, "小说不存在")
    return {"novel": n}


@app.get("/api/novels/{nid}/export")
def export_novel(request: Request, nid: str, format: str = "md"):
    uid = request.state.user_id
    """导出小说，支持 md / txt / epub 格式。"""
    n = storage.get_novel(nid, uid)
    if not n:
        raise HTTPException(404, "小说不存在")

    fmt = (format or "md").lower().strip()
    if fmt not in ("md", "txt", "epub"):
        raise HTTPException(400, f"不支持的导出格式：{format}")

    title = n.get("title", "novel")
    ts = int(time.time())

    if fmt == "md":
        return _export_md(n, title, ts)
    elif fmt == "txt":
        return _export_txt(n, title, ts)
    else:
        return _export_epub(n, title, ts)


def _export_md(n, title, ts):
    lines = [f"# {title}", ""]
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
    fname = f"{title}_v{ts}.md"
    out_path = storage.OUTPUT_DIR / fname
    out_path.write_text(text, encoding="utf-8")
    return FileResponse(out_path, filename=fname, media_type="text/markdown")


def _strip_markdown(text):
    """去掉 Markdown 标记，保留纯文本。"""
    import re as _re
    # 标题
    text = _re.sub(r'^#{1,6}\s+', '', text, flags=_re.MULTILINE)
    # 粗体/斜体
    text = _re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = _re.sub(r'\*(.+?)\*', r'\1', text)
    # 引用块标记
    text = _re.sub(r'^>\s*', '', text, flags=_re.MULTILINE)
    # 多余空行压缩
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _export_txt(n, title, ts):
    lines = [title, "=" * len(title), ""]
    if n.get("summary"):
        lines += ["【故事梗概】", n["summary"], ""]
    if n.get("worldbuilding"):
        lines += ["【世界观】", n["worldbuilding"], ""]
    lines += [f"题材：{n.get('genre') or '不限'}",
              f"章节数：{n.get('chapter_count')}",
              f"每章字数目标：{n.get('words_per_chapter')}", ""]
    for ch in n.get("chapters", []):
        if ch.get("content"):
            lines += [f"第{ch['index']}章 {ch.get('title','').strip()}",
                      "-" * 40,
                      _strip_markdown(ch["content"]), ""]
    text = "\n".join(lines)
    fname = f"{title}_v{ts}.txt"
    out_path = storage.OUTPUT_DIR / fname
    out_path.write_text(text, encoding="utf-8")
    return FileResponse(out_path, filename=fname, media_type="text/plain")


def _escape_xml(s):
    """转义 XML 特殊字符。"""
    s = s.replace("&", "&amp;")
    s = s.replace("<", "&lt;")
    s = s.replace(">", "&gt;")
    s = s.replace('"', "&quot;")
    s = s.replace("'", "&apos;")
    return s


def _export_epub(n, title, ts):
    """构造 EPUB 2.0 格式的 ZIP 文件（纯 Python，无外部依赖）。"""
    import zipfile
    import io

    chapters_with_content = [ch for ch in n.get("chapters", []) if ch.get("content")]
    if not chapters_with_content:
        raise HTTPException(400, "没有可导出的章节内容")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype 必须第一个且未压缩
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

        # META-INF/container.xml
        container_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>'''
        zf.writestr("META-INF/container.xml", container_xml.encode("utf-8"))

        # OEBPS/style.css
        css = '''body { font-family: serif; line-height: 1.8; margin: 1em 2em; }
h1 { text-align: center; margin: 2em 0 1em; }
h2 { margin: 1.5em 0 0.5em; }
p { text-indent: 2em; margin: 0.5em 0; }
.meta { color: #666; font-size: 0.9em; margin-bottom: 1em; }
.chapter-break { page-break-before: always; }
'''
        zf.writestr("OEBPS/style.css", css.encode("utf-8"))

        # 前导页（梗概 + 世界观）
        intro_xhtml = _build_intro_xhtml(n, title)
        zf.writestr("OEBPS/intro.xhtml", intro_xhtml.encode("utf-8"))

        # 各章节 XHTML
        chapter_files = []
        for ch in chapters_with_content:
            xhtml = _build_chapter_xhtml(ch)
            fname = f"OEBPS/chapter_{ch['index']:03d}.xhtml"
            zf.writestr(fname, xhtml.encode("utf-8"))
            chapter_files.append((ch, fname))

        # content.opf
        opf = _build_opf(n, title, chapter_files)
        zf.writestr("OEBPS/content.opf", opf.encode("utf-8"))

        # toc.ncx
        ncx = _build_ncx(n, title, chapter_files)
        zf.writestr("OEBPS/toc.ncx", ncx.encode("utf-8"))

    buf.seek(0)
    fname = f"{title}_v{ts}.epub"
    out_path = storage.OUTPUT_DIR / fname
    out_path.write_bytes(buf.read())
    return FileResponse(out_path, filename=fname, media_type="application/epub+zip")


def _build_intro_xhtml(n, title):
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">',
        '<html xmlns="http://www.w3.org/1999/xhtml">',
        '<head><title>' + _escape_xml(title) + '</title>',
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>',
        '<body>',
        '<h1>' + _escape_xml(title) + '</h1>',
    ]
    if n.get("summary"):
        parts += ['<div class="meta"><h2>故事梗概</h2>',
                  '<p>' + _escape_xml(n["summary"]) + '</p></div>']
    if n.get("worldbuilding"):
        parts += ['<div class="meta"><h2>世界观</h2>',
                  '<p>' + _escape_xml(n["worldbuilding"]) + '</p></div>']
    genre = n.get("genre") or "不限"
    parts += [f'<div class="meta"><p>题材：{_escape_xml(genre)}</p>',
              f'<p>章节数：{n.get("chapter_count", "")}</p>',
              f'<p>每章字数目标：{n.get("words_per_chapter", "")}</p></div>',
              '</body></html>']
    return "\n".join(parts)


def _build_chapter_xhtml(ch):
    title = ch.get("title", "").strip() or f"第{ch['index']}章"
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd">',
        '<html xmlns="http://www.w3.org/1999/xhtml">',
        '<head><title>' + _escape_xml(title) + '</title>',
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>',
        '<body class="chapter-break">',
        '<h2>' + _escape_xml(title) + '</h2>',
    ]
    content = ch.get("content", "")
    # 按段落分割
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    for p in paragraphs:
        parts.append('<p>' + _escape_xml(p) + '</p>')
    parts += ['</body></html>']
    return "\n".join(parts)


def _build_opf(n, title, chapter_files):
    uid = f"urn:noveltale:{n.get('id', 'unknown')}"
    items = [
        f'    <item id="intro" href="intro.xhtml" media-type="application/xhtml+xml"/>',
    ]
    spine = [
        '    <itemref idref="intro"/>',
    ]
    manifest_items = []
    for ch, fname in chapter_files:
        fid = f"chapter_{ch['index']:03d}"
        items.append(f'    <item id="{fid}" href="{fname.split("/")[-1]}" media-type="application/xhtml+xml"/>')
        spine.append(f'    <itemref idref="{fid}"/>')

    opf = f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="BookId">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{_escape_xml(title)}</dc:title>
    <dc:creator>织叙-NexTale</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:identifier id="BookId">{uid}</dc:identifier>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
{chr(10).join(items)}
  </manifest>
  <spine toc="ncx">
{chr(10).join(spine)}
  </spine>
</package>'''
    return opf


def _build_ncx(n, title, chapter_files):
    uid = f"urn:noveltale:{n.get('id', 'unknown')}"
    nav_points = [
        f'''    <navPoint id="intro" playOrder="1">
      <navLabel><text>简介</text></navLabel>
      <content src="intro.xhtml"/>
    </navPoint>''',
    ]
    for i, (ch, fname) in enumerate(chapter_files, start=2):
        label = ch.get("title", "").strip() or f"第{ch['index']}章"
        nav_points.append(f'''    <navPoint id="chapter_{ch['index']:03d}" playOrder="{i}">
      <navLabel><text>{_escape_xml(label)}</text></navLabel>
      <content src="{fname.split('/')[-1]}"/>
    </navPoint>''')

    ncx = f'''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="{uid}"/>
    <meta name="dtb:depth" content="1"/>
  </head>
  <docTitle><text>{_escape_xml(title)}</text></docTitle>
  <navMap>
{chr(10).join(nav_points)}
  </navMap>
</ncx>'''
    return ncx


# ================= 静态资源 =================
# 先挂载 uploads（更具体路径优先），再挂载根静态目录
app.mount("/uploads", StaticFiles(directory=str(storage.UPLOAD_DIR)), name="uploads")
app.mount("/", StaticFiles(directory=str(BASE_DIR / "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
