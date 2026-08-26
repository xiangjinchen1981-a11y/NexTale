"""基于 SQLite 的持久化存储。

数据表：providers / models / settings / characters / novels / chapters。
对外接口保持与旧版 JSON 存储一致，上层（app.py / generators.py）无需改动。
"""
import json
import sqlite3
import time
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = DATA_DIR / "novel.db"

for _d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "text_model_id": "",
    "vision_model_id": "",
    # 每 100 目标字数对应的 max_tokens 安全系数
    "token_ratio": 1.6,
    "temperature": 0.8,
    # 全局前置提示词：附加到所有生成请求，统一约束创作方向
    "global_prompt": "",
    # 各功能提示词模板（key -> 模板文本），空 dict 表示全部使用默认
    "prompts": {},
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS providers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  api_key TEXT NOT NULL DEFAULT '',
  proxy TEXT NOT NULL DEFAULT 'direct'
);
CREATE TABLE IF NOT EXISTS models (
  id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'text',
  temperature REAL,
  max_tokens INTEGER,
  context_length INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS characters (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  appearance TEXT NOT NULL DEFAULT '',
  personality TEXT NOT NULL DEFAULT '',
  background TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  photo_path TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS novels (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  genre TEXT NOT NULL DEFAULT '',
  style TEXT NOT NULL DEFAULT '',
  reference_text TEXT NOT NULL DEFAULT '',
  character_ids TEXT NOT NULL DEFAULT '[]',
  relationships TEXT NOT NULL DEFAULT '[]',
  chapter_count INTEGER NOT NULL DEFAULT 10,
  words_per_chapter INTEGER NOT NULL DEFAULT 2000,
  summary TEXT NOT NULL DEFAULT '',
  worldbuilding TEXT NOT NULL DEFAULT '',
  background TEXT NOT NULL DEFAULT '',
  progress_summary TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  text_model_id TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL DEFAULT 'outline',
  dialog_messages TEXT NOT NULL DEFAULT '[]',
  worldbuilding_source TEXT NOT NULL DEFAULT 'manual',
  source_text TEXT NOT NULL DEFAULT '',
  task_instruction TEXT NOT NULL DEFAULT '',
  structured_profile TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL DEFAULT 0,
  deleted_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chapters (
  id TEXT PRIMARY KEY,
  novel_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  word_count INTEGER NOT NULL DEFAULT 0,
  instruction TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS request_logs (
  id TEXT PRIMARY KEY,
  created_at REAL NOT NULL,
  kind TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  prompt TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'ok',
  elapsed REAL NOT NULL DEFAULT 0,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  error TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS genres (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  style TEXT NOT NULL DEFAULT '',
  reference_text TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS worldbooks (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  entries TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chapter_versions (
  id TEXT PRIMARY KEY,
  novel_id TEXT NOT NULL,
  chapter_idx INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  word_count INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'manual',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_models_provider ON models(provider_id);
CREATE INDEX IF NOT EXISTS idx_chapters_novel ON chapters(novel_id, idx);
CREATE INDEX IF NOT EXISTS idx_logs_created ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_chapter_versions ON chapter_versions(novel_id, chapter_idx);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """轻量迁移：为旧库补齐新增列。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(novels)")}
    if "text_model_id" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN text_model_id TEXT NOT NULL DEFAULT ''")
    if "mode" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN mode TEXT NOT NULL DEFAULT 'outline'")
    if "background" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN background TEXT NOT NULL DEFAULT ''")
    if "deleted_at" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN deleted_at REAL NOT NULL DEFAULT 0")
    if "dialog_messages" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN dialog_messages TEXT NOT NULL DEFAULT '[]'")
    if "worldbuilding_source" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN worldbuilding_source TEXT NOT NULL DEFAULT 'manual'")
    if "source_text" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN source_text TEXT NOT NULL DEFAULT ''")
    if "task_instruction" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN task_instruction TEXT NOT NULL DEFAULT ''")
    if "structured_profile" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN structured_profile TEXT NOT NULL DEFAULT ''")

    mcols = {r[1] for r in conn.execute("PRAGMA table_info(models)")}
    if "context_length" not in mcols:
        conn.execute("ALTER TABLE models ADD COLUMN context_length INTEGER")

    ccols = {r[1] for r in conn.execute("PRAGMA table_info(chapters)")}
    if "instruction" not in ccols:
        conn.execute("ALTER TABLE chapters ADD COLUMN instruction TEXT NOT NULL DEFAULT ''")

    lcols = {r[1] for r in conn.execute("PRAGMA table_info(request_logs)")}
    if "name" not in lcols:
        conn.execute("ALTER TABLE request_logs ADD COLUMN name TEXT NOT NULL DEFAULT ''")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # 懒初始化：确保表存在（防止删库后进程未重启导致 no such table）
    n = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='providers'"
    ).fetchone()[0]
    if n == 0:
        conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def _init_db() -> None:
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


_init_db()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _json_loads(s, default):
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


# ---- Providers ----
def list_providers():
    conn = _connect()
    try:
        providers = [dict(r) for r in conn.execute("SELECT * FROM providers")]
        for p in providers:
            rows = conn.execute(
                "SELECT * FROM models WHERE provider_id = ? ORDER BY rowid", (p["id"],)
            )
            p["models"] = [dict(r) for r in rows]
        return providers
    finally:
        conn.close()


def save_providers(providers):
    conn = _connect()
    try:
        conn.execute("DELETE FROM models")
        conn.execute("DELETE FROM providers")
        for p in providers:
            pid = p.get("id") or new_id()
            conn.execute(
                "INSERT INTO providers (id, name, base_url, api_key, proxy) VALUES (?,?,?,?,?)",
                (pid, p.get("name", ""), p.get("base_url", ""),
                 p.get("api_key", ""), p.get("proxy", "direct")),
            )
            for m in p.get("models", []):
                conn.execute(
                    "INSERT INTO models (id, provider_id, name, type, temperature, max_tokens, context_length) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (m.get("id") or new_id(), pid, m.get("name", ""),
                     m.get("type", "text"), m.get("temperature"), m.get("max_tokens"),
                     m.get("context_length")),
                )
        conn.commit()
    finally:
        conn.close()


def get_provider(provider_id):
    for p in list_providers():
        if p.get("id") == provider_id:
            return p
    return None


# ---- Settings ----
def get_settings():
    conn = _connect()
    try:
        rows = conn.execute("SELECT key, value FROM settings")
        stored = {}
        for k, v in rows:
            stored[k] = _json_loads(v, v)
        merged = dict(DEFAULT_SETTINGS)
        merged.update(stored)
        # 只保留已知字段，自动清理历史遗留的旧字段
        return {k: merged.get(k) for k in DEFAULT_SETTINGS}
    finally:
        conn.close()


def save_settings(settings):
    conn = _connect()
    try:
        conn.execute("DELETE FROM settings")
        for k in DEFAULT_SETTINGS:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?,?)",
                (k, json.dumps(settings.get(k, DEFAULT_SETTINGS[k]))),
            )
        conn.commit()
    finally:
        conn.close()


# ---- Characters ----
def list_characters():
    conn = _connect()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM characters")]
    finally:
        conn.close()


def save_characters(characters):
    conn = _connect()
    try:
        conn.execute("DELETE FROM characters")
        for c in characters:
            conn.execute(
                "INSERT INTO characters (id, name, appearance, personality, background, notes, photo_path) "
                "VALUES (?,?,?,?,?,?,?)",
                (c.get("id") or new_id(), c.get("name", ""), c.get("appearance", ""),
                 c.get("personality", ""), c.get("background", ""), c.get("notes", ""),
                 c.get("photo_path", "")),
            )
        conn.commit()
    finally:
        conn.close()


def get_character(character_id):
    for c in list_characters():
        if c.get("id") == character_id:
            return c
    return None


# ---- Novels ----
def list_novels(include_deleted=False):
    conn = _connect()
    try:
        if include_deleted:
            novels = [dict(r) for r in conn.execute("SELECT * FROM novels")]
        else:
            novels = [dict(r) for r in conn.execute("SELECT * FROM novels WHERE deleted_at = 0")]
        for n in novels:
            n["character_ids"] = _json_loads(n["character_ids"], [])
            n["relationships"] = _json_loads(n["relationships"], [])
            n["dialog_messages"] = _json_loads(n.get("dialog_messages"), [])
            rows = conn.execute(
                "SELECT * FROM chapters WHERE novel_id = ? ORDER BY idx", (n["id"],)
            )
            n["chapters"] = [
                {
                    "index": r["idx"],
                    "title": r["title"],
                    "summary": r["summary"],
                    "content": r["content"],
                    "word_count": r["word_count"],
                    "instruction": r["instruction"] if "instruction" in r.keys() else "",
                }
                for r in rows
            ]
        return novels
    finally:
        conn.close()


def list_deleted_novels():
    """返回垃圾箱内的小说（仅元信息，不含章节）。"""
    conn = _connect()
    try:
        novels = [dict(r) for r in conn.execute("SELECT * FROM novels WHERE deleted_at != 0 ORDER BY deleted_at DESC")]
        for n in novels:
            n["character_ids"] = _json_loads(n["character_ids"], [])
            n["relationships"] = _json_loads(n["relationships"], [])
            n["chapters"] = []
        return novels
    finally:
        conn.close()


def save_novels(novels):
    """按 id upsert 保存小说（不清空已删除记录，避免垃圾箱数据丢失）。"""
    conn = _connect()
    try:
        for n in novels:
            nid = n.get("id") or new_id()
            conn.execute(
                "INSERT OR REPLACE INTO novels (id, title, genre, style, reference_text, character_ids, "
                "relationships, chapter_count, words_per_chapter, summary, worldbuilding, background, "
                "progress_summary, status, text_model_id, mode, dialog_messages, worldbuilding_source, "
                "source_text, task_instruction, structured_profile, created_at, deleted_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (nid, n.get("title", ""), n.get("genre", ""), n.get("style", ""),
                 n.get("reference_text", ""), json.dumps(n.get("character_ids", [])),
                 json.dumps(n.get("relationships", [])), n.get("chapter_count", 10),
                 n.get("words_per_chapter", 2000), n.get("summary", ""),
                 n.get("worldbuilding", ""), n.get("background", ""), n.get("progress_summary", ""),
                 n.get("status", "draft"), n.get("text_model_id", ""),
                 n.get("mode", "outline"), json.dumps(n.get("dialog_messages", [])),
                 n.get("worldbuilding_source", "manual"),
                 n.get("source_text", ""), n.get("task_instruction", ""),
                 n.get("structured_profile", ""),
                 n.get("created_at", 0), n.get("deleted_at", 0)),
            )
            # 重建本章节（先删后插，保证与传入数据一致）
            conn.execute("DELETE FROM chapters WHERE novel_id = ?", (nid,))
            for c in n.get("chapters", []):
                conn.execute(
                    "INSERT INTO chapters (id, novel_id, idx, title, summary, content, word_count, instruction) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (f"{nid}:{c.get('index', 0)}", nid, c.get("index", 0),
                     c.get("title", ""), c.get("summary", ""), c.get("content", ""),
                     c.get("word_count", 0), c.get("instruction", "")),
                )
        conn.commit()
    finally:
        conn.close()


def get_novel(novel_id):
    for n in list_novels():
        if n.get("id") == novel_id:
            return n
    return None


def update_novel(novel_id, mutator):
    novels = list_novels()
    for n in novels:
        if n.get("id") == novel_id:
            mutator(n)
            save_novels(novels)
            return n
    return None


def trash_novel(novel_id):
    """软删除：标记进垃圾箱。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE novels SET deleted_at = ? WHERE id = ? AND deleted_at = 0",
            (time.time(), novel_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def restore_novel(novel_id):
    """从垃圾箱恢复。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE novels SET deleted_at = 0 WHERE id = ?", (novel_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def destroy_novel(novel_id):
    """彻底删除小说及其章节。"""
    conn = _connect()
    try:
        conn.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
        cur = conn.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---- AI 请求日志 ----
def add_log(kind, provider, model, prompt, status="ok", elapsed=0.0,
            prompt_tokens=None, completion_tokens=None, error="", name=""):
    """记录一次 AI 请求。"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO request_logs (id, created_at, kind, name, provider, model, prompt, "
            "status, elapsed, prompt_tokens, completion_tokens, error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id(), time.time(), kind, name, provider, model, prompt,
             status, elapsed, prompt_tokens, completion_tokens, error),
        )
        conn.commit()
    finally:
        conn.close()


def list_logs(limit=200, offset=0):
    """按时间倒序返回日志列表（支持分页）。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM request_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_logs():
    """返回日志总条数。"""
    conn = _connect()
    try:
        return conn.execute("SELECT count(*) FROM request_logs").fetchone()[0]
    finally:
        conn.close()


# ---- 用户认证 ----
AUTH_PATH = DATA_DIR / "auth.json"


def _auth_data() -> dict:
    """读取认证数据（密码哈希 + salt），不存在则返回空 dict。"""
    if not AUTH_PATH.exists():
        return {}
    try:
        return json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def has_password() -> bool:
    """是否已设置登录密码。"""
    return bool(_auth_data().get("password_hash"))


def verify_password(password: str) -> bool:
    """校验密码是否正确（sha256 + salt）。"""
    data = _auth_data()
    h = data.get("password_hash")
    salt = data.get("salt", "")
    if not h:
        return False
    import hashlib
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest() == h


def set_password(password: str) -> None:
    """设置（或修改）登录密码。"""
    import hashlib
    import secrets
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    AUTH_PATH.write_text(
        json.dumps({"password_hash": h, "salt": salt}, ensure_ascii=False),
        encoding="utf-8",
    )


# ---- 题材库 ----
def list_genres():
    """返回所有题材（按创建时间倒序）。"""
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM genres ORDER BY created_at DESC")
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_genre(genre_id):
    conn = _connect()
    try:
        r = conn.execute("SELECT * FROM genres WHERE id = ?", (genre_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def save_genre(genre):
    """新增或更新单个题材（有 id 则更新，否则新增）。"""
    conn = _connect()
    try:
        gid = genre.get("id") or new_id()
        conn.execute(
            "INSERT OR REPLACE INTO genres (id, name, style, reference_text, description, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (gid, genre.get("name", ""), genre.get("style", ""),
             genre.get("reference_text", ""), genre.get("description", ""),
             genre.get("created_at", time.time())),
        )
        conn.commit()
        return gid
    finally:
        conn.close()


def save_genres(genres):
    """批量保存（导入时用），返回保存数量。"""
    conn = _connect()
    try:
        for g in genres:
            gid = g.get("id") or new_id()
            conn.execute(
                "INSERT OR REPLACE INTO genres (id, name, style, reference_text, description, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (gid, g.get("name", ""), g.get("style", ""),
                 g.get("reference_text", ""), g.get("description", ""),
                 g.get("created_at", time.time())),
            )
        conn.commit()
        return len(genres)
    finally:
        conn.close()


def delete_genre(genre_id):
    conn = _connect()
    try:
        conn.execute("DELETE FROM genres WHERE id = ?", (genre_id,))
        conn.commit()
    finally:
        conn.close()


# ---- 世界书 ----
def list_worldbooks():
    """返回所有世界书（按创建时间倒序），entries 解析为列表。"""
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM worldbooks ORDER BY created_at DESC")
        result = []
        for r in rows:
            wb = dict(r)
            wb["entries"] = _json_loads(wb.get("entries"), [])
            result.append(wb)
        return result
    finally:
        conn.close()


def get_worldbook(wb_id):
    conn = _connect()
    try:
        r = conn.execute("SELECT * FROM worldbooks WHERE id = ?", (wb_id,)).fetchone()
        if not r:
            return None
        wb = dict(r)
        wb["entries"] = _json_loads(wb.get("entries"), [])
        return wb
    finally:
        conn.close()


def save_worldbook(worldbook):
    """新增或更新单个世界书（有 id 则更新，否则新增）。"""
    conn = _connect()
    try:
        wb_id = worldbook.get("id") or new_id()
        entries = worldbook.get("entries", [])
        conn.execute(
            "INSERT OR REPLACE INTO worldbooks (id, name, description, entries, created_at) "
            "VALUES (?,?,?,?,?)",
            (wb_id, worldbook.get("name", ""), worldbook.get("description", ""),
             json.dumps(entries), worldbook.get("created_at", time.time())),
        )
        conn.commit()
        return wb_id
    finally:
        conn.close()


def delete_worldbook(wb_id):
    conn = _connect()
    try:
        conn.execute("DELETE FROM worldbooks WHERE id = ?", (wb_id,))
        conn.commit()
    finally:
        conn.close()


# ---- Chapter Version History ----

def snapshot_chapter(novel_id, chapter_idx, source="manual"):
    """把当前章节内容快照到 chapter_versions（仅当有 content 时）。"""
    n = get_novel(novel_id)
    if not n:
        return None
    ch = next((c for c in n.get("chapters", []) if c.get("index") == chapter_idx), None)
    if not ch or not ch.get("content"):
        return None
    conn = _connect()
    try:
        vid = new_id()
        conn.execute(
            "INSERT INTO chapter_versions (id, novel_id, chapter_idx, title, summary, "
            "content, word_count, source, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (vid, novel_id, chapter_idx, ch.get("title", ""), ch.get("summary", ""),
             ch["content"], ch.get("word_count", 0), source, time.time()),
        )
        conn.commit()
        return vid
    finally:
        conn.close()


def list_chapter_versions(novel_id, chapter_idx):
    """返回某章节的历史版本列表（按时间倒序）。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM chapter_versions WHERE novel_id=? AND chapter_idx=? ORDER BY created_at DESC",
            (novel_id, chapter_idx),
        )
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_chapter_version(version_id):
    """返回单个版本详情。"""
    conn = _connect()
    try:
        r = conn.execute("SELECT * FROM chapter_versions WHERE id=?", (version_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def delete_chapter_versions(novel_id, chapter_idx=None):
    """删除指定章节（或全部）的历史版本。"""
    conn = _connect()
    try:
        if chapter_idx is not None:
            conn.execute("DELETE FROM chapter_versions WHERE novel_id=? AND chapter_idx=?",
                         (novel_id, chapter_idx))
        else:
            conn.execute("DELETE FROM chapter_versions WHERE novel_id=?", (novel_id,))
        conn.commit()
    finally:
        conn.close()
