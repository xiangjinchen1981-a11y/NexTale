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
AUTH_PATH = DATA_DIR / "auth.json"

for _d in (DATA_DIR, UPLOAD_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULT_SETTINGS = {
    "text_model_id": "",
    "vision_model_id": "",
    # 每 100 目标字数对应的 max_tokens 安全系数
    "token_ratio": 1.6,
    "temperature": 0.8,
    # 最大输出 token 数（None 表示按字数自动估算）
    "max_tokens": None,
    # 模型上下文窗口长度（token），用于截断超长输入（None 表示不截断）
    "context_length": None,
    # 全局前置提示词：附加到所有生成请求，统一约束创作方向
    "global_prompt": "",
    # 各功能提示词模板（key -> 模板文本），空 dict 表示全部使用默认
    "prompts": {},
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  salt TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'user',
  created_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS providers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  api_key TEXT NOT NULL DEFAULT '',
  proxy TEXT NOT NULL DEFAULT 'direct',
  user_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS models (
  id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'text',
  temperature REAL,
  max_tokens INTEGER,
  context_length INTEGER,
  user_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  user_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS characters (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  appearance TEXT NOT NULL DEFAULT '',
  personality TEXT NOT NULL DEFAULT '',
  background TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  photo_path TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL DEFAULT 0,
  user_id TEXT NOT NULL DEFAULT ''
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
  worldbook_ids TEXT NOT NULL DEFAULT '[]',
  character_backgrounds TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL DEFAULT 0,
  deleted_at REAL NOT NULL DEFAULT 0,
  user_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chapters (
  id TEXT PRIMARY KEY,
  novel_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  word_count INTEGER NOT NULL DEFAULT 0,
  instruction TEXT NOT NULL DEFAULT '',
  user_id TEXT NOT NULL DEFAULT ''
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
  error TEXT NOT NULL DEFAULT '',
  user_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS genres (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  style TEXT NOT NULL DEFAULT '',
  reference_text TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL DEFAULT 0,
  user_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS worldbooks (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  entries TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL DEFAULT 0,
  user_id TEXT NOT NULL DEFAULT ''
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
  created_at REAL NOT NULL,
  user_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_models_provider ON models(provider_id);
CREATE INDEX IF NOT EXISTS idx_chapters_novel ON chapters(novel_id, idx);
CREATE INDEX IF NOT EXISTS idx_logs_created ON request_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_chapter_versions ON chapter_versions(novel_id, chapter_idx);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """轻量迁移：为旧库补齐新增列。"""
    # 为所有数据表添加 user_id 列
    _USER_ID_TABLES = [
        "providers", "models", "characters", "novels", "chapters",
        "genres", "worldbooks", "chapter_versions", "request_logs",
    ]
    for tbl in _USER_ID_TABLES:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")}
        if "user_id" not in cols:
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")

    # settings 表需要改主键结构（key -> key + user_id），通过重建表实现
    scols = {r[1] for r in conn.execute("PRAGMA table_info(settings)")}
    if "user_id" not in scols:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings_new (
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                user_id TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("INSERT INTO settings_new (key, value) SELECT key, value FROM settings")
        conn.execute("DROP TABLE settings")
        conn.execute("ALTER TABLE settings_new RENAME TO settings")

    # 原有列迁移（保持兼容）
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
    if "worldbook_ids" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN worldbook_ids TEXT NOT NULL DEFAULT '[]'")
    if "character_backgrounds" not in cols:
        conn.execute("ALTER TABLE novels ADD COLUMN character_backgrounds TEXT NOT NULL DEFAULT '{}'")

    mcols = {r[1] for r in conn.execute("PRAGMA table_info(models)")}
    if "context_length" not in mcols:
        conn.execute("ALTER TABLE models ADD COLUMN context_length INTEGER")

    ccols = {r[1] for r in conn.execute("PRAGMA table_info(chapters)")}
    if "instruction" not in ccols:
        conn.execute("ALTER TABLE chapters ADD COLUMN instruction TEXT NOT NULL DEFAULT ''")

    lcols = {r[1] for r in conn.execute("PRAGMA table_info(request_logs)")}
    if "name" not in lcols:
        conn.execute("ALTER TABLE request_logs ADD COLUMN name TEXT NOT NULL DEFAULT ''")

    charcols = {r[1] for r in conn.execute("PRAGMA table_info(characters)")}
    if "created_at" not in charcols:
        conn.execute("ALTER TABLE characters ADD COLUMN created_at REAL NOT NULL DEFAULT 0")

    # 数据迁移：若 users 表为空且旧 auth.json 存在，创建默认 admin 并将所有数据归属给它
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, salt TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user', created_at REAL NOT NULL DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY, user_id TEXT NOT NULL,
        created_at REAL NOT NULL, expires_at REAL NOT NULL)""")
    user_count = conn.execute("SELECT count(*) FROM users").fetchone()[0]
    if user_count == 0 and AUTH_PATH.exists():
        import hashlib as _hl
        import secrets as _sc
        try:
            auth = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
            old_hash = auth.get("password_hash", "")
            old_salt = auth.get("salt", "")
        except (json.JSONDecodeError, OSError):
            old_hash, old_salt = "", ""
        admin_id = uuid.uuid4().hex[:12]
        conn.execute(
            "INSERT INTO users (id, username, password_hash, salt, role, created_at) VALUES (?,?,?,?,?,?)",
            (admin_id, "admin", old_hash, old_salt, "admin", time.time()),
        )
        # 将所有无主数据归属给 admin
        for tbl in _USER_ID_TABLES + ["settings"]:
            conn.execute(f"UPDATE {tbl} SET user_id = ? WHERE user_id = ''", (admin_id,))
        AUTH_PATH.rename(AUTH_PATH.with_suffix(".json.bak"))


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
def list_providers(user_id=""):
    conn = _connect()
    try:
        providers = [dict(r) for r in conn.execute("SELECT * FROM providers WHERE user_id = ?", (user_id,))]
        for p in providers:
            rows = conn.execute(
                "SELECT * FROM models WHERE provider_id = ? AND user_id = ? ORDER BY rowid",
                (p["id"], user_id),
            )
            p["models"] = [dict(r) for r in rows]
        return providers
    finally:
        conn.close()


def save_providers(providers, user_id=""):
    conn = _connect()
    try:
        conn.execute("DELETE FROM models WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM providers WHERE user_id = ?", (user_id,))
        for p in providers:
            pid = p.get("id") or new_id()
            conn.execute(
                "INSERT INTO providers (id, name, base_url, api_key, proxy, user_id) VALUES (?,?,?,?,?,?)",
                (pid, p.get("name", ""), p.get("base_url", ""),
                 p.get("api_key", ""), p.get("proxy", "direct"), user_id),
            )
            for m in p.get("models", []):
                conn.execute(
                    "INSERT INTO models (id, provider_id, name, type, temperature, max_tokens, context_length, user_id) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (m.get("id") or new_id(), pid, m.get("name", ""),
                     m.get("type", "text"), m.get("temperature"), m.get("max_tokens"),
                     m.get("context_length"), user_id),
                )
        conn.commit()
    finally:
        conn.close()


def get_provider(provider_id, user_id=""):
    for p in list_providers(user_id):
        if p.get("id") == provider_id:
            return p
    return None


# ---- Settings ----
def get_settings(user_id=""):
    conn = _connect()
    try:
        rows = conn.execute("SELECT key, value FROM settings WHERE user_id = ?", (user_id,))
        stored = {}
        for k, v in rows:
            stored[k] = _json_loads(v, v)
        merged = dict(DEFAULT_SETTINGS)
        merged.update(stored)
        return {k: merged.get(k) for k in DEFAULT_SETTINGS}
    finally:
        conn.close()


def save_settings(settings, user_id=""):
    conn = _connect()
    try:
        conn.execute("DELETE FROM settings WHERE user_id = ?", (user_id,))
        for k in DEFAULT_SETTINGS:
            conn.execute(
                "INSERT INTO settings (key, value, user_id) VALUES (?,?,?)",
                (k, json.dumps(settings.get(k, DEFAULT_SETTINGS[k])), user_id),
            )
        conn.commit()
    finally:
        conn.close()


# ---- Characters ----
def list_characters(user_id=""):
    """按创建时间倒序返回所有角色（最新在前）。"""
    conn = _connect()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM characters WHERE user_id = ? ORDER BY created_at DESC", (user_id,))]
    finally:
        conn.close()


def save_characters(characters, user_id=""):
    conn = _connect()
    try:
        conn.execute("DELETE FROM characters WHERE user_id = ?", (user_id,))
        for c in characters:
            conn.execute(
                "INSERT INTO characters (id, name, appearance, personality, background, notes, photo_path, created_at, user_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (c.get("id") or new_id(), c.get("name", ""), c.get("appearance", ""),
                 c.get("personality", ""), c.get("background", ""), c.get("notes", ""),
                 c.get("photo_path", ""), c.get("created_at", time.time()), user_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_character(character_id, user_id=""):
    for c in list_characters(user_id):
        if c.get("id") == character_id:
            return c
    return None


# ---- Novels ----
def list_novels(user_id="", include_deleted=False):
    conn = _connect()
    try:
        if include_deleted:
            novels = [dict(r) for r in conn.execute("SELECT * FROM novels WHERE user_id = ?", (user_id,))]
        else:
            novels = [dict(r) for r in conn.execute("SELECT * FROM novels WHERE user_id = ? AND deleted_at = 0", (user_id,))]
        for n in novels:
            n["character_ids"] = _json_loads(n["character_ids"], [])
            n["relationships"] = _json_loads(n["relationships"], [])
            n["dialog_messages"] = _json_loads(n.get("dialog_messages"), [])
            n["worldbook_ids"] = _json_loads(n.get("worldbook_ids"), [])
            n["character_backgrounds"] = _json_loads(n.get("character_backgrounds"), {})
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


def list_deleted_novels(user_id=""):
    """返回垃圾箱内的小说（仅元信息，不含章节）。"""
    conn = _connect()
    try:
        novels = [dict(r) for r in conn.execute("SELECT * FROM novels WHERE user_id = ? AND deleted_at != 0 ORDER BY deleted_at DESC", (user_id,))]
        for n in novels:
            n["character_ids"] = _json_loads(n["character_ids"], [])
            n["relationships"] = _json_loads(n["relationships"], [])
            n["chapters"] = []
        return novels
    finally:
        conn.close()


def save_novels(novels, user_id=""):
    """按 id upsert 保存小说（不清空已删除记录，避免垃圾箱数据丢失）。"""
    conn = _connect()
    try:
        for n in novels:
            nid = n.get("id") or new_id()
            conn.execute(
                "INSERT OR REPLACE INTO novels (id, title, genre, style, reference_text, character_ids, "
                "relationships, chapter_count, words_per_chapter, summary, worldbuilding, background, "
                "progress_summary, status, text_model_id, mode, dialog_messages, worldbuilding_source, "
                "source_text, task_instruction, structured_profile, worldbook_ids, character_backgrounds, "
                "created_at, deleted_at, user_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                 json.dumps(n.get("worldbook_ids", [])),
                 json.dumps(n.get("character_backgrounds", {})),
                 n.get("created_at", 0), n.get("deleted_at", 0), user_id),
            )
            conn.execute("DELETE FROM chapters WHERE novel_id = ?", (nid,))
            for c in n.get("chapters", []):
                conn.execute(
                    "INSERT INTO chapters (id, novel_id, idx, title, summary, content, word_count, instruction, user_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"{nid}:{c.get('index', 0)}", nid, c.get("index", 0),
                     c.get("title", ""), c.get("summary", ""), c.get("content", ""),
                     c.get("word_count", 0), c.get("instruction", ""), user_id),
                )
        conn.commit()
    finally:
        conn.close()


def get_novel(novel_id, user_id=""):
    for n in list_novels(user_id):
        if n.get("id") == novel_id:
            return n
    return None


def update_novel(novel_id, user_id="", mutator=None):
    novels = list_novels(user_id, include_deleted=True)
    for n in novels:
        if n.get("id") == novel_id:
            mutator(n)
            save_novels(novels, user_id)
            return n
    return None


def trash_novel(novel_id, user_id=""):
    """软删除：标记进垃圾箱。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE novels SET deleted_at = ? WHERE id = ? AND user_id = ? AND deleted_at = 0",
            (time.time(), novel_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def restore_novel(novel_id, user_id=""):
    """从垃圾箱恢复。"""
    conn = _connect()
    try:
        cur = conn.execute(
            "UPDATE novels SET deleted_at = 0 WHERE id = ? AND user_id = ?", (novel_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def destroy_novel(novel_id, user_id=""):
    """彻底删除小说及其章节。"""
    conn = _connect()
    try:
        conn.execute("DELETE FROM chapters WHERE novel_id = ? AND user_id = ?", (novel_id, user_id))
        cur = conn.execute("DELETE FROM novels WHERE id = ? AND user_id = ?", (novel_id, user_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---- AI 请求日志 ----
def add_log(kind, provider, model, prompt, status="ok", elapsed=0.0,
            prompt_tokens=None, completion_tokens=None, error="", name="", user_id=""):
    """记录一次 AI 请求。"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO request_logs (id, created_at, kind, name, provider, model, prompt, "
            "status, elapsed, prompt_tokens, completion_tokens, error, user_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id(), time.time(), kind, name, provider, model, prompt,
             status, elapsed, prompt_tokens, completion_tokens, error, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_logs(user_id="", limit=200, offset=0):
    """按时间倒序返回日志列表（支持分页）。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM request_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_logs(user_id=""):
    """返回日志总条数。"""
    conn = _connect()
    try:
        return conn.execute("SELECT count(*) FROM request_logs WHERE user_id = ?", (user_id,)).fetchone()[0]
    finally:
        conn.close()


# ---- 用户管理 ----

def _hash_password(password: str, salt: str = "") -> tuple:
    """返回 (password_hash, salt)。"""
    import hashlib
    if not salt:
        import secrets
        salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return h, salt


def has_users() -> bool:
    """是否已有用户（用于前端判断是创建管理员还是登录）。"""
    conn = _connect()
    try:
        return conn.execute("SELECT count(*) FROM users").fetchone()[0] > 0
    finally:
        conn.close()


def create_user(username: str, password: str, role: str = "user") -> dict:
    """创建用户，返回用户信息。用户名重复抛 ValueError。"""
    conn = _connect()
    try:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise ValueError(f"用户名 '{username}' 已存在")
        uid = new_id()
        h, salt = _hash_password(password)
        conn.execute(
            "INSERT INTO users (id, username, password_hash, salt, role, created_at) VALUES (?,?,?,?,?,?)",
            (uid, username, h, salt, role, time.time()),
        )
        conn.commit()
        return {"id": uid, "username": username, "role": role}
    finally:
        conn.close()


def verify_user_password(username: str, password: str) -> dict | None:
    """验证用户名+密码，成功返回用户 dict（含 id, username, role），失败返回 None。"""
    conn = _connect()
    try:
        import hashlib
        r = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not r:
            return None
        u = dict(r)
        h = hashlib.sha256((u["salt"] + password).encode("utf-8")).hexdigest()
        if h != u["password_hash"]:
            return None
        return {"id": u["id"], "username": u["username"], "role": u["role"]}
    finally:
        conn.close()


def list_users() -> list:
    """返回所有用户（不含密码信息）。"""
    conn = _connect()
    try:
        rows = conn.execute("SELECT id, username, role, created_at FROM users ORDER BY created_at")
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_user(user_id: str) -> dict | None:
    conn = _connect()
    try:
        r = conn.execute("SELECT id, username, role, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def update_user_password(user_id: str, new_password: str) -> None:
    conn = _connect()
    try:
        h, salt = _hash_password(new_password)
        conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE id = ?", (h, salt, user_id))
        conn.commit()
    finally:
        conn.close()


def update_user_role(user_id: str, role: str) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
        conn.commit()
    finally:
        conn.close()


def delete_user(user_id: str) -> None:
    """删除用户及其所有关联数据。"""
    conn = _connect()
    try:
        # 删除该用户的所有数据
        tables = ["providers", "models", "characters", "novels", "chapters",
                   "genres", "worldbooks", "chapter_versions", "request_logs", "settings", "sessions"]
        for tbl in tables:
            conn.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


# ---- 会话管理 ----
SESSION_TTL = 7 * 24 * 3600  # 7 天


def create_session(user_id: str) -> str:
    """创建会话，返回 token。"""
    import secrets
    token = secrets.token_urlsafe(32)
    now = time.time()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
            (token, user_id, now, now + SESSION_TTL),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def get_session(token: str) -> str | None:
    """验证 token 是否有效，返回 user_id 或 None。"""
    if not token:
        return None
    conn = _connect()
    try:
        r = conn.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token = ?", (token,)
        ).fetchone()
        if not r or r["expires_at"] < time.time():
            return None
        return r["user_id"]
    finally:
        conn.close()


def delete_session(token: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


def cleanup_expired_sessions() -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        conn.commit()
    finally:
        conn.close()


# ---- 题材库 ----
def list_genres(user_id=""):
    """返回所有题材（按创建时间倒序）。"""
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM genres WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_genre(genre_id, user_id=""):
    conn = _connect()
    try:
        r = conn.execute("SELECT * FROM genres WHERE id = ? AND user_id = ?", (genre_id, user_id)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def save_genre(genre, user_id=""):
    """新增或更新单个题材（有 id 则更新，否则新增）。"""
    conn = _connect()
    try:
        gid = genre.get("id") or new_id()
        conn.execute(
            "INSERT OR REPLACE INTO genres (id, name, style, reference_text, description, created_at, user_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (gid, genre.get("name", ""), genre.get("style", ""),
             genre.get("reference_text", ""), genre.get("description", ""),
             genre.get("created_at", time.time()), user_id),
        )
        conn.commit()
        return gid
    finally:
        conn.close()


def save_genres(genres, user_id=""):
    """批量保存（导入时用），返回保存数量。"""
    conn = _connect()
    try:
        for g in genres:
            gid = g.get("id") or new_id()
            conn.execute(
                "INSERT OR REPLACE INTO genres (id, name, style, reference_text, description, created_at, user_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (gid, g.get("name", ""), g.get("style", ""),
                 g.get("reference_text", ""), g.get("description", ""),
                 g.get("created_at", time.time()), user_id),
            )
        conn.commit()
        return len(genres)
    finally:
        conn.close()


def delete_genre(genre_id, user_id=""):
    conn = _connect()
    try:
        conn.execute("DELETE FROM genres WHERE id = ? AND user_id = ?", (genre_id, user_id))
        conn.commit()
    finally:
        conn.close()


# ---- 世界书 ----
def list_worldbooks(user_id=""):
    """返回所有世界书（按创建时间倒序），entries 解析为列表。"""
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM worldbooks WHERE user_id = ? ORDER BY created_at DESC", (user_id,))
        result = []
        for r in rows:
            wb = dict(r)
            wb["entries"] = _json_loads(wb.get("entries"), [])
            result.append(wb)
        return result
    finally:
        conn.close()


def get_worldbook(wb_id, user_id=""):
    conn = _connect()
    try:
        r = conn.execute("SELECT * FROM worldbooks WHERE id = ? AND user_id = ?", (wb_id, user_id)).fetchone()
        if not r:
            return None
        wb = dict(r)
        wb["entries"] = _json_loads(wb.get("entries"), [])
        return wb
    finally:
        conn.close()


def save_worldbook(worldbook, user_id=""):
    """新增或更新单个世界书（有 id 则更新，否则新增）。"""
    conn = _connect()
    try:
        wb_id = worldbook.get("id") or new_id()
        entries = worldbook.get("entries", [])
        conn.execute(
            "INSERT OR REPLACE INTO worldbooks (id, name, description, entries, created_at, user_id) "
            "VALUES (?,?,?,?,?,?)",
            (wb_id, worldbook.get("name", ""), worldbook.get("description", ""),
             json.dumps(entries), worldbook.get("created_at", time.time()), user_id),
        )
        conn.commit()
        return wb_id
    finally:
        conn.close()


def delete_worldbook(wb_id, user_id=""):
    conn = _connect()
    try:
        conn.execute("DELETE FROM worldbooks WHERE id = ? AND user_id = ?", (wb_id, user_id))
        conn.commit()
    finally:
        conn.close()


# ---- Chapter Version History ----

def snapshot_chapter(novel_id, chapter_idx, source="manual", user_id=""):
    """把当前章节内容快照到 chapter_versions（仅当有 content 时）。"""
    n = get_novel(novel_id, user_id)
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
            "content, word_count, source, created_at, user_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (vid, novel_id, chapter_idx, ch.get("title", ""), ch.get("summary", ""),
             ch["content"], ch.get("word_count", 0), source, time.time(), user_id),
        )
        conn.commit()
        return vid
    finally:
        conn.close()


def list_chapter_versions(novel_id, chapter_idx, user_id=""):
    """返回某章节的历史版本列表（按时间倒序）。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM chapter_versions WHERE novel_id=? AND chapter_idx=? AND user_id=? ORDER BY created_at DESC",
            (novel_id, chapter_idx, user_id),
        )
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_chapter_version(version_id, user_id=""):
    """返回单个版本详情。"""
    conn = _connect()
    try:
        r = conn.execute("SELECT * FROM chapter_versions WHERE id=? AND user_id=?", (version_id, user_id)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def delete_chapter_versions(novel_id, chapter_idx=None, user_id=""):
    """删除指定章节（或全部）的历史版本。"""
    conn = _connect()
    try:
        if chapter_idx is not None:
            conn.execute("DELETE FROM chapter_versions WHERE novel_id=? AND chapter_idx=? AND user_id=?",
                         (novel_id, chapter_idx, user_id))
        else:
            conn.execute("DELETE FROM chapter_versions WHERE novel_id=? AND user_id=?", (novel_id, user_id))
        conn.commit()
    finally:
        conn.close()
