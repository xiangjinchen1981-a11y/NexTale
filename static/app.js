// ============ 全局状态 ============
let state = {
  providers: [],
  presets: {},
  settings: {},
  characters: [],      // 全局角色库
  genres: [],          // 题材库
  novels: [],
  novel: null,         // 当前创作的小说
  relations: [],       // 当前小说的临时关系列表
  wizardStep: 1,       // 1=基本信息 2=角色设定 3=生成
  editingProviderId: null,
  editingModel: null,
  modelLists: {},
  addModelOpen: null,
  editingGenreId: null, // 正在编辑的题材 id
};

// 章节编辑状态（当前正在编辑的章节 index，null 表示未编辑）
let chapterEditing = null;

// 登录 token（持久化到 localStorage）
let authToken = localStorage.getItem('novel_token') || '';

// ============ 工具函数 ============
const $ = (id) => document.getElementById(id);

// ============ 夜间模式 ============
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = $('btn-theme');
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  const next = cur === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  localStorage.setItem('novel_theme', next);
}

// 初始化主题（读取 localStorage，默认浅色）
(function initTheme() {
  const saved = localStorage.getItem('novel_theme') || 'light';
  applyTheme(saved);
})();

async function api(path, opts = {}) {
  opts = opts || {};
  const headers = opts.headers || {};
  // 自动附带认证 token
  if (authToken) {
    headers['Authorization'] = 'Bearer ' + authToken;
  }
  const res = await fetch(path, { ...opts, headers });
  let data = null;
  try { data = await res.json(); } catch (e) { /* 非 JSON */ }
  if (res.status === 401) {
    // 登录失效，跳转登录页
    handleUnauthorized();
    throw new Error((data && data.detail) ? data.detail : '未登录或登录已过期');
  }
  if (!res.ok) {
    let detail = data && data.detail;
    // FastAPI 422 校验错误时 detail 是数组对象，需提取可读信息，避免显示 [object Object]
    if (Array.isArray(detail)) {
      detail = detail.map(x => x && x.msg ? x.msg : JSON.stringify(x)).join('；');
    } else if (detail && typeof detail === 'object') {
      detail = detail.message || JSON.stringify(detail);
    }
    const msg = detail ? String(detail) : `请求失败(${res.status})`;
    throw new Error(msg);
  }
  return data;
}

function toast(msg, type = '') {
  const t = $('toast');
  // 防御：若 msg 不是字符串（如对象），转为可读字符串
  if (typeof msg !== 'string') {
    try { msg = msg.message || JSON.stringify(msg); } catch (e) { msg = String(msg); }
  }
  t.textContent = msg;
  t.className = 'toast show ' + type;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.className = 'toast', 3200);
}

// 全屏加载遮罩：带进度条（可传入标题与副标题）
function showLoading(title = '处理中…', sub = '') {
  const ov = $('loading-overlay');
  const t = $('loading-title');
  const s = $('loading-sub');
  const bar = $('loading-bar-fill');
  if (t) t.textContent = title;
  if (s) s.textContent = sub;
  if (bar) bar.style.width = '0%';
  ov.classList.add('show');
  // 模拟不确定进度：缓慢前进到 90%，不加载完
  let p = 0;
  clearInterval(ov._timer);
  ov._timer = setInterval(() => {
    p = Math.min(p + (0.8 + Math.random() * 1.5), 90);
    if (bar) bar.style.width = p + '%';
  }, 200);
}

function hideLoading() {
  const ov = $('loading-overlay');
  clearInterval(ov._timer);
  ov.classList.remove('show');
}

// ============ 用户认证 ============
let currentUser = null;

async function prepareLogin() {
  try {
    const res = await fetch('/api/auth/status');
    const d = await res.json();
    const loginCard = document.querySelector('#view-login .login-card');
    const regCard = $('register-card');
    if (d.has_users) {
      loginCard.style.display = '';
      if (regCard) regCard.style.display = 'none';
    } else {
      loginCard.style.display = 'none';
      if (regCard) regCard.style.display = '';
    }
    const pwd = $('login-password');
    if (pwd) pwd.value = '';
    const uname = $('login-username');
    if (uname) uname.value = '';
  } catch (e) {}
}

async function doLogin() {
  const username = ($('login-username') || {}).value || '';
  const password = ($('login-password') || {}).value || '';
  if (!username || !password) { toast('请输入用户名和密码', 'err'); return; }
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const d = await res.json();
    if (!res.ok) { toast(d.detail || '登录失败', 'err'); return; }
    authToken = d.token;
    currentUser = d.user;
    localStorage.setItem('novel_token', authToken);
    toast('登录成功', 'ok');
    onLoginSuccess();
  } catch (e) { toast('登录失败：' + e.message, 'err'); }
}

async function doRegister() {
  const username = ($('reg-username') || {}).value || '';
  const password = ($('reg-password') || {}).value || '';
  const password2 = ($('reg-password2') || {}).value || '';
  if (!username || !password) { toast('请输入用户名和密码', 'err'); return; }
  if (password !== password2) { toast('两次密码不一致', 'err'); return; }
  if (password.length < 4) { toast('密码至少 4 个字符', 'err'); return; }
  try {
    const res = await fetch('/api/auth/register', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const d = await res.json();
    if (!res.ok) { toast(d.detail || '注册失败', 'err'); return; }
    authToken = d.token;
    currentUser = d.user;
    localStorage.setItem('novel_token', authToken);
    toast('管理员已创建', 'ok');
    onLoginSuccess();
  } catch (e) { toast('注册失败：' + e.message, 'err'); }
}

async function onLoginSuccess() {
  updateUserUI();
  try {
    await loadSettings();
    await loadProviders();
    await loadAllCharacters();
    await loadGenres();
  } catch (e) {}
  location.hash = '#/novels';
  await router();
}

function toggleUserDropdown() {
  const menu = $('user-dropdown-menu');
  if (menu) menu.classList.toggle('open');
}

function closeUserDropdown() {
  const menu = $('user-dropdown-menu');
  if (menu) menu.classList.remove('open');
}

document.addEventListener('click', (e) => {
  if (!e.target.closest('.user-dropdown')) closeUserDropdown();
});

function updateUserUI() {
  const dropdown = $('user-dropdown');
  const badge = $('user-badge');
  const btnUsers = $('btn-users');
  if (currentUser) {
    if (badge) badge.textContent = currentUser.username;
    if (dropdown) dropdown.style.display = '';
    if (btnUsers) btnUsers.style.display = currentUser.role === 'admin' ? '' : 'none';
  } else {
    if (dropdown) dropdown.style.display = 'none';
    if (btnUsers) btnUsers.style.display = 'none';
  }
  closeUserDropdown();
}

function logout() {
  fetch('/api/auth/logout', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + authToken },
  }).catch(() => {});
  authToken = '';
  currentUser = null;
  localStorage.removeItem('novel_token');
  updateUserUI();
  location.hash = '#/login';
  showView('login');
  prepareLogin();
}

function handleUnauthorized() {
  authToken = '';
  currentUser = null;
  localStorage.removeItem('novel_token');
  updateUserUI();
  location.hash = '#/login';
  showView('login');
  prepareLogin();
}

// ============ 用户管理 ============
async function loadUsers() {
  try {
    const d = await api('/api/users');
    renderUsers(d);
  } catch (e) {}
}

function renderUsers(users) {
  const el = $('user-list');
  if (!el) return;
  if (!users || !users.length) {
    el.innerHTML = '<p class="hint">暂无其他用户</p>';
    return;
  }
  el.innerHTML = `<table class="user-table"><thead><tr>
    <th>用户名</th><th>角色</th><th>创建时间</th><th>操作</th>
    </tr></thead><tbody>
    ${users.map(u => `<tr>
      <td>${esc(u.username)}</td>
      <td>${u.role === 'admin' ? '管理员' : '普通用户'}</td>
      <td>${u.created_at ? new Date(u.created_at * 1000).toLocaleString('zh-CN', {hour12: false}) : '-'}</td>
      <td>
        <button class="btn btn-sm" onclick="changeUserPassword('${u.id}', '${esc(u.username)}')">改密码</button>
        <button class="btn btn-sm" onclick="toggleUserRole('${u.id}', '${u.role}')">${u.role === 'admin' ? '降为普通' : '升为管理'}</button>
        <button class="btn btn-sm btn-danger" onclick="deleteUser('${u.id}', '${esc(u.username)}')">删除</button>
      </td>
    </tr>`).join('')}
    </tbody></table>`;
}

async function createUser() {
  const username = ($('new-username') || {}).value || '';
  const password = ($('new-password') || {}).value || '';
  const role = ($('new-role') || {}).value || 'user';
  if (!username || !password) { toast('请输入用户名和密码', 'err'); return; }
  try {
    await api('/api/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, role }),
    });
    toast('用户已创建', 'ok');
    $('new-username').value = '';
    $('new-password').value = '';
    await loadUsers();
  } catch (e) { toast(e.message, 'err'); }
}

async function deleteUser(uid, name) {
  if (!confirm(`确定删除用户「${name}」？该用户的所有数据将被清除。`)) return;
  try {
    await api(`/api/users/${uid}`, { method: 'DELETE' });
    toast('用户已删除', 'ok');
    await loadUsers();
  } catch (e) { toast(e.message, 'err'); }
}

async function changeUserPassword(uid, name) {
  const pw = prompt(`为用户「${name}」设置新密码（至少4位）：`);
  if (!pw) return;
  if (pw.length < 4) { toast('密码至少 4 个字符', 'err'); return; }
  try {
    await api(`/api/users/${uid}/password`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_password: pw }),
    });
    toast('密码已更新', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

async function toggleUserRole(uid, currentRole) {
  const newRole = currentRole === 'admin' ? 'user' : 'admin';
  try {
    await api(`/api/users/${uid}/role`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: newRole }),
    });
    toast('角色已更新', 'ok');
    await loadUsers();
  } catch (e) { toast(e.message, 'err'); }
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function maskKey(k) {
  if (!k) return '（未填写）';
  if (k.length <= 8) return k;
  return k.slice(0, 4) + '••••••' + k.slice(-4);
}

// ============ 视图 / 路由 ============
// 视图列表：login（登录）、providers（配置）、genres（题材库）、worldbooks（世界书）、novels（列表）、trash（垃圾箱）、editor（创作）、generate（生成）、chapter（章节详情）、reader（阅读）、improv（即兴写作）、dialog（对话模式）、logs（请求日志）
const VIEWS = ['login', 'users', 'providers', 'genres', 'worldbooks', 'characters', 'character-new', 'character-detail', 'novels', 'library', 'trash', 'editor', 'generate', 'chapter', 'reader', 'improv', 'dialog', 'rewrite', 'continue', 'logs'];

// 当前小说 id（用于创作/生成页定位）
let currentNovelId = null;

function showView(name) {
  VIEWS.forEach(v => {
    const el = $('view-' + v);
    if (el) el.style.display = (v === name) ? 'block' : 'none';
  });
  // 登录页时隐藏顶部导航；其他页面显示
  const isLogin = name === 'login';
  const tabs = $('main-tabs');
  const providersBtn = $('btn-providers');
  const usersBtn = $('btn-users');
  const userDropdown = $('user-dropdown');
  if (tabs) tabs.style.display = isLogin ? 'none' : '';
  if (providersBtn) providersBtn.style.display = isLogin ? 'none' : '';
  if (usersBtn) usersBtn.style.display = (isLogin || !currentUser || currentUser.role !== 'admin') ? 'none' : '';
  if (userDropdown) userDropdown.style.display = (isLogin || !currentUser) ? 'none' : '';
  // 顶部标签高亮（providers/配置页 与 login 不点亮任何标签）
  document.querySelectorAll('.tab').forEach(b => {
    const tab = b.dataset.tab;
    let active = false;
    if (tab === 'genres') active = (name === 'genres');
    else if (tab === 'worldbooks') active = (name === 'worldbooks');
    else if (tab === 'characters') active = (name === 'characters' || name === 'character-new' || name === 'character-detail');
    else if (tab === 'library') active = (name === 'library');
    else if (tab === 'logs') active = (name === 'logs');
    else if (tab === 'novels') active = (name !== 'genres' && name !== 'worldbooks' && name !== 'characters' && name !== 'character-new' && name !== 'character-detail' && name !== 'library' && name !== 'logs' && name !== 'login' && name !== 'providers' && name !== 'users');
    b.classList.toggle('active', active);
  });
  // 视图切换时触发对应数据加载
  if (name === 'providers') { switchConfigTab('api'); loadProviders(); }
  if (name === 'genres') { loadGenres(); }
  if (name === 'worldbooks') { loadWorldbooks(); }
  if (name === 'novels') { loadNovels(); }
  if (name === 'trash') { loadTrash(); }
  if (name === 'logs') { loadLogs(); }
}

// 解析 hash 路由
function parseRoute() {
  const hash = window.location.hash || '#/novels';
  // 形如 #/novels、#/novels/new、#/novels/:id/edit、#/novels/:id/generate
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  return parts; // e.g. ['novels'] 或 ['novels','new'] 或 ['novels','id','edit']
}

// 路由分发
async function router() {
  const parts = parseRoute();
  const section = parts[0] || 'novels';

  // 登录态校验：未登录一律进入登录页
  if (!authToken) {
    showView('login');
    await prepareLogin();
    return;
  }

  if (section === 'providers') {
    showView('providers');
    return;
  }

  if (section === 'users') {
    showView('users');
    await loadUsers();
    return;
  }

  if (section === 'genres') {
    showView('genres');
    return;
  }

  if (section === 'worldbooks') {
    showView('worldbooks');
    return;
  }

  if (section === 'characters') {
    if (parts.length === 1) {
      // 角色库列表页
      resumeWizardStep = null;
      showView('characters');
      await loadCharacterNovels();       // 加载小说下拉
      await loadCharacters('');          // 默认加载最新 20 个角色
      renderCharacterGrid();
      return;
    }
    if (parts[1] === 'new') {
      // 添加角色页
      showView('character-new');
      resetCharacterNewForm();
      return;
    }
    // /characters/:id 角色详情页
    showView('character-detail');
    await openCharacterDetail(parts[1]);
    return;
  }

  if (section === 'logs') {
    showView('logs');
    return;
  }

  if (section === 'library') {
    showView('library');
    await loadLibrary();
    return;
  }

  if (section === 'trash') {
    showView('trash');
    return;
  }

  if (section !== 'novels') {
    showView('novels');
    return;
  }

  // /novels 或 /novels/new
  if (parts.length === 1) {
    currentNovelId = null;
    showView('novels');
    return;
  }

  if (parts[1] === 'new') {
    // 新建小说 → 创作页
    showView('editor');
    newNovel();
    return;
  }

  // parts[1] 是小说 id
  const id = parts[1];
  currentNovelId = id;
  const sub = parts[2];

  if (sub === 'generate') {
    // 章节生成页
    showView('generate');
    await openGeneratePage(id);
    return;
  }

  if (sub === 'chapter' && parts[3]) {
    // 章节详情/生成页：#/novels/:id/chapter/:index
    showView('chapter');
    await openChapterPage(id, parseInt(parts[3], 10));
    return;
  }

  if (sub === 'read') {
    // 阅读模式：#/novels/:id/read
    showView('reader');
    await openReaderPage(id);
    return;
  }

  if (sub === 'improv') {
    // 即兴交互式写作：#/novels/:id/improv
    showView('improv');
    await openImprovPage(id);
    return;
  }

  if (sub === 'dialog') {
    // 对话模式：#/novels/:id/dialog
    showView('dialog');
    await openDialogPage(id);
    return;
  }

  if (sub === 'rewrite') {
    // 改写模式：#/novels/:id/rewrite
    showView('rewrite');
    await openRewritePage(id);
    return;
  }

  if (sub === 'continue') {
    // 续写模式：#/novels/:id/continue
    showView('continue');
    await openContinuePage(id);
    return;
  }

  // 默认：编辑创作页
  showView('editor');
  await openEditorPage(id);
}

window.addEventListener('hashchange', router);

// 编程式导航
function nav(hash) {
  window.location.hash = hash;
}

// ============ 标签切换（顶部导航） ============
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    if (tab === 'genres') {
      nav('#/genres');
    } else if (tab === 'worldbooks') {
      nav('#/worldbooks');
    } else if (tab === 'characters') {
      nav('#/characters');
    } else if (tab === 'library') {
      nav('#/library');
    } else if (tab === 'logs') {
      nav('#/logs');
    } else {
      nav('#/novels');
    }
  });
});

// ================= API 配置 =================
async function loadProviders() {
  const d = await api('/api/providers');
  state.providers = d.providers;
  state.presets = d.presets || {};
  renderProviders();
  const sel = $('preset-select');
  sel.innerHTML = '<option value="">自定义</option>';
  Object.entries(state.presets).forEach(([name, url]) => {
    const o = document.createElement('option');
    o.value = url; o.textContent = name;
    sel.appendChild(o);
  });
  sel.onchange = () => {
    if (sel.value) $('p-base').value = sel.value;
    if (sel.value && !$('p-name').value) $('p-name').value = sel.selectedOptions[0].textContent;
  };
  loadPromptConfig();
}

// ================= 配置页子 Tab 切换 =================
function switchConfigTab(name) {
  const apiEl = $('config-tab-api');
  const promptEl = $('config-tab-prompt');
  if (apiEl) apiEl.style.display = name === 'api' ? 'block' : 'none';
  if (promptEl) promptEl.style.display = name === 'prompt' ? 'block' : 'none';
  // 子 tab 高亮
  document.querySelectorAll('#config-sub-tabs .sub-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.subtab === name);
  });
  // 切换到提示词 tab 时刷新提示词配置
  if (name === 'prompt') loadPromptConfig();
}

// ================= 提示词配置 =================
let promptConfigState = { defs: {}, custom: {} };  // 缓存的提示词定义与自定义值

async function loadPromptConfig() {
  try {
    const d = await api('/api/prompts');
    promptConfigState.defs = d.defs || {};
    promptConfigState.custom = d.custom || {};
  } catch (e) { /* 忽略，页面仍可用 */ }
  renderPromptConfig();
}

function renderPromptConfig() {
  const box = $('prompt-config-list');
  if (!box) return;
  const defs = promptConfigState.defs;
  const custom = promptConfigState.custom;
  const keys = Object.keys(defs);
  if (!keys.length) return;

  box.innerHTML = keys.map(key => {
    const d = defs[key];
    const isCustom = custom[key] && custom[key].trim();
    // 变量说明
    const varList = Object.entries(d.vars || {}).map(([v, desc]) => `<code>{${v}}</code><span class="prompt-var-desc">${esc(desc)}</span>`).join('');
    return `
    <div class="card prompt-config-item" data-key="${key}">
      <div class="row">
        <span class="title">${esc(d.label)}</span>
        <span class="badge ${isCustom ? 'prompt-custom-badge' : ''}">${isCustom ? '已自定义' : '默认'}</span>
        <span class="spacer"></span>
        <button class="btn" onclick="togglePromptEditor('${key}')">编辑</button>
        <button class="btn danger" onclick="resetPrompt('${key}')" ${isCustom ? '' : 'disabled'}>恢复默认</button>
      </div>
      <div class="meta">${esc(d.desc || '')}</div>
      ${varList ? `<div class="prompt-vars">${varList}</div>` : ''}
      <div class="prompt-editor" id="prompt-editor-${key}" style="display:none">
        <textarea class="prompt-editor-ta" id="prompt-ta-${key}" rows="10">${esc(custom[key] || '')}</textarea>
        <div class="row" style="margin-top:8px">
          <button class="btn primary" onclick="savePrompt('${key}')">保存</button>
          <button class="btn" onclick="cancelPromptEdit('${key}')">取消</button>
          <span class="hint">留空并保存即恢复默认</span>
        </div>
      </div>
    </div>`;
  }).join('');
}

function togglePromptEditor(key) {
  const ed = $('prompt-editor-' + key);
  if (!ed) return;
  const isHidden = ed.style.display === 'none';
  ed.style.display = isHidden ? 'block' : 'none';
  if (isHidden) {
    const ta = $('prompt-ta-' + key);
    if (ta && !ta.value && promptConfigState.defs[key]) {
      ta.placeholder = promptConfigState.defs[key].default.slice(0, 200) + '……（当前使用默认模板）';
    }
  }
}

function cancelPromptEdit(key) {
  const ed = $('prompt-editor-' + key);
  if (ed) ed.style.display = 'none';
}

async function savePrompt(key) {
  const ta = $('prompt-ta-' + key);
  if (!ta) return;
  const val = ta.value;
  try {
    const d = await api('/api/prompts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompts: { [key]: val } }),
    });
    promptConfigState.custom = d.prompts || {};
    renderPromptConfig();
    toast(val.trim() ? '提示词已保存' : '已恢复默认', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

async function resetPrompt(key) {
  if (!confirm('确定恢复该提示词为默认模板？')) return;
  try {
    const d = await api('/api/prompts', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompts: { [key]: '' } }),
    });
    promptConfigState.custom = d.prompts || {};
    renderPromptConfig();
    toast('已恢复默认', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

function proxyLabel(p) {
  if (p.proxy === 'system') return '系统代理';
  if (p.proxy && p.proxy !== 'direct') return '自定义代理';
  return '直连';
}

function renderProviders() {
  const box = $('provider-list');
  const s = state.settings;
  box.innerHTML = state.providers.length
    ? state.providers.map(p => {
        const models = p.models || [];
        const list = state.modelLists[p.id] || [];
        const open = state.addModelOpen === p.id;
        const modelsHtml = models.map(m => {
          const isText = s.text_model_id === m.id;
          const isVision = s.vision_model_id === m.id;
          return `
        <div class="model-item">
          <span class="title">${esc(m.name)}</span>
          <span class="badge ${m.type === 'vision' ? 'badge-vision' : ''}">${m.type === 'vision' ? '视觉' : '文本'}</span>
          ${m.temperature != null && m.temperature !== '' ? `<span class="meta">temp=${m.temperature}</span>` : ''}
          ${m.max_tokens ? `<span class="meta">max_tokens=${m.max_tokens}</span>` : ''}
          ${m.context_length ? `<span class="meta">上下文=${m.context_length}</span>` : ''}
          <span class="spacer"></span>
          <button class="btn role-mark ${isText ? 'on' : ''}" onclick="setModelRole('${p.id}','${m.id}','text')" title="设为当前文本生成模型">${isText ? '●' : '○'}文本</button>
          <button class="btn role-mark ${isVision ? 'on' : ''}" onclick="setModelRole('${p.id}','${m.id}','vision')" title="设为当前视觉分析模型">${isVision ? '●' : '○'}视觉</button>
          <button class="btn" onclick="testModel('${p.id}','${m.id}')">测试</button>
          <button class="btn" onclick="editModel('${p.id}','${m.id}')">编辑</button>
          <button class="btn danger" onclick="deleteModel('${p.id}','${m.id}')">删除</button>
        </div>`;
        }).join('');

        return `
      <div class="card">
        <div class="row">
          <span class="title">${esc(p.name)}</span>
          <span class="badge">${proxyLabel(p)}</span>
          <span class="spacer"></span>
          <button class="btn" id="btn-connect-${p.id}" onclick="connectProvider('${p.id}')">🔌 连接</button>
          <button class="btn" onclick="startEditProvider('${p.id}')">编辑服务商</button>
          <button class="btn danger" onclick="deleteProvider('${p.id}')">删除</button>
        </div>
        <div class="meta">${esc(p.base_url)}</div>
        <div class="meta mask">Key: ${esc(maskKey(p.api_key))}</div>
        <div class="meta">连接：<span id="connect-status-${p.id}">${list.length ? `已缓存 ${list.length} 个模型` : '未连接'}</span></div>
        <div class="model-section">
          <div class="row" style="margin:10px 0 6px">
            <span class="meta"><b>模型（${models.length}）</b></span>
            <span class="spacer"></span>
            <button class="btn" onclick="toggleAddModel('${p.id}')">${open ? '收起' : '＋ 添加模型'}</button>
          </div>
          ${modelsHtml || '<div class="meta" style="margin:4px 0">暂无模型，先「连接」拉取列表再添加。</div>'}
          ${renderModelForm(p, open)}
        </div>
      </div>`;
      }).join('')
    : '<div class="card meta">暂无服务商，请在下方添加。</div>';
}

function renderModelForm(p, open) {
  const pid = p.id;
  const editing = state.editingModel && state.editingModel.pid === pid ? state.editingModel : null;
  const model = editing ? (p.models || []).find(m => m.id === editing.mid) : null;
  const list = state.modelLists[pid] || [];
  const dlId = 'dl-' + pid;
  const isVision = model && model.type === 'vision';
  return `
    <div id="model-form-${pid}" style="${open ? '' : 'display:none'}" class="model-form">
      <datalist id="${dlId}">${list.map(m => `<option value="${esc(m)}"></option>`).join('')}</datalist>
      <div class="form-grid">
        <label>模型名
          <input id="mf-name-${pid}" list="${dlId}" placeholder="连接后从列表选择，也可手输" value="${esc(model ? model.name : '')}">
        </label>
        <label>类型（二选一）
          <span class="radio-group">
            <label class="radio-inline"><input type="radio" name="mf-type-${pid}" value="text" ${!isVision ? 'checked' : ''}> 文本</label>
            <label class="radio-inline"><input type="radio" name="mf-type-${pid}" value="vision" ${isVision ? 'checked' : ''}> 视觉</label>
          </span>
        </label>
        <label>temperature（可选，留空用全局）
          <input id="mf-temp-${pid}" type="number" step="0.1" min="0" max="1.5" placeholder="如 0.8" value="${model && model.temperature != null ? model.temperature : ''}">
        </label>
        <label>max_tokens（可选，留空按字数自动）
          <input id="mf-max-${pid}" type="number" min="1" placeholder="如 4096" value="${model && model.max_tokens ? model.max_tokens : ''}">
        </label>
        <label>上下文长度 context_length（可选，超长输入会自动截断）
          <input id="mf-ctx-${pid}" type="number" min="1024" step="1024" placeholder="如 32768 / 128000" value="${model && model.context_length ? model.context_length : ''}">
        </label>
      </div>
      <button class="btn primary" onclick="saveModel('${pid}')">${model ? '保存模型修改' : '保存模型'}</button>
      <button class="btn" onclick="closeModelForm('${pid}')">取消</button>
    </div>`;
}

async function connectProvider(pid) {
  const p = state.providers.find(x => x.id === pid);
  if (!p) return;
  const status = $('connect-status-' + pid);
  const btn = $('btn-connect-' + pid);
  if (!status || !btn) return;
  btn.disabled = true;
  status.textContent = '连接中…';
  status.style.color = 'var(--muted)';
  try {
    const r = await api('/api/providers/connect', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url: p.base_url, api_key: p.api_key, proxy: p.proxy }),
    });
    if (r.ok) {
      state.modelLists[pid] = r.models || [];
      status.textContent = `✓ 已缓存 ${r.models.length} 个模型`;
      status.style.color = 'var(--ok)';
      toast('连接成功，可添加模型', 'ok');
    } else {
      status.textContent = '✗ ' + (r.message || '连接失败');
      status.style.color = 'var(--danger)';
      toast(r.message || '连接失败', 'err');
    }
  } catch (e) {
    status.textContent = '✗ ' + e.message;
    status.style.color = 'var(--danger)';
    toast(e.message, 'err');
  } finally {
    btn.disabled = false;
  }
  renderProviders();
}

function toggleAddModel(pid) {
  if (state.addModelOpen === pid) {
    state.addModelOpen = null;
    state.editingModel = null;
  } else {
    state.addModelOpen = pid;
    state.editingModel = null;
  }
  renderProviders();
}

function editModel(pid, mid) {
  state.addModelOpen = pid;
  state.editingModel = { pid, mid };
  renderProviders();
}

function closeModelForm(pid) {
  state.addModelOpen = null;
  state.editingModel = null;
  renderProviders();
}

async function saveModel(pid) {
  const name = $('mf-name-' + pid).value.trim();
  if (!name) return toast('请填写模型名', 'err');
  const checked = document.querySelector(`input[name="mf-type-${pid}"]:checked`);
  const type = checked ? checked.value : 'text';
  const tempVal = $('mf-temp-' + pid).value.trim();
  const maxVal = $('mf-max-' + pid).value.trim();
  const ctxVal = $('mf-ctx-' + pid).value.trim();
  const body = {
    name,
    type,
    temperature: tempVal === '' ? null : parseFloat(tempVal),
    max_tokens: maxVal === '' ? null : parseInt(maxVal),
    context_length: ctxVal === '' ? null : parseInt(ctxVal),
  };
  try {
    if (state.editingModel && state.editingModel.pid === pid) {
      await api(`/api/providers/${pid}/models/${state.editingModel.mid}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      toast('模型已更新', 'ok');
    } else {
      await api(`/api/providers/${pid}/models`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      toast('模型已添加', 'ok');
    }
    state.addModelOpen = null;
    state.editingModel = null;
    await loadProviders();
  } catch (e) { toast(e.message, 'err'); }
}

async function deleteModel(pid, mid) {
  if (!confirm('确定删除该模型？')) return;
  await api(`/api/providers/${pid}/models/${mid}`, { method: 'DELETE' });
  await loadProviders();
  await loadSettings();
}

async function testModel(pid, mid) {
  toast('测试中…');
  try {
    const r = await api(`/api/providers/${pid}/models/${mid}/test`, { method: 'POST' });
    toast(r.message, r.ok ? 'ok' : 'err');
  } catch (e) { toast(e.message, 'err'); }
}

async function setModelRole(pid, mid, role) {
  const field = role === 'text' ? 'text_model_id' : 'vision_model_id';
  try {
    state.settings = await api('/api/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: mid }),
    });
    renderProviders();
    toast(role === 'text' ? '已设为当前文本生成模型' : '已设为当前视觉分析模型', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

async function saveProviderForm() {
  const body = {
    name: $('p-name').value.trim(),
    base_url: $('p-base').value.trim(),
    api_key: $('p-key').value.trim(),
    proxy: $('p-proxy').value === 'custom' ? ($('p-proxy-url').value.trim() || 'custom') : $('p-proxy').value,
  };
  if (!body.base_url) return toast('请填写 Base URL', 'err');
  try {
    if (state.editingProviderId) {
      await api('/api/providers/' + state.editingProviderId, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      toast('服务商已更新', 'ok');
    } else {
      await api('/api/providers', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      toast('服务商已添加', 'ok');
    }
    resetProviderForm();
    await loadProviders();
  } catch (e) { toast(e.message, 'err'); }
}

function startEditProvider(id) {
  const p = state.providers.find(x => x.id === id);
  if (!p) return;
  state.editingProviderId = id;
  $('p-name').value = p.name || '';
  $('p-base').value = p.base_url || '';
  $('p-key').value = p.api_key || '';
  $('p-proxy').value = (p.proxy && p.proxy !== 'direct' && p.proxy !== 'system') ? 'custom' : (p.proxy || 'direct');
  $('p-proxy-url').value = (p.proxy && p.proxy !== 'direct' && p.proxy !== 'system') ? p.proxy : '';
  $('provider-form-title').textContent = '编辑服务商：' + p.name;
  $('btn-provider-save').textContent = '保存修改';
  $('btn-provider-cancel').style.display = '';
  $('provider-form-title').scrollIntoView({ behavior: 'smooth' });
}

function cancelEditProvider() {
  resetProviderForm();
}

function resetProviderForm() {
  state.editingProviderId = null;
  ['p-name', 'p-base', 'p-key', 'p-proxy-url'].forEach(i => $(i).value = '');
  $('p-proxy').value = 'direct';
  $('provider-form-title').textContent = '添加服务商';
  $('btn-provider-save').textContent = '＋ 添加服务商';
  $('btn-provider-cancel').style.display = 'none';
}

async function deleteProvider(id) {
  if (!confirm('确定删除该服务商（含其下所有模型）？')) return;
  await api('/api/providers/' + id, { method: 'DELETE' });
  delete state.modelLists[id];
  await loadProviders();
  await loadSettings();
}

async function loadSettings() {
  state.settings = await api('/api/settings');
  renderSettings();
  renderProviders();
}

function renderSettings() {
  const s = state.settings;
  $('s-temperature').value = s.temperature ?? 0.8;
  $('s-ratio').value = s.token_ratio ?? 1.6;
  const gp = $('global-prompt');
  if (gp) gp.value = s.global_prompt ?? '';
}

// 保存全局前置提示词（静默保存到 settings.global_prompt）
async function saveGlobalPrompt() {
  const gp = $('global-prompt');
  if (!gp) return;
  try {
    state.settings = await api('/api/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ global_prompt: gp.value }),
    });
  } catch (e) { /* 静默失败，下次再保存 */ }
}

async function saveSettings() {
  const body = {
    temperature: parseFloat($('s-temperature').value) || 0.8,
    token_ratio: parseFloat($('s-ratio').value) || 1.6,
  };
  try {
    state.settings = await api('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    toast('生成参数已保存', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// ================= 角色库（全局角色管理） =================
let charDetailId = null;         // 详情页正在编辑的角色 id
let charBackHash = '#/characters'; // 详情/添加页「返回」目标
let charAssignNovelId = null;    // 从小说向导进入添加页时，新角色自动归入的小说 id
let resumeWizardStep = null;     // 从角色页返回小说编辑页时恢复的向导步骤
let newCharPhotoBlob = null;     // 添加页已裁剪、待上传的照片
let charBgNovelId = null;        // 从小说创作入口进入角色卡时，绑定的小说 id（用于展示并保存「本书背景设定」）

// 角色库小说筛选下拉数据（与角色列表分开，按需加载）
let characterNovelList = [];

// 加载小说列表（仅用于筛选下拉，不含角色）
async function loadCharacterNovels() {
  const d = await api('/api/characters/novels');
  characterNovelList = d.novels || [];
  renderCharacterNovelFilter();
}

// 按需加载角色：novelId 为空则加载最新 20 个，否则加载该小说角色
async function loadCharacters(novelId) {
  let url = '/api/characters';
  if (novelId) {
    url = '/api/characters?novel_id=' + encodeURIComponent(novelId);
  }
  const d = await api(url);
  state.characters = d.characters;
}

// 加载全部角色（小说向导/详情等需要跨小说匹配的场景）
async function loadAllCharacters() {
  const d = await api('/api/characters?limit=10000');
  state.characters = d.characters;
}

function currentNovelCharacters() {
  const ids = (state.novel && state.novel.character_ids) || [];
  return state.characters.filter(c => ids.includes(c.id));
}

// 角色封面（照片或占位图）
function charCoverHTML(c) {
  if (c.photo_path) {
    return `<img src="/${esc(c.photo_path)}" alt="${esc(c.name || '')}" loading="lazy">`;
  }
  return `<div class="char-cover-ph">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
    <span>未上传照片</span>
  </div>`;
}

// ============ 正文角色名高亮 + 角色卡弹窗 ============
// 获取当前小说关联的角色（含 id 与 name 映射）
function novelCharacters() {
  if (!state.novel) return [];
  const ids = state.novel.character_ids || [];
  return (state.characters || []).filter(c => ids.includes(c.id) && c.name);
}

// 将正文中的角色名高亮为可点击元素（点击打开角色卡）
function highlightCharacterNames(content) {
  const chars = novelCharacters();
  if (!chars.length) return esc(content);
  // 先转义，再按角色名长度从长到短替换，避免短名覆盖长名
  let html = esc(content);
  const sorted = chars.slice().sort((a, b) => (b.name || '').length - (a.name || '').length);
  for (const c of sorted) {
    const name = c.name.trim();
    if (!name) continue;
    // 转义角色名后作为正则字面量
    const escName = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(escName, 'g');
    html = html.replace(re, `<span class="char-mention" data-cid="${esc(c.id)}" onclick="openCharCard('${esc(c.id)}')">${name}</span>`);
  }
  return html;
}

// 打开角色卡弹窗
function openCharCard(id) {
  const c = (state.characters || []).find(x => x.id === id);
  if (!c) return;
  const overlay = $('char-card-overlay');
  if (!overlay) return;
  $('char-card-title').textContent = c.name || '未命名';
  $('char-card-photo').innerHTML = charCoverHTML(c);
  $('char-card-appearance').textContent = c.appearance || '暂无';
  $('char-card-personality').textContent = c.personality || '暂无';
  // 背景设定跟随小说：优先显示本书背景，无则回退角色库背景（兼容旧数据）
  const bookBg = (state.novel && state.novel.character_backgrounds && state.novel.character_backgrounds[id]) || '';
  $('char-card-background').textContent = bookBg || c.background || '（背景设定跟随各小说，请从小说创作进入角色卡填写本书背景）';
  $('char-card-notes').textContent = c.notes || '暂无';
  // 记录当前角色 id，供「编辑角色」使用
  overlay.dataset.cid = id;
  overlay.style.display = 'flex';
}

// 关闭角色卡弹窗
function closeCharCard() {
  const overlay = $('char-card-overlay');
  if (overlay) overlay.style.display = 'none';
}

// 从角色卡跳转到角色详情编辑页
function editCharFromCard() {
  const overlay = $('char-card-overlay');
  const id = overlay ? overlay.dataset.cid : null;
  if (!id) return;
  closeCharCard();
  if (state.novel) {
    // 从小说阅读/生成页进入：视为小说创作入口，展示并保存「本书背景设定」
    charBackHash = '#/novels/' + state.novel.id + '/edit';
    resumeWizardStep = 2;
    charBgNovelId = state.novel.id;
  } else {
    charBackHash = '#/characters';
    resumeWizardStep = null;
    charBgNovelId = null;
  }
  nav('#/characters/' + id);
}

// 角色库列表页：照片卡片网格（state.characters 已是按需加载后的结果）
function renderCharacterGrid() {
  const box = $('character-grid');
  if (!box) return;
  const hintEl = $('character-grid-hint');
  const sel = $('character-novel-filter');
  const novelId = sel ? sel.value : '';

  const chars = state.characters || [];

  if (hintEl) {
    if (novelId) {
      const novel = (characterNovelList || []).find(n => n.id === novelId);
      hintEl.textContent = novel ? `《${novel.title || '未命名'}》共 ${chars.length} 个角色。` : '该小说暂无角色。';
    } else {
      hintEl.textContent = `展示最新的 ${chars.length} 个角色。`;
    }
  }

  if (!chars.length) {
    const emptyMsg = novelId
      ? '该小说暂无角色，点击右上角「添加角色」创建，或在小说创作向导中添加。'
      : '暂无角色，点击右上角「添加角色」创建你的第一个角色。';
    box.innerHTML = `<div class="card meta" style="grid-column:1/-1">${emptyMsg}</div>`;
    return;
  }

  box.innerHTML = chars.map(c => `
    <div class="char-grid-card">
      <div class="char-grid-cover" onclick="openCharFromList('${c.id}')" title="点击查看/编辑角色">
        ${charCoverHTML(c)}
      </div>
      <div class="char-grid-body">
        <div class="char-grid-name" onclick="openCharFromList('${c.id}')">${esc(c.name || '未命名')}</div>
        <div class="meta">${esc((c.appearance || '').slice(0, 40)) || '暂无外貌描述'}</div>
      </div>
    </div>`).join('');
}

// 小说筛选下拉：填充选项（保留当前选中）
function renderCharacterNovelFilter() {
  const sel = $('character-novel-filter');
  if (!sel) return;
  const prev = sel.value;
  const novels = characterNovelList || [];
  sel.innerHTML = '<option value="">最新角色（默认）</option>' + novels.map(n =>
    `<option value="${esc(n.id)}">${esc(n.title || '未命名')}</option>`).join('');
  if (prev && novels.some(n => n.id === prev)) {
    sel.value = prev;
  }
}

// 筛选下拉变更：按需请求对应小说的角色
async function onCharacterNovelFilter() {
  const sel = $('character-novel-filter');
  const novelId = sel ? sel.value : '';
  await loadCharacters(novelId);
  renderCharacterGrid();
}

// 小说向导（步骤3）：当前小说角色的照片卡片网格
function renderCharacters() {
  const box = $('character-list');
  if (!box) return;
  const chars = currentNovelCharacters();
  box.innerHTML = chars.length
    ? chars.map(c => `
      <div class="char-grid-card">
        <div class="char-grid-cover" onclick="openCharFromWizard('${c.id}')" title="点击查看/编辑角色">
          ${charCoverHTML(c)}
        </div>
        <div class="char-grid-body">
          <div class="row">
            <span class="char-grid-name" onclick="openCharFromWizard('${c.id}')">${esc(c.name || '未命名')}</span>
            <span class="spacer"></span>
            <button class="btn danger" onclick="removeCharacterFromNovel('${c.id}')">移除</button>
          </div>
        </div>
      </div>`).join('')
    : '<div class="card meta" style="grid-column:1/-1">本小说还没有角色，点击「添加角色」新增。</div>';
}

// —— 角色库列表页入口：点卡片进详情 ——
function openCharFromList(id) {
  charBackHash = '#/characters';
  resumeWizardStep = null;
  charBgNovelId = null;          // 角色库入口：不展示「本书背景设定」
  nav('#/characters/' + id);
}

// —— 小说向导入口：点卡片进详情，返回时回到向导步骤3 ——
async function openCharFromWizard(id) {
  charBackHash = state.novel ? ('#/novels/' + state.novel.id + '/edit') : '#/characters';
  resumeWizardStep = 2;
  charBgNovelId = state.novel ? state.novel.id : null;  // 小说入口：展示并保存「本书背景设定」
  await persistNovelCharsSilently();
  nav('#/characters/' + id);
}

// 返回（详情/添加页共用）
function goBackFromCharacter() {
  nav(charBackHash || '#/characters');
}

// 添加角色（角色库入口：新角色自动归入当前筛选的小说）
function goAddCharacterFromList() {
  charBackHash = '#/characters';
  const sel = $('character-novel-filter');
  charAssignNovelId = sel && sel.value ? sel.value : null;
  resumeWizardStep = null;
  charBgNovelId = null;
  nav('#/characters/new');
}

// 添加角色（小说向导入口：新角色自动归入本小说）
async function goAddCharacterFromWizard() {
  if (!state.novel) return toast('请先完成基本信息', 'err');
  charBackHash = '#/novels/' + state.novel.id + '/edit';
  charAssignNovelId = state.novel.id;
  resumeWizardStep = 2;
  charBgNovelId = state.novel.id;  // 新建后进入详情页同样展示「本书背景设定」
  await persistNovelCharsSilently();
  nav('#/characters/new');
}

// —— 从角色库选择已有角色（一个角色可属于多部小说） ——
async function toggleCharacterPicker() {
  const panel = $('character-picker');
  if (!panel) return;
  const isHidden = panel.style.display === 'none';
  if (isHidden) {
    await loadAllCharacters();  // 确保拿到全量角色
    renderCharacterPicker();
    panel.style.display = 'block';
  } else {
    panel.style.display = 'none';
  }
}

function renderCharacterPicker() {
  const box = $('character-picker-list');
  if (!box) return;
  const chars = state.characters || [];
  const currentIds = (state.novel && state.novel.character_ids) || [];
  if (!chars.length) {
    box.innerHTML = '<div class="meta">角色库为空，请先「新建角色」。</div>';
    return;
  }
  box.innerHTML = chars.map(c => {
    const checked = currentIds.includes(c.id);
    return `
    <label class="character-picker-item">
      <input type="checkbox" ${checked ? 'checked' : ''} onchange="toggleNovelCharacter('${c.id}', this.checked)">
      ${charCoverHTML(c)}
      <span class="character-picker-name">${esc(c.name || '未命名')}</span>
    </label>`;
  }).join('');
}

// 勾选/取消勾选：把角色加入或移出本小说
async function toggleNovelCharacter(id, checked) {
  if (!state.novel) return;
  let ids = (state.novel.character_ids || []).slice();
  if (checked) {
    if (!ids.includes(id)) ids.push(id);
  } else {
    ids = ids.filter(x => x !== id);
  }
  try {
    const nd = await api('/api/novels/' + state.novel.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_ids: ids }),
    });
    state.novel = nd.novel;
    renderCharacters();       // 刷新本小说角色网格
    renderCharacterPicker();  // 刷新选择面板勾选状态
  } catch (e) { toast(e.message, 'err'); }
}

// 静默保存小说当前角色与关系（避免离开向导时丢失手动输入）
async function persistNovelCharsSilently() {
  if (!state.novel) return;
  try {
    await api('/api/novels/' + state.novel.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        character_ids: state.novel.character_ids || [],
        relationships: state.relations.filter(r => r.char1_id && r.char2_id && r.char1_id !== r.char2_id),
      }),
    });
  } catch (e) { /* 忽略：如已完结小说等，不阻断跳转 */ }
}

// 添加页：重置表单
function resetCharacterNewForm() {
  $('c-new-name').value = '';
  $('c-new-appearance').value = '';
  $('c-new-personality').value = '';
  $('c-new-notes').value = '';
  newCharPhotoBlob = null;
  renderNewPhotoPreview();
  const title = $('character-new-title');
  if (title) title.textContent = charAssignNovelId ? '添加角色（将归入当前小说）' : '添加角色';
}

// 保存新角色
async function saveNewCharacter() {
  const name = $('c-new-name').value.trim();
  if (!name) return toast('请填写角色姓名', 'err');
  try {
    const d = await api('/api/characters', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        appearance: $('c-new-appearance').value.trim(),
        personality: $('c-new-personality').value.trim(),
        notes: $('c-new-notes').value.trim(),
      }),
    });
    const cid = d.character.id;
    if (newCharPhotoBlob) {
      showLoading('正在上传照片…', '');
      try { await uploadPhoto(cid, newCharPhotoBlob); newCharPhotoBlob = null; }
      finally { hideLoading(); }
    }
    // 自动归入小说（若从向导进入）
    if (charAssignNovelId) {
      try {
        const nd = await api('/api/novels/' + charAssignNovelId);
        const ids = nd.novel.character_ids || [];
        if (!ids.includes(cid)) ids.push(cid);
        const upd = await api('/api/novels/' + charAssignNovelId, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ character_ids: ids }),
        });
        if (state.novel && state.novel.id === charAssignNovelId) state.novel = upd.novel;
      } catch (e) { /* 忽略 */ }
      charAssignNovelId = null;
    }
    await loadAllCharacters();
    toast('角色已添加', 'ok');
    // 进入详情页继续完善
    nav('#/characters/' + cid);
  } catch (e) { toast(e.message, 'err'); }
}

// 详情页：加载角色
async function openCharacterDetail(id) {
  if (!state.characters.length) { await loadAllCharacters(); }
  const c = state.characters.find(x => x.id === id);
  if (!c) { toast('角色不存在', 'err'); nav('#/characters'); return; }
  charDetailId = id;
  const title = $('character-detail-title');
  if (title) title.textContent = '角色详情 · ' + (c.name || '未命名');
  const photo = $('c-detail-photo');
  photo.innerHTML = c.photo_path
    ? `<img src="/${esc(c.photo_path)}" alt="${esc(c.name || '')}">`
    : `<div class="char-cover-ph">
         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
         <span>未上传照片</span>
       </div>`;
  $('c-detail-name').value = c.name || '';
  $('c-detail-appearance').value = c.appearance || '';
  $('c-detail-personality').value = c.personality || '';
  $('c-detail-notes').value = c.notes || '';
  // 背景设定跟随小说：仅从小说创作入口进入时展示「本书背景设定」输入框
  const bgWrap = $('c-detail-bg-wrap');
  if (bgWrap) bgWrap.style.display = charBgNovelId ? '' : 'none';
  const bgEl = $('c-detail-background');
  if (bgEl) {
    bgEl.value = '';
    if (charBgNovelId) {
      try {
        const nd = await api('/api/novels/' + charBgNovelId);
        bgEl.value = (nd.novel.character_backgrounds || {})[id] || '';
        if (state.novel && state.novel.id === charBgNovelId) state.novel = nd.novel;
      } catch (e) { bgEl.value = ''; }
    }
  }
  if (!charBackHash) charBackHash = '#/characters';
}

// 详情页：保存
async function saveCharacterDetail() {
  const id = charDetailId;
  if (!id) return;
  const name = $('c-detail-name').value.trim();
  if (!name) return toast('角色姓名不能为空', 'err');
  try {
    await api('/api/characters/' + id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        appearance: $('c-detail-appearance').value.trim(),
        personality: $('c-detail-personality').value.trim(),
        notes: $('c-detail-notes').value.trim(),
      }),
    });
    // 若从小说创作入口进入，同时把「本书背景设定」保存到该小说的 character_backgrounds
    if (charBgNovelId) {
      const bgEl = $('c-detail-background');
      const bg = bgEl ? bgEl.value.trim() : '';
      const nd = await api('/api/novels/' + charBgNovelId);
      const bgs = Object.assign({}, nd.novel.character_backgrounds || {});
      if (bg) bgs[id] = bg; else delete bgs[id];
      const upd = await api('/api/novels/' + charBgNovelId, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_backgrounds: bgs }),
      });
      if (state.novel && state.novel.id === charBgNovelId) state.novel = upd.novel;
    }
    await loadAllCharacters();
    const title = $('character-detail-title');
    if (title) title.textContent = '角色详情 · ' + name;
    toast('角色已保存', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// 详情页：更换照片（先裁剪，再上传，不自动分析）
function uploadDetailPhoto() {
  const id = charDetailId;
  if (!id) return;
  const input = document.createElement('input');
  input.type = 'file'; input.accept = 'image/*';
  input.onchange = () => {
    if (!input.files.length) return;
    cropFromFile(input.files[0], async (blob) => {
      showLoading('正在上传照片…', '');
      try {
        await uploadPhoto(id, blob);
        toast('照片已更新', 'ok');
        await loadAllCharacters();
        openCharacterDetail(id);
      } catch (e) { toast(e.message, 'err'); }
      finally { hideLoading(); }
    });
  };
  input.click();
}

// 详情页：手动触发 AI 分析当前照片（外貌/穿着/性格），填充表单供确认
async function analyzeDetailPhoto() {
  const id = charDetailId;
  if (!id) return;
  const c = state.characters.find(x => x.id === id);
  if (!c || !c.photo_path) return toast('请先上传照片', 'err');
  const appEl = $('c-detail-appearance'), perEl = $('c-detail-personality');
  if ((appEl.value.trim() || perEl.value.trim()) && !confirm('外貌/性格已有内容，确定用 AI 分析结果覆盖吗？')) return;
  showLoading('正在分析人物照片…', 'AI 正在识别外貌、穿着与性格特征，请稍候');
  try {
    const blob = await fetch('/' + c.photo_path).then(r => {
      if (!r.ok) throw new Error('照片读取失败');
      return r.blob();
    });
    const r = await analyzePhotoBlob(blob);
    appEl.value = r.appearance || '';
    perEl.value = r.personality || '';
    toast('分析完成，请确认后点击「保存」', 'ok');
  } catch (e) { toast(e.message, 'err'); }
  finally { hideLoading(); }
}

// 详情页：删除角色
async function deleteCharacterDetail() {
  const id = charDetailId;
  if (!id) return;
  if (!confirm('确定删除该角色？此操作不可恢复。')) return;
  try {
    await api('/api/characters/' + id, { method: 'DELETE' });
    await loadAllCharacters();
    toast('角色已删除', 'ok');
    goBackFromCharacter();
  } catch (e) { toast(e.message, 'err'); }
}

// 小说向导：仅从本小说移除角色（不删除角色本身）
async function removeCharacterFromNovel(id) {
  if (!state.novel) return;
  if (!confirm('确定将该角色从本小说移除？（角色本身不会被删除）')) return;
  try {
    const ids = (state.novel.character_ids || []).filter(x => x !== id);
    const nd = await api('/api/novels/' + state.novel.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_ids: ids }),
    });
    state.novel = nd.novel;
    await loadAllCharacters();
    renderCharacters();
    renderRelations();
    loadNovels();
    toast('已从本小说移除', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// 上传照片到指定角色（仅保存，不分析）
async function uploadPhoto(id, file) {
  const fd = new FormData();
  fd.append('file', file, file.name || 'photo.jpg');
  return await api(`/api/characters/${id}/photo`, { method: 'POST', body: fd });
}

// 调用 AI 分析接口，返回 {appearance, personality}
async function analyzePhotoBlob(blob) {
  const fd = new FormData();
  fd.append('file', blob, blob.name || 'photo.jpg');
  return await api('/api/analyze-character-photo', { method: 'POST', body: fd });
}

// ================= 添加页照片 =================
// 选择照片后打开裁剪器
function onNewPhotoPicked(input) {
  if (!input.files.length) return;
  cropFromFile(input.files[0], (blob) => {
    newCharPhotoBlob = blob;
    renderNewPhotoPreview();
    toast('照片已就绪，可点击「AI 分析」识别外貌与性格', 'ok');
  });
  input.value = '';
}

// 渲染添加页照片预览
function renderNewPhotoPreview() {
  const wrap = $('c-new-photo-preview');
  const img = $('c-new-photo-img');
  if (!wrap || !img) return;
  // 释放上一个预览的 blob URL，避免重复选择时泄漏内存
  if (img.src && img.src.indexOf('blob:') === 0) URL.revokeObjectURL(img.src);
  if (newCharPhotoBlob) {
    img.src = URL.createObjectURL(newCharPhotoBlob);
    wrap.style.display = '';
  } else {
    img.removeAttribute('src');
    wrap.style.display = 'none';
  }
}

function rePickNewPhoto() {
  const input = $('c-new-photo');
  if (input) input.click();
}

// 添加页：手动触发 AI 分析已选照片
async function analyzeNewPhoto() {
  if (!newCharPhotoBlob) return toast('请先选择并裁切照片', 'err');
  const appEl = $('c-new-appearance'), perEl = $('c-new-personality');
  if ((appEl.value.trim() || perEl.value.trim()) && !confirm('外貌/性格已有内容，确定用 AI 分析结果覆盖吗？')) return;
  showLoading('正在分析人物照片…', 'AI 正在识别外貌、穿着与性格特征，请稍候');
  try {
    const r = await analyzePhotoBlob(newCharPhotoBlob);
    appEl.value = r.appearance || '';
    perEl.value = r.personality || '';
    toast('分析完成，请检查并确认后保存', 'ok');
  } catch (e) { toast(e.message, 'err'); }
  finally { hideLoading(); }
}

// ================= 照片裁剪器 =================
let cropCtx = null;  // { img, dw, dh, ox, oy, box:{x,y,w,h}, mode, startX, startY, startBox, onDone }

// 从文件读取图片并打开裁剪模态框（用 dataURL，避免 blob URL 提前 revoke 导致图片加载失败）
function cropFromFile(file, onDone) {
  const reader = new FileReader();
  reader.onload = () => {
    const img = new Image();
    img.onload = () => openCropModal(img, reader.result, onDone);
    img.onerror = () => toast('无法读取该图片', 'err');
    img.src = reader.result;
  };
  reader.onerror = () => toast('无法读取该图片', 'err');
  reader.readAsDataURL(file);
}

// 打开裁剪模态框：计算显示尺寸、居中、默认全图选框
function openCropModal(img, src, onDone) {
  const stage = $('crop-stage');
  const imageEl = $('crop-image');
  const maxW = Math.min(560, (window.innerWidth || 800) - 40);
  const maxH = Math.min(420, (window.innerHeight || 700) - 220);
  const ratio = Math.min(maxW / img.naturalWidth, maxH / img.naturalHeight);
  const dw = Math.max(1, Math.round(img.naturalWidth * ratio));
  const dh = Math.max(1, Math.round(img.naturalHeight * ratio));
  imageEl.style.width = dw + 'px';
  imageEl.style.height = dh + 'px';
  imageEl.onload = () => {
    const ox = Math.round((stage.clientWidth - dw) / 2);
    const oy = Math.round((stage.clientHeight - dh) / 2);
    imageEl.style.left = ox + 'px';
    imageEl.style.top = oy + 'px';
    cropCtx = { img, dw, dh, ox, oy, box: { x: ox, y: oy, w: dw, h: dh }, mode: null, startX: 0, startY: 0, startBox: null, onDone };
    renderCropBox();
  };
  $('crop-overlay').classList.add('show');
  imageEl.src = src;
}

function renderCropBox() {
  if (!cropCtx) return;
  const box = $('crop-box');
  const b = cropCtx.box;
  box.style.left = b.x + 'px';
  box.style.top = b.y + 'px';
  box.style.width = b.w + 'px';
  box.style.height = b.h + 'px';
}

function closeCropModal() {
  const ov = $('crop-overlay');
  if (ov) ov.classList.remove('show');
  cropCtx = null;
}
function cancelCrop() { closeCropModal(); }

// 指针按下：开始移动或缩放选框
function cropPointerDown(e, mode) {
  if (!cropCtx) return;
  e.preventDefault();
  e.stopPropagation();
  cropCtx.mode = mode || 'move';
  cropCtx.startX = e.clientX;
  cropCtx.startY = e.clientY;
  cropCtx.startBox = { x: cropCtx.box.x, y: cropCtx.box.y, w: cropCtx.box.w, h: cropCtx.box.h };
  window.addEventListener('pointermove', cropPointerMove);
  window.addEventListener('pointerup', cropPointerUp);
}

function cropPointerMove(e) {
  const ctx = cropCtx;
  if (!ctx || !ctx.mode) return;
  const dx = e.clientX - ctx.startX;
  const dy = e.clientY - ctx.startY;
  const sb = ctx.startBox;
  const b = ctx.box;
  const MIN = 30;
  const imgL = ctx.ox, imgT = ctx.oy, imgR = ctx.ox + ctx.dw, imgB = ctx.oy + ctx.dh;
  if (ctx.mode === 'move') {
    b.x = Math.max(imgL, Math.min(sb.x + dx, imgR - sb.w));
    b.y = Math.max(imgT, Math.min(sb.y + dy, imgB - sb.h));
  } else {
    if (ctx.mode.indexOf('w') >= 0) {
      b.x = Math.max(imgL, Math.min(sb.x + dx, sb.x + sb.w - MIN));
      b.w = sb.x + sb.w - b.x;
    }
    if (ctx.mode.indexOf('e') >= 0) {
      b.w = Math.min(imgR - sb.x, Math.max(MIN, sb.w + dx));
    }
    if (ctx.mode.indexOf('n') >= 0) {
      b.y = Math.max(imgT, Math.min(sb.y + dy, sb.y + sb.h - MIN));
      b.h = sb.y + sb.h - b.y;
    }
    if (ctx.mode.indexOf('s') >= 0) {
      b.h = Math.min(imgB - sb.y, Math.max(MIN, sb.h + dy));
    }
  }
  renderCropBox();
}

function cropPointerUp() {
  if (cropCtx) cropCtx.mode = null;
  window.removeEventListener('pointermove', cropPointerMove);
  window.removeEventListener('pointerup', cropPointerUp);
}

// 确认裁切：canvas 截取选框区域，输出 jpeg blob
function applyCrop() {
  const ctx = cropCtx;
  if (!ctx) return;
  const b = ctx.box;
  const sx = (b.x - ctx.ox) / ctx.dw * ctx.img.naturalWidth;
  const sy = (b.y - ctx.oy) / ctx.dh * ctx.img.naturalHeight;
  const sw = b.w / ctx.dw * ctx.img.naturalWidth;
  const sh = b.h / ctx.dh * ctx.img.naturalHeight;
  const cw = Math.max(1, Math.round(sw));
  const ch = Math.max(1, Math.round(sh));
  const canvas = document.createElement('canvas');
  canvas.width = cw; canvas.height = ch;
  canvas.getContext('2d').drawImage(ctx.img, sx, sy, sw, sh, 0, 0, cw, ch);
  const onDone = ctx.onDone;
  closeCropModal();
  canvas.toBlob((blob) => {
    if (blob && onDone) onDone(blob);
    else if (!blob) toast('裁切失败，请重试', 'err');
  }, 'image/jpeg', 0.92);
}

// ================= 小说创作（向导） =================
async function loadNovels() {
  const d = await api('/api/novels');
  state.novels = d.novels;
  novelPage = 1;
  renderNovelFilterOptions();
  renderModeFilterOptions();
  renderNovels();
}

// 填充模型筛选下拉框（列出所有文本模型 + 全局默认）
function renderNovelFilterOptions() {
  const sel = $('novel-model-filter');
  if (!sel) return;
  const cur = sel.value;
  const opts = ['<option value="">全部模型</option>'];
  opts.push('<option value="__global__">全局默认</option>');
  const seen = new Set();
  (state.providers || []).forEach(p => {
    (p.models || []).forEach(m => {
      if (m.type !== 'text' || seen.has(m.id)) return;
      seen.add(m.id);
      opts.push(`<option value="${m.id}">${esc(p.name)} / ${esc(m.name)}</option>`);
    });
  });
  sel.innerHTML = opts.join('');
  sel.value = cur || '';
}

// 填充创作模式筛选下拉框（由 NOVEL_MODES 驱动，与列表显示名保持一致）
function renderModeFilterOptions() {
  const sel = $('novel-mode-filter');
  if (!sel) return;
  const cur = sel.value;
  const opts = ['<option value="">全部</option>'];
  NOVEL_MODES.forEach(m => opts.push(`<option value="${m.value}">${m.label}</option>`));
  sel.innerHTML = opts.join('');
  sel.value = cur || '';
}

// 状态显示名
function statusLabel(s) {
  return { 'draft': '草稿', 'outlined': '已生成大纲', 'generating': '生成中', 'done': '已完成', 'finished': '已完结' }[s] || s;
}

// 小说列表分页状态
let novelPage = 1;
const NOVEL_PAGE_SIZE = 5;

// 创作模式定义（单一数据源）：新增模式时在此追加，列表筛选框与显示名自动保持一致
const NOVEL_MODES = [
  { value: 'outline', label: '大纲' },
  { value: 'improv', label: '即兴' },
  { value: 'dialog', label: '对话' },
  { value: 'rewrite', label: '改写' },
  { value: 'continue', label: '续写' },
];

// 创作模式显示名
function modeLabel(m) {
  const item = NOVEL_MODES.find(x => x.value === m);
  return item ? item.label : '大纲';
}

// 渲染一个小说卡片（供列表与垃圾箱复用）
function novelCardHTML(n) {
  const isImprov = n.mode === 'improv';
  const isDialog = n.mode === 'dialog';
  const isRewrite = n.mode === 'rewrite';
  const isContinue = n.mode === 'continue';
  const hasOutline = n.chapters && n.chapters.length;
  const genCount = (n.chapters || []).filter(c => c.content).length;
  const isFinished = n.status === 'finished';
  const created = n.created_at ? new Date(n.created_at * 1000).toLocaleString('zh-CN', { hour12: false }) : '';
  let primaryBtn;
  if (isDialog) {
    primaryBtn = `<button class="btn primary" onclick="nav('#/novels/${n.id}/dialog')">进入对话</button>`;
  } else if (isImprov) {
    primaryBtn = `<button class="btn primary" onclick="nav('#/novels/${n.id}/improv')">进入写作（${genCount} 章）</button>`;
  } else if (isRewrite) {
    primaryBtn = `<button class="btn primary" onclick="nav('#/novels/${n.id}/rewrite')">进入改写（${hasOutline ? n.chapters.length : 0} 段）</button>`;
  } else if (isContinue) {
    primaryBtn = `<button class="btn primary" onclick="nav('#/novels/${n.id}/continue')">进入续写（${genCount} 章）</button>`;
  } else if (hasOutline) {
    primaryBtn = `<button class="btn primary" onclick="nav('#/novels/${n.id}/generate')">进入生成（${genCount}/${n.chapter_count}）</button>`;
  } else {
    primaryBtn = `<button class="btn primary" onclick="nav('#/novels/${n.id}/edit')">继续创作</button>`;
  }
  const modeBadge = `<span class="badge">${modeLabel(n.mode)}</span>`;
  if (isFinished) {
    return `
    <div class="card novel-card">
      <div class="row">
        <span class="title">${esc(n.title)}</span>
        <span class="badge">${esc(statusLabel(n.status))}</span>
        ${modeBadge}
        <span class="spacer"></span>
        ${created ? `<span class="meta">${esc(created)}</span>` : ''}
      </div>
      <div class="meta">${esc(n.genre || '未设题材')} · ${n.chapter_count}章 · ${n.words_per_chapter}字/章 · 角色${(n.character_ids || []).length} · 已生成 ${genCount} 章 · 模型${n.text_model_id ? esc(modelLabel(n.text_model_id)) : '（全局）'}</div>
      <div class="row" style="margin-top:10px">
        ${genCount > 0 ? `<button class="btn" onclick="nav('#/novels/${n.id}/read')">阅读</button>` : ''}
        <button class="btn" onclick="exportNovel('${n.id}', 'md')">导出 MD</button>
        <button class="btn" onclick="reopenNovel('${n.id}')">重开</button>
        <span class="spacer"></span>
        <button class="btn danger" onclick="deleteNovel('${n.id}')">删除</button>
      </div>
    </div>`;
  }
  return `
  <div class="card novel-card">
    <div class="row">
      <span class="title">${esc(n.title)}</span>
      <span class="badge">${esc(statusLabel(n.status))}</span>
      ${modeBadge}
      <span class="spacer"></span>
      ${created ? `<span class="meta">${esc(created)}</span>` : ''}
    </div>
    <div class="meta">${esc(n.genre || '未设题材')} · ${n.chapter_count}章 · ${n.words_per_chapter}字/章 · 角色${(n.character_ids || []).length} · 已生成 ${genCount} 章 · 模型${n.text_model_id ? esc(modelLabel(n.text_model_id)) : '（全局）'}</div>
    <div class="row" style="margin-top:10px">
      ${primaryBtn}
      ${genCount > 0 ? `<button class="btn" onclick="nav('#/novels/${n.id}/read')">阅读</button>` : ''}
      <button class="btn" onclick="nav('#/novels/${n.id}/edit')">编辑设定</button>
      <button class="btn" onclick="exportNovel('${n.id}', 'md')">导出 MD</button>
      <button class="btn" onclick="finishNovel('${n.id}')">完结</button>
      <span class="spacer"></span>
      <button class="btn danger" onclick="deleteNovel('${n.id}')">删除</button>
    </div>
  </div>`;
}

// 渲染分页控件
function renderPagination(total, current, onPage) {
  const box = $('novel-pagination');
  if (!box) return;
  const totalPages = Math.max(1, Math.ceil(total / NOVEL_PAGE_SIZE));
  if (totalPages <= 1) { box.innerHTML = ''; return; }
  let html = '';
  for (let i = 1; i <= totalPages; i++) {
    html += `<button class="page-btn ${i === current ? 'active' : ''}" onclick="${onPage}(${i})">${i}</button>`;
  }
  box.innerHTML = html;
}

function renderNovels() {
  const box = $('novel-list');
  const sortSel = $('novel-sort');
  const modelSel = $('novel-model-filter');
  const statusSel = $('novel-status-filter');
  const modeSel = $('novel-mode-filter');
  const sort = sortSel ? sortSel.value : 'created_desc';
  const modelFilter = modelSel ? modelSel.value : '';
  const statusFilter = statusSel ? statusSel.value : '';
  const modeFilter = modeSel ? modeSel.value : '';

  // 筛选
  let list = (state.novels || []).filter(n => {
    if (statusFilter && n.status !== statusFilter) return false;
    if (modeFilter && n.mode !== modeFilter) return false;
    if (modelFilter) {
      if (modelFilter === '__global__') {
        if (n.text_model_id) return false;  // 只保留用全局默认的
      } else if (n.text_model_id !== modelFilter) {
        return false;
      }
    }
    return true;
  });

  // 排序
  if (sort === 'created_desc') {
    list = list.slice().sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  } else if (sort === 'created_asc') {
    list = list.slice().sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
  } else if (sort === 'title') {
    list = list.slice().sort((a, b) => (a.title || '').localeCompare(b.title || '', 'zh'));
  }

  // 数量提示
  const cnt = $('novel-count');
  if (cnt) cnt.textContent = `共 ${list.length} 本`;

  if (!list.length) {
    box.innerHTML = '<div class="card meta">没有符合条件的小说。</div>';
    const pg = $('novel-pagination'); if (pg) pg.innerHTML = '';
    return;
  }

  // 分页：夹取当前页
  const totalPages = Math.ceil(list.length / NOVEL_PAGE_SIZE);
  if (novelPage > totalPages) novelPage = totalPages;
  if (novelPage < 1) novelPage = 1;
  const start = (novelPage - 1) * NOVEL_PAGE_SIZE;
  const pageList = list.slice(start, start + NOVEL_PAGE_SIZE);

  box.innerHTML = pageList.map(n => novelCardHTML(n)).join('');
  renderPagination(list.length, novelPage, 'gotoNovelPage');
}

function gotoNovelPage(p) {
  novelPage = p;
  renderNovels();
}

// ============ 小说阅读（已完结小说列表） ============
let readerBackHash = null;  // 阅读页「返回」目标

// 从阅读库进入阅读模式
function openFromLibrary(id) {
  readerBackHash = '#/library';
  nav('#/novels/' + id + '/read');
}

// 已完结小说卡片
function libraryCardHTML(n) {
  const genCount = (n.chapters || []).filter(c => c.content).length;
  const created = n.created_at ? new Date(n.created_at * 1000).toLocaleString('zh-CN', { hour12: false }) : '';
  const summary = (n.summary || '').trim();
  return `
  <div class="card novel-card library-card">
    <div class="row">
      <span class="title">${esc(n.title)}</span>
      <span class="badge">已完结</span>
      <span class="badge">${modeLabel(n.mode)}</span>
      <span class="spacer"></span>
      ${created ? `<span class="meta">${esc(created)}</span>` : ''}
    </div>
    <div class="meta">${esc(n.genre || '未设题材')} · ${genCount} 章 · ${(n.words_per_chapter || 0)}字/章 · 角色 ${(n.character_ids || []).length}</div>
    ${summary ? `<div class="library-summary">${esc(summary.slice(0, 120))}${summary.length > 120 ? '…' : ''}</div>` : ''}
    <div class="row" style="margin-top:10px">
      <button class="btn primary" onclick="openFromLibrary('${n.id}')">开始阅读</button>
      <button class="btn" onclick="exportNovel('${n.id}', 'md')">导出 MD</button>
      <button class="btn" onclick="exportNovel('${n.id}', 'epub')">导出 EPUB</button>
    </div>
  </div>`;
}

async function loadLibrary() {
  try {
    const d = await api('/api/novels');
    state.novels = d.novels || [];
  } catch (e) { toast(e.message, 'err'); }
  renderLibrary();
}

function renderLibrary() {
  const box = $('library-list');
  if (!box) return;
  const finished = (state.novels || []).filter(n => n.status === 'finished')
    .slice().sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  if (!finished.length) {
    box.innerHTML = '<div class="card meta">暂无已完结的小说。在「小说创作」中完成一部小说后，它会出现在这里。</div>';
    return;
  }
  box.innerHTML = finished.map(n => libraryCardHTML(n)).join('');
}

// ============ 垃圾箱 ============
async function loadTrash() {
  const box = $('trash-list');
  try {
    const d = await api('/api/novels/trash');
    const list = d.novels || [];
    if (!list.length) {
      box.innerHTML = '<div class="card meta">垃圾箱是空的。</div>';
      return;
    }
    box.innerHTML = list.map(n => {
      const isImprov = n.mode === 'improv';
      const deletedAt = n.deleted_at ? new Date(n.deleted_at * 1000).toLocaleString('zh-CN', { hour12: false }) : '';
      return `
      <div class="card novel-card">
        <div class="row">
          <span class="title">${esc(n.title)}</span>
          <span class="badge">${isImprov ? '即兴' : '大纲'}</span>
          <span class="spacer"></span>
          ${deletedAt ? `<span class="meta">删除于 ${esc(deletedAt)}</span>` : ''}
        </div>
        <div class="meta">${esc(n.genre || '未设题材')} · ${n.chapter_count}章 · 角色${(n.character_ids || []).length}</div>
        <div class="row" style="margin-top:10px">
          <button class="btn" onclick="restoreNovel('${n.id}')">恢复</button>
          <span class="spacer"></span>
          <button class="btn danger" onclick="destroyNovel('${n.id}')">彻底删除</button>
        </div>
      </div>`;
    }).join('');
  } catch (e) { toast(e.message, 'err'); }
}

function showTrash() {
  nav('#/trash');
}

async function restoreNovel(id) {
  try {
    await api(`/api/novels/${id}/restore`, { method: 'POST' });
    toast('已恢复', 'ok');
    loadTrash();
  } catch (e) { toast(e.message, 'err'); }
}

async function destroyNovel(id) {
  if (!confirm('彻底删除后不可恢复，确定删除该小说？')) return;
  try {
    await api(`/api/novels/${id}/destroy`, { method: 'DELETE' });
    toast('已彻底删除', 'ok');
    loadTrash();
  } catch (e) { toast(e.message, 'err'); }
}

async function deleteNovel(id) {
  if (!confirm('确定删除该小说？删除后将移入垃圾箱，可随时恢复。')) return;
  try {
    await api('/api/novels/' + id, { method: 'DELETE' });
    toast('已移入垃圾箱', 'ok');
    loadNovels();
  } catch (e) { toast(e.message, 'err'); }
}

async function finishNovel(id) {
  if (!confirm('确定完结该小说？完结后不可再修改，如需修改可「重开」。')) return;
  try {
    await api(`/api/novels/${id}/finish`, { method: 'POST' });
    toast('已完结', 'ok');
    loadNovels();
  } catch (e) { toast(e.message, 'err'); }
}

async function reopenNovel(id) {
  if (!confirm('确定重开该小说？重开后恢复可编辑状态。')) return;
  try {
    await api(`/api/novels/${id}/reopen`, { method: 'POST' });
    toast('已重开', 'ok');
    loadNovels();
  } catch (e) { toast(e.message, 'err'); }
}

function renderNovelModelSelect() {
  const sel = $('n-model');
  const opts = [];
  const global = state.settings.text_model_id || '';
  const globalName = global ? modelLabel(global) : '';
  opts.push(`<option value="">跟随全局默认${globalName ? '（' + globalName + '）' : ''}</option>`);
  (state.providers || []).forEach(p => {
    (p.models || []).forEach(m => {
      if (m.type !== 'text') return;
      opts.push(`<option value="${m.id}">${esc(p.name)} / ${esc(m.name)}</option>`);
    });
  });
  sel.innerHTML = opts.join('');
  sel.value = state.novel && state.novel.text_model_id ? state.novel.text_model_id : '';
}

function modelLabel(mid) {
  for (const p of (state.providers || [])) {
    const m = (p.models || []).find(x => x.id === mid);
    if (m) return `${p.name} / ${m.name}`;
  }
  return '';
}

function newNovel() {
  state.novel = null;
  state.relations = [];
  state.novelProfile = null;
  state.novelProfileSource = '';
  currentNovelId = null;
  ['n-title', 'n-genre', 'n-style', 'n-reference', 'n-background', 'n-worldbuilding', 'n-source', 'n-task-instruction'].forEach(i => $(i).value = '');
  const srcInfo = $('n-source-info'); if (srcInfo) srcInfo.textContent = '';
  $('n-chapters').value = 10;
  $('n-words').value = 2000;
  $('n-mode').value = 'outline';
  onModeChange();
  renderNovelModelSelect();
  renderSettings();
  renderGenreSelect();
  renderNovelWorldbookSelect();
  state.wizardStep = 1;
  $('editor-title').textContent = '新建小说';
  renderSteps();
  window.scrollTo({ top: 0 });
}

// 创作模式切换：即兴交互式、对话、改写、续写模式不需要预设章节数
function onModeChange() {
  const mode = $('n-mode') ? $('n-mode').value : 'outline';
  const chaptersLabel = $('n-chapters').closest('label');
  if (chaptersLabel) {
    const hide = mode === 'improv' || mode === 'dialog' || mode === 'rewrite' || mode === 'continue';
    chaptersLabel.style.display = hide ? 'none' : '';
  }
  const srcBox = $('source-import-box');
  if (srcBox) srcBox.style.display = (mode === 'rewrite' || mode === 'continue') ? 'block' : 'none';
  // 续写模式：故事背景/世界观/写作风格/参考小说文本直接继承原小说，无需手动填写
  ['n-background', 'n-worldbuilding', 'n-style', 'n-reference'].forEach(id => {
    const el = $(id);
    if (el) {
      const label = el.closest('label');
      if (label) label.style.display = (mode === 'continue') ? 'none' : '';
    }
  });
  renderSteps();
}

function goStep(n) {
  state.wizardStep = n;
  renderSteps();
}

function getWizardSteps() {
  const mode = $('n-mode') ? $('n-mode').value : 'outline';
  return mode === 'continue' ? [1, 'analyze', 2, 3] : [1, 2, 3];
}

function nextStep() {
  const steps = getWizardSteps();
  const idx = steps.indexOf(state.wizardStep);
  if (idx >= 0 && idx < steps.length - 1) goStep(steps[idx + 1]);
}

function prevStep() {
  const steps = getWizardSteps();
  const idx = steps.indexOf(state.wizardStep);
  if (idx > 0) goStep(steps[idx - 1]);
}

function renderSteps() {
  const mode = $('n-mode') ? $('n-mode').value : 'outline';
  const isContinue = mode === 'continue';
  const steps = getWizardSteps();

  // 续写模式：显示 AI 拆解步骤指示器，更新后续编号
  const dotAnalyze = $('step-dot-analyze');
  if (dotAnalyze) dotAnalyze.style.display = isContinue ? '' : 'none';

  const dot2 = $('step-dot-2');
  if (dot2) dot2.textContent = isContinue ? '③ 角色设定' : '② 角色设定';
  const dot3 = $('step-dot-3');
  if (dot3) dot3.textContent = isContinue ? '④ 模型与提示词' : '③ 模型与提示词';

  // 面板显隐
  ['step-1', 'step-analyze', 'step-2', 'step-3'].forEach(id => {
    const panel = $(id);
    if (panel) panel.style.display = '';
  });
  if (!isContinue) {
    const ap = $('step-analyze');
    if (ap) ap.style.display = 'none';
  }
  // 非续写模式跳过 analyze
  if (state.wizardStep === 'analyze' && !isContinue) {
    state.wizardStep = 2;
  }

  [1, 'analyze', 2, 3].forEach(i => {
    const panelId = i === 'analyze' ? 'step-analyze' : 'step-' + i;
    const panel = $(panelId);
    if (panel) panel.style.display = (i === state.wizardStep) ? 'block' : 'none';

    const dotId = i === 'analyze' ? 'step-dot-analyze' : 'step-dot-' + i;
    const dot = $(dotId);
    if (dot) {
      dot.classList.toggle('active', i === state.wizardStep);
      const curIdx = steps.indexOf(state.wizardStep);
      const thisIdx = steps.indexOf(i);
      dot.classList.toggle('done', thisIdx >= 0 && curIdx >= 0 && thisIdx < curIdx);
    }
  });

  if (state.wizardStep === 'analyze') renderWizardAnalyzeBox();
  if (state.wizardStep === 2) {
    renderAnalyzedCharacters();
    renderCharacters();
    renderRelations();
  }
}

async function saveNovelBasics() {
  const title = $('n-title').value.trim();
  if (!title) { toast('请填写小说标题', 'err'); return false; }
  const body = {
    title,
    genre: $('n-genre').value.trim(),
    style: $('n-style').value.trim(),
    reference_text: $('n-reference').value.trim(),
    background: $('n-background').value.trim(),
    worldbuilding: $('n-worldbuilding').value.trim(),
    chapter_count: parseInt($('n-chapters').value) || 10,
    words_per_chapter: parseInt($('n-words').value) || 2000,
    mode: $('n-mode').value || 'outline',
    source_text: $('n-source').value.trim(),
    task_instruction: $('n-task-instruction').value.trim(),
    structured_profile: state.novelProfile ? JSON.stringify(state.novelProfile) : '',
    worldbook_ids: (state.novel && state.novel.worldbook_ids) || [],
  };
  try {
    if (state.novel) {
      const d = await api('/api/novels/' + state.novel.id, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      state.novel = d.novel;
    } else {
      const d = await api('/api/novels', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      state.novel = d.novel;
    }
    toast('基本信息已保存', 'ok');
    // 新建时更新 URL 到具体 id（用 replaceState 避免触发 hashchange 导致步骤重置）
    if (window.location.hash.includes('/new')) {
      history.replaceState(null, '', '#/novels/' + state.novel.id + '/edit');
    }
    loadNovels();
    return true;
  } catch (e) { toast(e.message, 'err'); return false; }
}

// 保存基本信息并进入下一步（供步骤1的「下一步」按钮使用）
async function saveNovelBasicsAndNext() {
  const ok = await saveNovelBasics();
  if (ok) nextStep();
}

// 只保存角色设定（不跳转），供步骤2的「保存角色设定」按钮使用
async function saveNovelCharsOnly() {
  if (!state.novel) return toast('请先保存基本信息', 'err');
  const body = {
    character_ids: state.novel.character_ids || [],
    relationships: state.relations.filter(r => r.char1_id && r.char2_id && r.char1_id !== r.char2_id),
  };
  try {
    const d = await api('/api/novels/' + state.novel.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    state.novel = d.novel;
    toast('角色设定已保存', 'ok');
    loadNovels();
  } catch (e) { toast(e.message, 'err'); }
}

// 保存模型选择 + 全局前置提示词；goNext 为 true 时保存后跳转到生成页
async function saveNovelModelAndPrompt(goNext = false) {
  if (!state.novel) return toast('请先保存基本信息', 'err');
  try {
    // 保存小说级模型选择
    const modelId = $('n-model').value || '';
    const d = await api('/api/novels/' + state.novel.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text_model_id: modelId }),
    });
    state.novel = d.novel;
    // 保存全局前置提示词
    await saveGlobalPrompt();
    toast('模型与提示词已保存', 'ok');
    if (goNext) {
      // 根据创作模式跳转
      if (state.novel.mode === 'improv') {
        nav('#/novels/' + state.novel.id + '/improv');
      } else if (state.novel.mode === 'dialog') {
        nav('#/novels/' + state.novel.id + '/dialog');
      } else if (state.novel.mode === 'rewrite') {
        nav('#/novels/' + state.novel.id + '/rewrite');
      } else if (state.novel.mode === 'continue') {
        nav('#/novels/' + state.novel.id + '/continue');
      } else {
        nav('#/novels/' + state.novel.id + '/generate');
      }
    }
  } catch (e) { toast(e.message, 'err'); }
}

// 打开创作/编辑页（基本信息 + 角色设定）
async function openEditorPage(id) {
  try {
    const d = await api('/api/novels/' + id);
    state.novel = d.novel;
    currentNovelId = id;
    $('n-title').value = state.novel.title || '';
    $('n-genre').value = state.novel.genre || '';
    $('n-style').value = state.novel.style || '';
    $('n-reference').value = state.novel.reference_text || '';
    $('n-background').value = state.novel.background || '';
    $('n-worldbuilding').value = state.novel.worldbuilding || '';
    $('n-source').value = state.novel.source_text || '';
    try { state.novelProfile = state.novel.structured_profile ? JSON.parse(state.novel.structured_profile) : null; }
    catch (e) { state.novelProfile = null; }
    state.novelProfileSource = state.novel.source_text || '';
    $('n-task-instruction').value = state.novel.task_instruction || '';
    $('n-chapters').value = state.novel.chapter_count || 10;
    $('n-words').value = state.novel.words_per_chapter || 2000;
    renderNovelModelSelect();
    renderSettings();
    renderGenreSelect();
    renderNovelWorldbookSelect();
    $('n-mode').value = state.novel.mode || 'outline';
    onModeChange();
    state.relations = (state.novel.relationships || []).map(r => ({ ...r }));
    $('editor-title').textContent = '编辑《' + (state.novel.title || '未命名') + '》';
    // 若已有大纲，更新"编辑设定"链接指向正确 id
    const editLink = $('gen-edit-link');
    if (editLink) editLink.setAttribute('href', '#/novels/' + id + '/edit');
    state.wizardStep = resumeWizardStep || 1;
    resumeWizardStep = null;
    renderSteps();
    window.scrollTo({ top: 0 });
  } catch (e) {
    toast(e.message, 'err');
    nav('#/novels');
  }
}

// 打开章节生成页
async function openGeneratePage(id) {
  try {
    const d = await api('/api/novels/' + id);
    state.novel = d.novel;
    currentNovelId = id;
    $('gen-title').textContent = '《' + (state.novel.title || '未命名') + '》 章节生成';
    const editLink = $('gen-edit-link');
    if (editLink) editLink.setAttribute('href', '#/novels/' + id + '/edit');
    renderWorkspace();
    window.scrollTo({ top: 0 });
  } catch (e) {
    toast(e.message, 'err');
    nav('#/novels');
  }
}

// 兼容旧的 openNovel 引用
async function openNovel(id) {
  nav('#/novels/' + id + '/edit');
}

// 打开章节详情/生成页
async function openChapterPage(id, index) {
  try {
    const d = await api('/api/novels/' + id);
    state.novel = d.novel;
    currentNovelId = id;
    const chapters = state.novel.chapters || [];
    if (index < 1 || index > chapters.length) {
      toast('章节序号越界', 'err');
      nav('#/novels/' + id + '/generate');
      return;
    }
    const backLink = $('chapter-back-link');
    if (backLink) {
      // 根据创作模式决定返回目标：即兴 → 即兴写作页，对话 → 对话页，改写 → 改写页，续写 → 续写页，大纲 → 生成页
      const backTarget = state.novel.mode === 'improv' ? '/improv'
        : state.novel.mode === 'dialog' ? '/dialog'
        : state.novel.mode === 'rewrite' ? '/rewrite'
        : state.novel.mode === 'continue' ? '/continue' : '/generate';
      backLink.setAttribute('href', '#/novels/' + id + backTarget);
    }
    chapterEditing = null;  // 切换到章节页时重置编辑状态
    renderChapterPage(index);
    window.scrollTo({ top: 0 });
  } catch (e) {
    toast(e.message, 'err');
    nav('#/novels');
  }
}

// ============ 即兴交互式写作 ============
let improvGenerating = false;  // 是否正在生成中（防止重复提交）
let improvSortDesc = true;     // 章节排序：默认倒序（最新在前）

async function openImprovPage(id) {
  try {
    const d = await api('/api/novels/' + id);
    state.novel = d.novel;
    currentNovelId = id;
    $('improv-title').textContent = '《' + (state.novel.title || '未命名') + '》 即兴写作';
    const editLink = $('improv-edit-link');
    if (editLink) editLink.setAttribute('href', '#/novels/' + id + '/edit');
    renderImprov();
    window.scrollTo({ top: 0 });
  } catch (e) {
    toast(e.message, 'err');
    nav('#/novels');
  }
}

// 渲染即兴写作页：展示已生成章节 + 更新下一章提示
function renderImprov() {
  const n = state.novel;
  const body = $('improv-body');
  const done = (n.chapters || []).filter(c => c.content);
  const nextIndex = (n.chapters || []).length + 1;

  const hint = $('improv-chapter-hint');
  if (hint) hint.textContent = done.length ? `已写 ${done.length} 章，接下来写第 ${nextIndex} 章` : '接下来写第 1 章';

  const readBtn = $('improv-read-btn');
  if (readBtn) readBtn.style.display = done.length ? '' : 'none';

  if (!done.length) {
    body.innerHTML = '<div class="card meta">还没有章节。在上方输入本章写作指引，点击「生成本章」开始创作。</div>';
    return;
  }

  // 排序：默认倒序（最新在前），可切换正序
  const ordered = improvSortDesc ? done.slice().reverse() : done;
  // 最近 4 章（index 最大的 4 章）默认「完整内容」，其余默认「摘要」
  const maxIndex = Math.max(...done.map(c => c.index));
  const recentSet = new Set(done.filter(c => c.index > maxIndex - 4).map(c => c.index));

  body.innerHTML = ordered.map(c => {
    const defaultMode = recentSet.has(c.index) ? 'full' : 'summary';
    return `
    <div class="card improv-chapter-card">
      <div class="row">
        <span class="title">第${c.index}章</span>
        <input class="improv-title-input" id="improv-title-${c.index}" value="${esc(c.title || '')}" placeholder="第${c.index}章标题（可编辑）" onchange="saveImprovTitle(${c.index})">
        <span class="meta">约 ${c.word_count || ''} 字</span>
        <span class="spacer"></span>
        <button class="btn" onclick="nav('#/novels/${n.id}/chapter/${c.index}')">查看/编辑正文</button>
      </div>
      ${c.instruction ? `<div class="improv-instruction-hint">📝 本章写作提示：${esc(c.instruction)}</div>` : ''}
      ${c.summary ? `<div class="improv-chapter-summary">${esc(c.summary)}</div>` : ''}
      <div class="improv-ref-row">
        <label class="improv-ref-item">
          <input type="checkbox" id="improv-ref-${c.index}" checked onchange="onImprovRefToggle(${c.index})">
          <span>引用本章</span>
        </label>
        <select id="improv-ref-mode-${c.index}">
          <option value="summary" ${defaultMode === 'summary' ? 'selected' : ''}>带入摘要</option>
          <option value="full" ${defaultMode === 'full' ? 'selected' : ''}>带入完整内容</option>
        </select>
      </div>
    </div>`;
  }).join('');

  // 更新排序按钮文案
  const sortBtn = $('improv-sort-btn');
  if (sortBtn) sortBtn.textContent = improvSortDesc ? '排序：最新在前' : '排序：最早在前';
}

// 切换章节排序（正序/倒序）
function toggleImprovSort() {
  improvSortDesc = !improvSortDesc;
  renderImprov();
}

// 切换引用勾选时，联动启用/禁用方式下拉
function onImprovRefToggle(index) {
  const cb = $('improv-ref-' + index);
  const modeSel = $('improv-ref-mode-' + index);
  if (cb && modeSel) modeSel.disabled = !cb.checked;
}

// 保存即兴章节标题
async function saveImprovTitle(index) {
  const input = $('improv-title-' + index);
  if (!input) return;
  const title = input.value.trim();
  try {
    const d = await api(`/api/novels/${state.novel.id}/chapter/${index}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    state.novel = d.novel;
    toast('标题已保存', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// 生成即兴章节（流式）
async function generateImprovChapter() {
  if (improvGenerating) return;
  const instruction = $('improv-instruction').value.trim();
  if (!instruction) return toast('请填写本章写作指引', 'err');

  // 收集用户勾选的引用章节
  const contextChapters = [];
  (state.novel.chapters || []).forEach(c => {
    const cb = $('improv-ref-' + c.index);
    if (cb && cb.checked) {
      const modeSel = $('improv-ref-mode-' + c.index);
      contextChapters.push({ index: c.index, mode: modeSel ? modeSel.value : 'summary' });
    }
  });

  improvGenerating = true;
  const btn = $('improv-gen-btn');
  btn.disabled = true;
  btn.textContent = '生成中…';
  $('improv-instruction').disabled = true;

  // 在正文顶部插入生成面板
  const body = $('improv-body');
  const panelId = 'improv-gen-' + Date.now();
  body.insertAdjacentHTML('afterbegin', `
    <div class="card gen-panel" id="${panelId}">
      <div class="row">
        <span class="title">新章节生成中</span>
        <span class="badge gen-badge" id="${panelId}-badge">生成中…</span>
        <span class="spacer"></span>
        <span class="meta" id="${panelId}-words"></span>
      </div>
      <div class="gen-output" id="${panelId}-out"></div>
    </div>`);
  const out = $(panelId + '-out');
  const badge = $(panelId + '-badge');
  const wordsEl = $(panelId + '-words');

  let full = '';
  let wordCount = 0;
  let received = false;
  const waitTimer = setTimeout(() => {
    if (!received && badge) badge.textContent = '模型思考中…';
  }, 9000);

  try {
    await streamApi(`/api/novels/${state.novel.id}/improv/stream`, (ev) => {
      if (ev.type === 'delta') {
        if (!received) { received = true; clearTimeout(waitTimer); if (badge) badge.textContent = '生成中…'; }
        full += ev.content;
        if (out) { out.textContent = full; out.scrollTop = out.scrollHeight; }
      } else if (ev.type === 'chapter_done') {
        wordCount = ev.word_count || 0;
        if (wordsEl) wordsEl.textContent = `约 ${wordCount} 字`;
        if (badge) badge.textContent = '正文完成，生成摘要…';
      } else if (ev.type === 'done') {
        state.novel = ev.novel;
      } else if (ev.type === 'error') {
        throw new Error(ev.message);
      }
    }, { instruction, context_chapters: contextChapters });
  } catch (e) {
    toast(e.message, 'err');
    $(panelId).remove();
    return;
  } finally {
    clearTimeout(waitTimer);
    improvGenerating = false;
    btn.disabled = false;
    btn.textContent = '生成本章';
    $('improv-instruction').disabled = false;
  }

  if (!received) {
    toast('模型未返回内容，请重试', 'err');
    $(panelId).remove();
    return;
  }

  $(panelId).remove();
  $('improv-instruction').value = '';
  renderImprov();
  toast('本章完成', 'ok');
}

// ============ 对话模式（IM 聊天式推进剧情） ============
let dialogSending = false;  // 是否正在等待 AI 回复（防止重复发送）

async function openDialogPage(id) {
  try {
    const d = await api('/api/novels/' + id);
    state.novel = d.novel;
    currentNovelId = id;
    $('dialog-title').textContent = '《' + (state.novel.title || '未命名') + '》 对话创作';
    const editLink = $('dialog-edit-link');
    if (editLink) editLink.setAttribute('href', '#/novels/' + id + '/edit');
    renderDialog();
    window.scrollTo({ top: 0 });
  } catch (e) {
    toast(e.message, 'err');
    nav('#/novels');
  }
}

// 渲染对话页下方的「已生成章节」列表（可查看/编辑/删除）
function renderDialogChapters() {
  const box = $('dialog-chapters-list');
  const wrap = $('dialog-chapters');
  if (!box || !wrap) return;
  const chs = (state.novel && state.novel.chapters) || [];
  if (!chs.length) {
    wrap.style.display = 'none';
    return;
  }
  wrap.style.display = 'block';
  box.innerHTML = chs.map(ch => `
    <div class="dialog-chapter-item">
      <span class="dialog-chapter-idx">第${ch.index}章</span>
      <span class="dialog-chapter-name">${esc(ch.title || '')}</span>
      <span class="meta">${ch.word_count || 0} 字</span>
      <span class="spacer"></span>
      <button class="dialog-act-btn" onclick="nav('#/novels/${state.novel.id}/chapter/${ch.index}')">查看/编辑</button>
      <button class="dialog-act-btn danger" onclick="deleteDialogChapter(${ch.index})">删除</button>
    </div>`).join('');
}

// 删除对话模式生成的章节
async function deleteDialogChapter(index) {
  if (!confirm(`确定删除第 ${index} 章？此操作不可恢复。`)) return;
  try {
    const d = await api(`/api/novels/${state.novel.id}/chapter/${index}`, { method: 'DELETE' });
    state.novel = d.novel;
    renderDialogChapters();
    toast('章节已删除', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// 渲染对话历史（IM 气泡样式，每条消息带操作按钮）
function renderDialog() {
  const chat = $('dialog-chat');
  if (!chat) return;
  // 先渲染已生成章节列表（无论对话是否为空都要展示）
  renderDialogChapters();
  const msgs = (state.novel && state.novel.dialog_messages) || [];
  if (!msgs.length) {
    chat.innerHTML = `
      <div class="dialog-empty">
        <div class="dialog-empty-icon">💬</div>
        <div class="dialog-empty-title">开始对话式创作</div>
        <div class="dialog-empty-hint">在下方输入一句话，告诉 AI 剧情走向（例如场景、人物动作、冲突），AI 会以一段不超过 500 字的正文回应，像聊天一样推进故事。</div>
      </div>`;
    return;
  }
  chat.innerHTML = msgs.map((m, idx) => {
    const isUser = m.role === 'user';
    // 每条消息的操作按钮：编辑 + （AI 消息）生成章节 + 删除（删除该消息及之后所有消息）
    const actions = `
      <div class="dialog-msg-actions">
        <button class="dialog-act-btn" onclick="editDialogMessage(${idx})">编辑</button>
        ${!isUser ? `<button class="dialog-act-btn" onclick="dialogToChapter(${idx})">生成章节</button>` : ''}
        <button class="dialog-act-btn danger" onclick="deleteDialogMessage(${idx})">删除</button>
      </div>`;
    return `
      <div class="dialog-msg ${isUser ? 'dialog-msg-user' : 'dialog-msg-ai'}" data-idx="${idx}">
        <div class="dialog-avatar">${isUser ? '我' : 'AI'}</div>
        <div class="dialog-bubble-wrap">
          <div class="dialog-bubble" id="dialog-bubble-${idx}">${esc(m.content)}</div>
          ${actions}
        </div>
      </div>`;
  }).join('');
  chat.scrollTop = chat.scrollHeight;
}

// 编辑某条消息：气泡变成文本框，提供「保存并重新生成」「取消」
function editDialogMessage(idx) {
  const msgs = (state.novel && state.novel.dialog_messages) || [];
  const m = msgs[idx];
  if (!m) return;
  const wrap = document.querySelector(`.dialog-msg[data-idx="${idx}"] .dialog-bubble-wrap`);
  if (!wrap) return;
  const isUser = m.role === 'user';
  // 记录原气泡宽度，让编辑框与气泡等宽（避免换成 textarea 后收缩）
  const bubbleEl = wrap.querySelector('.dialog-bubble');
  const bubbleWidth = bubbleEl ? Math.round(bubbleEl.getBoundingClientRect().width) : 0;
  wrap.innerHTML = `
    <textarea class="dialog-edit-textarea" id="dialog-edit-${idx}">${esc(m.content)}</textarea>
    <div class="dialog-msg-actions">
      <button class="dialog-act-btn primary" onclick="saveDialogEdit(${idx})">${isUser ? '保存并重新生成' : '保存修改'}</button>
      <button class="dialog-act-btn" onclick="renderDialog()">取消</button>
    </div>
    ${isUser ? '<div class="dialog-edit-hint">保存后将截断此消息之后的对话，并重新生成 AI 回复。</div>'
             : '<div class="dialog-edit-hint">仅修改这段 AI 返回的内容，不会重新调用 AI。</div>'}
  `;
  const ta = $('dialog-edit-' + idx);
  if (ta) {
    if (bubbleWidth > 0) ta.style.minWidth = bubbleWidth + 'px';
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    autoResizeTextarea(ta);
    ta.addEventListener('input', () => autoResizeTextarea(ta));
  }
}

// 让 textarea 高度随内容行数自适应（与气泡等宽，行数变化自动增高）
function autoResizeTextarea(ta) {
  ta.style.height = 'auto';
  ta.style.height = (ta.scrollHeight + 2) + 'px';
}

// 删除某条对话消息及其之后的所有消息（点击删除时自动选中该消息及之后的消息）
async function deleteDialogMessage(idx) {
  if (dialogSending) return;
  const msgs = (state.novel && state.novel.dialog_messages) || [];
  if (idx < 0 || idx >= msgs.length) return;
  const count = msgs.length - idx;  // 从 idx 到末尾的消息数
  if (!confirm(`删除这条消息及其之后的 ${count} 条消息？`)) return;
  // 自动选择 idx 及之后的所有消息索引
  const indexes = [];
  for (let i = idx; i < msgs.length; i++) indexes.push(i);
  try {
    const d = await api(`/api/novels/${state.novel.id}/dialog/delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ indexes }),
    });
    state.novel = d.novel;
    renderDialog();
    toast(`已删除 ${count} 条消息`, 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// 保存编辑：
// - 编辑 AI 消息：直接更新内容，不请求 AI 重新生成（用户修复 AI 返回的正文）
// - 编辑用户消息：截断历史到该消息，重新请求 AI 生成回复
async function saveDialogEdit(idx) {
  if (dialogSending) return;
  const ta = $('dialog-edit-' + idx);
  if (!ta) return;
  const newText = ta.value.trim();
  if (!newText) return toast('内容不能为空', 'err');

  const msgs = (state.novel && state.novel.dialog_messages) || [];
  const m = msgs[idx];
  if (!m) return;
  const isUser = m.role === 'user';

  // 编辑 AI 消息：直接更新，不调 AI
  if (!isUser) {
    try {
      const d = await api(`/api/novels/${state.novel.id}/dialog/update`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index: idx, content: newText }),
      });
      state.novel = d.novel;
      renderDialog();
      toast('内容已更新', 'ok');
    } catch (e) { toast(e.message, 'err'); }
    return;
  }

  // 编辑用户消息：重新生成 AI 回复
  // 截断历史到该消息之前（不含该消息）
  const prefix = msgs.slice(0, idx);

  dialogSending = true;
  const btn = $('dialog-send-btn');
  btn.disabled = true;
  btn.textContent = '重新生成中…';

  const chat = $('dialog-chat');
  // 移除该消息及其之后的所有消息
  chat.querySelectorAll('.dialog-msg').forEach(el => {
    if (parseInt(el.dataset.idx, 10) >= idx) el.remove();
  });

  // 追加显示用户消息（编辑后的内容）
  chat.insertAdjacentHTML('beforeend', `
    <div class="dialog-msg dialog-msg-user">
      <div class="dialog-avatar">我</div>
      <div class="dialog-bubble-wrap"><div class="dialog-bubble">${esc(newText)}</div></div>
    </div>`);

  // AI 气泡（流式填充）
  const aiId = 'dialog-ai-' + Date.now();
  chat.insertAdjacentHTML('beforeend', `
    <div class="dialog-msg dialog-msg-ai" id="${aiId}">
      <div class="dialog-avatar">AI</div>
      <div class="dialog-bubble-wrap"><div class="dialog-bubble" id="${aiId}-bubble"><span class="dialog-typing">正在思考…</span></div></div>
    </div>`);
  const bubble = $(aiId + '-bubble');
  chat.scrollTop = chat.scrollHeight;

  let full = '';
  try {
    const body = { text: newText, history: prefix };
    await streamApi(`/api/novels/${state.novel.id}/dialog/stream`, (ev) => {
      if (ev.type === 'delta') {
        full += ev.content;
        if (bubble) bubble.textContent = full;
        chat.scrollTop = chat.scrollHeight;
      } else if (ev.type === 'done') {
        if (ev.content && bubble && !full.trim()) bubble.textContent = ev.content;
      } else if (ev.type === 'error') {
        throw new Error(ev.message);
      }
    }, body);

    if (!full.trim()) throw new Error('模型未返回内容，请重试');
    // 更新本地 state：前缀 + 新 user + 新 AI
    state.novel.dialog_messages = prefix.concat([
      { role: 'user', content: newText },
      { role: 'assistant', content: full.trim() },
    ]);
    renderDialog();
    toast('已重新生成', 'ok');
  } catch (e) {
    if (bubble) { bubble.textContent = '⚠️ ' + e.message; bubble.classList.add('dialog-error'); }
    toast(e.message, 'err');
  } finally {
    dialogSending = false;
    btn.disabled = false;
    btn.textContent = '发送';
  }
}

// 在某次 AI 消息后输出章节（直接合并之前的 AI 输出，不重新生成正文，仅提取摘要）
async function dialogToChapter(idx) {
  if (dialogSending) return;
  if (!confirm('将把到目前为止的 AI 输出（含本条）直接合并成一个章节，确定继续？')) return;

  const msgs = (state.novel && state.novel.dialog_messages) || [];
  if (idx < 0 || idx >= msgs.length) return toast('消息索引无效', 'err');

  dialogSending = true;
  const btn = $('dialog-send-btn');
  btn.disabled = true;
  btn.textContent = '生成中…';

  const chat = $('dialog-chat');
  // 插入章节生成面板
  const panelId = 'dialog-chapter-' + Date.now();
  chat.insertAdjacentHTML('beforeend', `
    <div class="dialog-chapter-panel" id="${panelId}">
      <div class="row">
        <span class="title">正在合并并提取摘要…</span>
        <span class="badge gen-badge">生成中…</span>
      </div>
      <div class="gen-output" id="${panelId}-out"></div>
    </div>`);
  const out = $(panelId + '-out');
  chat.scrollTop = chat.scrollHeight;

  try {
    const d = await api(`/api/novels/${state.novel.id}/dialog/chapter`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ up_to: idx }),
    });

    const chapterIndex = d.chapter_index;
    // 展示合并后的章节正文
    if (out) {
      out.textContent = d.content;
      out.scrollTop = out.scrollHeight;
    }
    // 后端已删除已合并的对话消息，重新拉取 novel 以同步 state
    const fresh = await api('/api/novels/' + state.novel.id);
    state.novel = fresh.novel;
    // 重新渲染：对话区（已合并消息消失）+ 章节列表
    renderDialog();
    loadNovels();
    toast(`第 ${chapterIndex} 章已生成（${d.word_count} 字）`, 'ok');
    if (out) {
      const titleEl = panelId && document.querySelector(`#${panelId} .title`);
      if (titleEl) titleEl.textContent = `第 ${chapterIndex} 章 · ${d.title || ''}（${d.word_count} 字）`;
    }
  } catch (e) {
    if (out) { out.textContent = '⚠️ ' + e.message; out.classList.add('gen-error'); }
    toast(e.message, 'err');
  } finally {
    dialogSending = false;
    btn.disabled = false;
    btn.textContent = '发送';
  }
}

// 发送对话消息
async function sendDialogMessage() {
  if (dialogSending) return;
  const input = $('dialog-input');
  const text = input.value.trim();
  if (!text) return toast('请先输入内容', 'err');
  // 字数由作者在指令中指定（如「写300字」），后端会自动提取，未指定则默认 500 字

  dialogSending = true;
  const btn = $('dialog-send-btn');
  btn.disabled = true;
  btn.textContent = '回复中…';
  input.disabled = true;

  // 立即在聊天区显示用户消息
  const chat = $('dialog-chat');
  const emptyEl = chat.querySelector('.dialog-empty');
  if (emptyEl) emptyEl.remove();
  chat.insertAdjacentHTML('beforeend', `
    <div class="dialog-msg dialog-msg-user">
      <div class="dialog-avatar">我</div>
      <div class="dialog-bubble-wrap"><div class="dialog-bubble">${esc(text)}</div></div>
    </div>`);

  // AI 气泡（流式填充）
  const aiId = 'dialog-ai-' + Date.now();
  chat.insertAdjacentHTML('beforeend', `
    <div class="dialog-msg dialog-msg-ai" id="${aiId}">
      <div class="dialog-avatar">AI</div>
      <div class="dialog-bubble-wrap"><div class="dialog-bubble" id="${aiId}-bubble"><span class="dialog-typing">正在思考…</span></div></div>
    </div>`);
  const bubble = $(aiId + '-bubble');
  chat.scrollTop = chat.scrollHeight;

  let full = '';
  try {
    const body = { text };
    await streamApi(`/api/novels/${state.novel.id}/dialog/stream`, (ev) => {
      if (ev.type === 'delta') {
        full += ev.content;
        if (bubble) bubble.textContent = full;
        chat.scrollTop = chat.scrollHeight;
      } else if (ev.type === 'done') {
        if (ev.content && bubble && !full.trim()) bubble.textContent = ev.content;
      } else if (ev.type === 'error') {
        throw new Error(ev.message);
      }
    }, body);

    if (!full.trim()) throw new Error('模型未返回内容，请重试');
    // 更新 state 中的对话历史（供下次渲染）
    const msgs = (state.novel.dialog_messages || []);
    state.novel.dialog_messages = msgs.concat([
      { role: 'user', content: text },
      { role: 'assistant', content: full.trim() },
    ]);
    input.value = '';
    // 重新渲染，让每条消息（含新 AI 消息）都带上「编辑」「生成章节」按钮
    renderDialog();
  } catch (e) {
    if (bubble) { bubble.textContent = '⚠️ ' + e.message; bubble.classList.add('dialog-error'); }
    toast(e.message, 'err');
  } finally {
    dialogSending = false;
    btn.disabled = false;
    btn.textContent = '发送';
    input.disabled = false;
    input.focus();
    chat.scrollTop = chat.scrollHeight;
  }
}

// 对话模式输入框：回车发送，Shift+回车换行
document.addEventListener('keydown', (e) => {
  if (e.target && e.target.id === 'dialog-input' && e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendDialogMessage();
  }
});

// ============ 阅读模式 ============
let readerFontSize = 18;  // 阅读正文字号（px）

// 打开阅读模式
async function openReaderPage(id) {
  try {
    const d = await api('/api/novels/' + id);
    state.novel = d.novel;
    currentNovelId = id;
    const backLink = $('reader-back-link');
    if (backLink) backLink.setAttribute('href', readerBackHash || '#/novels');
    readerBackHash = null;
    renderReader();
    window.scrollTo({ top: 0 });
  } catch (e) {
    toast(e.message, 'err');
    nav('#/novels');
  }
}

// 渲染阅读正文（连贯展示所有已生成章节）+ 左侧目录
function renderReader() {
  const n = state.novel;
  if (!n) return;
  const body = $('reader-body');
  const toc = $('reader-toc');
  const done = (n.chapters || []).filter(c => c.content);
  if (!done.length) {
    body.innerHTML = '<div class="card meta">暂无已生成章节，无法进入阅读模式。</div>';
    if (toc) toc.innerHTML = '';
    return;
  }

  // 渲染正文
  let html = `<div class="reader-book-title">《${esc(n.title)}》</div>`;
  if (n.genre) html += `<div class="reader-meta">${esc(n.genre)}${n.summary ? ' · ' + esc(n.summary.slice(0, 60)) : ''}</div>`;

  html += done.map(c => `
    <div class="reader-chapter" id="reader-ch-${c.index}">
      <h2 class="reader-ch-title">第${c.index}章 ${esc(c.title || '')}</h2>
      <div class="reader-ch-content">${highlightCharacterNames(c.content)}</div>
    </div>`).join('');

  body.innerHTML = html;

  // 渲染左侧目录（用 onclick + scrollIntoView，避免改 hash 触发路由）
  if (toc) {
    toc.innerHTML = `<div class="reader-toc-title">目录</div>` + done.map(c =>
      `<div class="reader-toc-item" data-index="${c.index}" onclick="scrollToReaderChapter(${c.index})">第${c.index}章 ${esc(c.title || '')}</div>`
    ).join('');
  }
  applyReaderFont();
  setupReaderScrollSpy();
}

// 点击目录项：滚动到对应章节（不改变 URL hash）
function scrollToReaderChapter(index) {
  const el = $('reader-ch-' + index);
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  highlightReaderToc(index);
}

// 高亮目录中指定章节
function highlightReaderToc(index) {
  document.querySelectorAll('.reader-toc-item').forEach(el => {
    el.classList.toggle('active', parseInt(el.dataset.index, 10) === index);
  });
}

// 滚动监听：根据当前阅读位置高亮对应目录章节
let _readerScrollSpy = null;
function setupReaderScrollSpy() {
  // 清理旧监听
  if (_readerScrollSpy) {
    window.removeEventListener('scroll', _readerScrollSpy);
    _readerScrollSpy = null;
  }

  _readerScrollSpy = () => {
    // 计算当前滚动位置处于哪个章节
    const chapters = Array.from(document.querySelectorAll('.reader-chapter'));
    if (!chapters.length) return;
    const scrollTop = window.scrollY || document.documentElement.scrollTop || 0;
    const offset = 100;  // 章节标题距顶部的判定偏移
    // 默认当前为第1章，滚动超过后续章节起始位置时切换
    let current = chapters[0];
    for (const ch of chapters) {
      if (ch.offsetTop - offset <= scrollTop) {
        current = ch;
      } else {
        break;
      }
    }
    const idx = parseInt(current.id.replace('reader-ch-', ''), 10);
    highlightReaderToc(idx);
  };

  window.addEventListener('scroll', _readerScrollSpy, { passive: true });
  // 初始执行一次，确保进入页面时第1章高亮
  _readerScrollSpy();
}

// 兼容旧引用（不再使用 toggle 目录）
function toggleReaderToc() { /* 目录已常驻左侧，此函数保留为空 */ }
function hideReaderToc() { /* 目录已常驻左侧 */ }

// 调整字号
function changeReaderFont(delta) {
  readerFontSize = Math.min(30, Math.max(14, readerFontSize + delta));
  applyReaderFont();
}

function applyReaderFont() {
  document.querySelectorAll('.reader-ch-content').forEach(el => {
    el.style.fontSize = readerFontSize + 'px';
    el.style.lineHeight = (readerFontSize * 1.8) + 'px';
  });
}

// 渲染章节详情页
function renderChapterPage(index) {
  const n = state.novel;
  const chapters = n.chapters || [];
  const chapter = chapters.find(c => c.index === index);
  if (!chapter) return;

  $('chapter-title').textContent = `《${n.title}》 第 ${index} 章`;
  const body = $('chapter-body');
  const editing = chapterEditing === index;  // 当前是否在编辑本章
  const isFinished = n.status === 'finished';

  let html = '';
  html += `<div class="meta">${esc(chapter.title || '')}${chapter.summary ? ' · ' + esc(chapter.summary) : ''}</div>`;

  // 章节导航：上一章 / 下一章
  const prevIdx = index > 1 ? index - 1 : null;
  const nextIdx = index < chapters.length ? index + 1 : null;
  html += `<div class="row" style="margin:12px 0">
    ${prevIdx ? `<button class="btn" onclick="nav('#/novels/${n.id}/chapter/${prevIdx}')">← 第 ${prevIdx} 章</button>` : ''}
    <span class="spacer"></span>
    ${nextIdx ? `<button class="btn" onclick="nav('#/novels/${n.id}/chapter/${nextIdx}')">第 ${nextIdx} 章 →</button>` : ''}
  </div>`;

  // 操作按钮
  if (isFinished) {
    // 已完结：只读，不显示任何编辑/生成/删除按钮
    html += `<div style="margin:8px 0 16px">
      <span class="meta">该小说已完结，内容为只读。如需修改请回到列表「重开」。</span>
    </div>`;
  } else if (editing) {
    html += `<div style="margin:8px 0 16px">
      <button class="btn primary" onclick="saveChapterEdit(${index})">保存修改</button>
      <button class="btn" onclick="cancelChapterEdit(${index})">取消</button>
      <span class="spacer"></span>
      <button class="btn" id="polish-frag-btn" onclick="polishFragment(${index})">✨ 润色选中片段</button>
      <button class="btn" id="expand-frag-btn" onclick="expandFragment(${index})">📝 扩写选中片段</button>
    </div>
    <div id="frag-panel" style="display:none; margin:8px 0 16px"></div>`;
  } else {
    // 即兴模式：提供写作指引输入框，预填上一次的指引，作者可继续使用或修改后重新生成
    if (n.mode === 'improv') {
      html += `<div class="improv-regen-guide">
        <div class="improv-regen-label">本章写作指引（修改后重新生成本章）</div>
        <textarea id="chapter-instruction" rows="3" placeholder="告诉 AI 这一章想写什么（情节方向、冲突、转折等）">${esc(chapter.instruction || '')}</textarea>
      </div>`;
    }
    html += `<div style="margin:8px 0 16px">
      <button class="btn primary" id="chapter-gen-btn" onclick="generateChapterInPage(${index})">${chapter.content ? '重新生成本章' : '生成本章'}</button>
      ${chapter.content ? `<button class="btn" onclick="startChapterEdit(${index})">编辑本章</button>` : ''}
      ${chapter.content ? `<button class="btn" onclick="summarizeChapter(${index})">生成摘要</button>` : ''}
      ${chapter.content ? `<button class="btn" onclick="exportChapter(${index})">导出本章</button>` : ''}
      <span class="spacer"></span>
      <button class="btn danger" onclick="deleteChapter(${index})">删除本章</button>
    </div>`;
  }

  // 历史版本按钮（仅当章节有内容时显示）
  if (!isFinished && chapter.content) {
    html += `<div style="margin:8px 0 16px">
      <button class="btn" onclick="toggleChapterHistory(${index})">📜 历史版本</button>
    </div>`;
  }
  html += `<div id="chapter-history-panel" style="display:none; margin:8px 0 16px"></div>`;

  // 生成实时输出区（默认隐藏）
  html += `<div id="chapter-gen-panel" style="display:none"></div>`;

  // 正文内容 / 编辑表单
  if (editing) {
    html += `
      <div class="chapter-edit-form">
        <label>章节标题
          <input id="ce-title" value="${esc(chapter.title || '')}" placeholder="章节标题">
        </label>
        <label>章节概要
          <input id="ce-summary" value="${esc(chapter.summary || '')}" placeholder="一句话概要">
        </label>
        <label>正文内容
          <textarea id="ce-content" rows="20" class="chapter-edit-content">${esc(chapter.content || '')}</textarea>
        </label>
      </div>`;
  } else if (chapter.content) {
    html += `<div class="chapter-content full-chapter-content">${highlightCharacterNames(chapter.content)}</div>`;
  } else {
    html += `<div class="card meta">本章尚未生成，点击上方「生成本章」开始。</div>`;
  }

  body.innerHTML = html;
}

// 章节编辑状态（chapterEditing 已在文件顶部声明）

function startChapterEdit(index) {
  chapterEditing = index;
  renderChapterPage(index);
  window.scrollTo({ top: 0 });
}

function cancelChapterEdit(index) {
  chapterEditing = null;
  renderChapterPage(index);
}

async function saveChapterEdit(index) {
  const title = ($('ce-title') || {}).value || '';
  const summary = ($('ce-summary') || {}).value || '';
  const content = ($('ce-content') || {}).value || '';
  try {
    const d = await api(`/api/novels/${state.novel.id}/chapter/${index}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, summary, content }),
    });
    state.novel = d.novel;
    chapterEditing = null;
    renderChapterPage(index);
    loadNovels();
    toast('章节已保存', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// ============ 节选片段润色 / 扩写 ============
// 获取编辑正文文本框中选中的文字；未选中时给出提示
function getSelectedFragment() {
  const ta = $('ce-content');
  if (!ta) { toast('请先进入编辑模式', 'err'); return null; }
  const start = ta.selectionStart, end = ta.selectionEnd;
  if (start === end) {
    toast('请先在正文中选中要处理的文字片段', 'err');
    return null;
  }
  const text = ta.value.substring(start, end).trim();
  if (!text) { toast('选中内容为空，请重新选择', 'err'); return null; }
  if (text.length < 10) { toast('片段过短（至少 10 字），请选中更完整的文字', 'err'); return null; }
  return { text, start, end, ta };
}

// 润色 / 扩写的通用处理：流式获取结果，替换回选中位置
async function runFragmentAction(index, action) {
  const sel = getSelectedFragment();
  if (!sel) return;
  const { text, start, end, ta } = sel;
  const panel = $('frag-panel');
  const btn = $(action === 'polish' ? 'polish-frag-btn' : 'expand-frag-btn');
  const label = action === 'polish' ? '润色' : '扩写';
  if (!panel) return;

  panel.style.display = 'block';
  panel.innerHTML = `
    <div class="card gen-panel">
      <div class="row">
        <span class="title">片段${label}中</span>
        <span class="badge gen-badge" id="frag-badge">生成中…</span>
      </div>
      <div class="gen-output" id="frag-out"></div>
      <div class="row" style="margin-top:10px">
        <button class="btn primary" id="frag-apply-btn" disabled onclick="applyFragment(${index}, ${start}, ${end})">替换到正文</button>
        <button class="btn" onclick="cancelFragment()">取消</button>
      </div>
    </div>`;
  const out = $('frag-out'), badge = $('frag-badge');
  if (btn) btn.disabled = true;

  let full = '';
  try {
    await streamApi(`/api/novels/${state.novel.id}/chapter/${index}/${action}`, (ev) => {
      if (ev.type === 'delta') {
        full += ev.content;
        if (out) { out.textContent = full; out.scrollTop = out.scrollHeight; }
      } else if (ev.type === 'error') {
        throw new Error(ev.message);
      }
    }, { text });
    if (!full.trim()) { throw new Error('模型未返回内容，请重试'); }
    if (badge) badge.textContent = '完成';
    // 暂存结果，供「替换到正文」使用
    panel._fragmentResult = full.trim();
    panel._fragmentRange = { start, end };
    const applyBtn = $('frag-apply-btn');
    if (applyBtn) { applyBtn.disabled = false; applyBtn.textContent = '替换到正文（覆盖选中文字）'; }
    toast(`${label}完成，点击「替换到正文」生效`, 'ok');
  } catch (e) {
    if (out) { out.textContent = '⚠️ ' + e.message; out.classList.add('gen-error'); }
    if (badge) badge.textContent = '失败';
    toast(e.message, 'err');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function polishFragment(index) { runFragmentAction(index, 'polish'); }
function expandFragment(index) { runFragmentAction(index, 'expand'); }

// 将润色/扩写结果替换回正文文本框的选中位置
function applyFragment(index, start, end) {
  const panel = $('frag-panel');
  if (!panel || !panel._fragmentResult) return;
  const ta = $('ce-content');
  if (!ta) return;
  // 重新定位选中区间（若用户中途改动过文本，则退化为按当前选中替换）
  let s = start, e = end;
  if (typeof ta.selectionStart === 'number' && ta.selectionStart !== ta.selectionEnd) {
    s = ta.selectionStart; e = ta.selectionEnd;
  }
  ta.value = ta.value.substring(0, s) + panel._fragmentResult + ta.value.substring(e);
  panel.style.display = 'none';
  panel._fragmentResult = null;
  toast('已替换到正文，记得点「保存修改」', 'ok');
}

function cancelFragment() {
  const panel = $('frag-panel');
  if (panel) { panel.style.display = 'none'; panel._fragmentResult = null; }
}

// 在章节页内流式生成
async function generateChapterInPage(index) {
  const panel = $('chapter-gen-panel');
  const btn = $('chapter-gen-btn');
  const isImprov = state.novel.mode === 'improv';
  // 即兴模式：读取写作指引（预填上一次的，作者可修改）
  let instruction = '';
  if (isImprov) {
    const guideEl = $('chapter-instruction');
    instruction = guideEl ? guideEl.value.trim() : '';
    if (!instruction) {
      toast('请填写本章写作指引', 'err');
      if (guideEl) guideEl.focus();
      return;
    }
  }
  btn.disabled = true;
  btn.textContent = '生成中…';
  const guideEl = $('chapter-instruction');
  if (guideEl) guideEl.disabled = true;
  panel.style.display = 'block';
  panel.innerHTML = `
    <div class="card gen-panel">
      <div class="row">
        <span class="title">第 ${index} 章 生成中</span>
        <span class="badge gen-badge" id="cp-badge">生成中…</span>
        <span class="spacer"></span>
        <span class="meta" id="cp-words"></span>
      </div>
      <div class="gen-output" id="cp-out"></div>
    </div>`;
  const out = $('cp-out'), badge = $('cp-badge'), words = $('cp-words');
  try {
    if (isImprov) {
      await improvRegenerateStream(index, instruction, out, badge, words);
    } else {
      await generateChapterStream(index, out, badge, words);
    }
    panel.style.display = 'none';
    btn.disabled = false;
    btn.textContent = '重新生成本章';
    if (guideEl) guideEl.disabled = false;
    renderChapterPage(index);
    loadNovels();
    toast(`第 ${index} 章完成`, 'ok');
  } catch (e) {
    btn.disabled = false;
    btn.textContent = '重试';
    if (guideEl) guideEl.disabled = false;
    if (out) {
      out.textContent = '⚠️ ' + e.message;
      out.classList.add('gen-error');
    }
    if (badge) badge.textContent = '生成失败';
    toast(e.message, 'err');
  }
}

// 导出单章
function exportChapter(index) {
  const n = state.novel;
  const c = (n.chapters || []).find(x => x.index === index);
  if (!c || !c.content) { toast('本章暂无内容', 'err'); return; }
  const text = `# ${n.title} 第${index}章 ${c.title || ''}\n\n${c.content}\n`;
  downloadText(`${n.title}-第${index}章.md`, text);
  toast('已导出本章', 'ok');
}

// 为单章生成摘要
async function summarizeChapter(index) {
  const n = state.novel;
  if (!n) return;
  showLoading('正在生成本章摘要…', 'AI 正在概括本章核心情节，请稍候');
  try {
    const d = await api(`/api/novels/${n.id}/chapter/${index}/summary`, { method: 'POST' });
    state.novel = d.novel;
    toast('摘要已生成', 'ok');
    renderChapterPage(index);
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    hideLoading();
  }
}

// 删除单章（删除后章节重新编号）
async function deleteChapter(index) {
  const n = state.novel;
  if (!n) return;
  if (!confirm(`确定删除第 ${index} 章吗？删除后后续章节会重新编号，此操作不可恢复。`)) return;
  try {
    const d = await api(`/api/novels/${n.id}/chapter/${index}`, { method: 'DELETE' });
    state.novel = d.novel;
    chapterEditing = null;
    loadNovels();
    toast('章节已删除', 'ok');
    // 删除后跳回生成页（章节详情页可能已不存在）
    nav('#/novels/' + n.id + '/generate');
  } catch (e) { toast(e.message, 'err'); }
}

// ---- Chapter Version History ----

let historyPanelVisible = false;

async function toggleChapterHistory(index) {
  const panel = $('chapter-history-panel');
  if (!panel) return;
  if (historyPanelVisible) {
    panel.style.display = 'none';
    historyPanelVisible = false;
    return;
  }
  historyPanelVisible = true;
  panel.style.display = 'block';
  panel.innerHTML = '<div class="meta">加载中...</div>';
  try {
    const n = state.novel;
    const d = await api(`/api/novels/${n.id}/chapter/${index}/history`);
    renderHistoryList(index, d.versions || []);
  } catch (e) {
    panel.innerHTML = `<div class="meta" style="color:#e74c3c">${esc(e.message)}</div>`;
  }
}

function renderHistoryList(index, versions) {
  const panel = $('chapter-history-panel');
  if (!panel) return;
  if (!versions.length) {
    panel.innerHTML = '<div class="meta">暂无历史版本（编辑或重新生成后会自动保存快照）</div>';
    return;
  }
  let html = '<div class="meta" style="margin-bottom:8px">历史版本（点击「回退」可恢复到该版本）</div>';
  for (const v of versions) {
    const ts = new Date(v.created_at * 1000).toLocaleString('zh-CN');
    const preview = (v.content || '').substring(0, 50);
    const sourceLabel = v.source === 'ai' ? 'AI生成' : '手动编辑';
    html += `<div class="card" style="padding:12px; margin:8px 0">
      <div class="row" style="align-items:center">
        <span class="meta">${ts}</span>
        <span class="badge" style="margin-left:8px">${esc(sourceLabel)}</span>
        <span class="spacer"></span>
        <span class="meta">${v.word_count || 0} 字</span>
      </div>
      <div class="meta" style="margin:6px 0">${esc(preview)}${v.content && v.content.length > 50 ? '...' : ''}</div>
      <button class="btn" onclick="revertToVersion(${index}, '${v.id}')">↩ 回退到此版本</button>
    </div>`;
  }
  panel.innerHTML = html;
}

async function revertToVersion(index, versionId) {
  if (!confirm('确定回退到该版本吗？当前内容将被覆盖。')) return;
  try {
    const n = state.novel;
    const d = await api(`/api/novels/${n.id}/chapter/${index}/revert`, {
      method: 'POST',
      body: JSON.stringify({ version_id: versionId }),
    });
    state.novel = d.novel;
    historyPanelVisible = false;
    const panel = $('chapter-history-panel');
    if (panel) panel.style.display = 'none';
    renderChapterPage(index);
    toast('已回退到指定版本', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

function addRelation() {
  const rel = { char1_id: '', char2_id: '', type: '', description: '' };
  state.relations.push(rel);
  renderRelations();
}

function renderRelations() {
  const box = $('n-relations');
  const chars = currentNovelCharacters();
  const opts = chars.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('');
  box.innerHTML = state.relations.map((r, i) => `
    <div class="relation-item">
      <select onchange="state.relations[${i}].char1_id=this.value">${opts}</select>
      <span>↔</span>
      <select onchange="state.relations[${i}].char2_id=this.value">${opts}</select>
      <input placeholder="关系类型(如 师徒/恋人/仇敌)" onchange="state.relations[${i}].type=this.value" value="${esc(r.type)}">
      <input placeholder="关系描述" style="flex:1" onchange="state.relations[${i}].description=this.value" value="${esc(r.description)}">
      <button class="btn danger" onclick="state.relations.splice(${i},1);renderRelations()">✕</button>
    </div>`).join('');
  state.relations.forEach((r, i) => {
    const item = box.children[i];
    if (!item) return;
    item.children[0].value = r.char1_id;
    item.children[2].value = r.char2_id;
  });
}

function renderWorkspace() {
  const n = state.novel;
  if (!n) return;
  const ws = $('workspace');
  const generated = (n.chapters || []).filter(c => c.content).length;
  const total = (n.chapters || []).length;

  let html = '';
  const mid = n.text_model_id || state.settings.text_model_id || '';
  html += `<div class="meta">题材：${esc(n.genre || '不限')} · ${n.chapter_count}章 · ${n.words_per_chapter}字/章 · 角色 ${(n.character_ids || []).length} 个 · 创作模型：${esc(mid ? modelLabel(mid) : '（未配置）')}</div>`;

  if (n.summary) {
    if (outlineEditing) {
      // 编辑模式：可编辑梗概与世界观
      html += `<h4>故事梗概</h4><textarea id="out-edit-summary" rows="4" class="outline-edit">${esc(n.summary)}</textarea>`;
      if (n.worldbuilding) html += `<h4>世界观</h4><textarea id="out-edit-world" rows="3" class="outline-edit">${esc(n.worldbuilding)}</textarea>`;
    } else {
      html += `<h4>故事梗概</h4><div class="chapter-content">${esc(n.summary)}</div>`;
      if (n.worldbuilding) html += `<h4>世界观</h4><div class="chapter-content">${esc(n.worldbuilding)}</div>`;
    }
  }

  html += `<div style="margin-top:16px">
    <button class="btn primary" onclick="prepareNovel()">${n.summary ? '重新生成大纲' : '① 生成大纲'}</button>
    ${n.chapters && n.chapters.length ? `<button class="btn primary" onclick="generateAll()">② 逐章生成全文（${total} 章）</button>` : ''}
    <select id="export-format" style="padding:4px 8px; border-radius:4px; border:1px solid #ccc">
      <option value="md">Markdown</option>
      <option value="txt">TXT 纯文本</option>
      <option value="epub">EPUB 电子书</option>
    </select>
    <button class="btn" onclick="exportNovel('${n.id}', document.getElementById('export-format').value)">导出</button>
    ${n.summary ? (outlineEditing
      ? `<button class="btn primary" onclick="saveOutline()">保存大纲</button>
         <button class="btn" onclick="toggleOutlineEdit()">取消</button>`
      : `<button class="btn" onclick="toggleOutlineEdit()">编辑大纲</button>`) : ''}
  </div>`;

  if (n.chapters && n.chapters.length) {
    html += `<h4>章节大纲</h4>`;
    html += n.chapters.map((c) => {
      if (outlineEditing) {
        return `
          <div class="chapter-outline outline-edit-row">
            <label class="outline-idx">第${c.index}章</label>
            <input id="out-edit-title-${c.index}" value="${esc(c.title || '')}" placeholder="章节标题">
            <input id="out-edit-sum-${c.index}" value="${esc(c.summary || '')}" placeholder="一句话内容概要">
            ${c.content ? `<span class="badge">已生成</span>` : ''}
          </div>`;
      }
      return `
        <div class="chapter-outline">
          <b>第${c.index}章 ${esc(c.title || '')}</b>
          <span class="meta">${esc(c.summary || '')}</span>
          <span class="spacer"></span>
          ${c.content
            ? `<span class="badge">已生成 ${c.word_count || ''} 字</span>
               <button class="btn" onclick="nav('#/novels/${n.id}/chapter/${c.index}')">查看/重新生成</button>`
            : `<button class="btn primary" onclick="nav('#/novels/${n.id}/chapter/${c.index}')">生成本章</button>`}
        </div>`;
    }).join('');
  }

  const done = (n.chapters || []).filter(c => c.content);
  if (done.length) {
    html += `<h4>正文预览</h4>`;
    html += done.map(c => `
      <div class="card chapter-preview-card" onclick="nav('#/novels/${n.id}/chapter/${c.index}')">
        <div class="row"><span class="title">第${c.index}章 ${esc(c.title || '')}</span>
        <span class="meta">约 ${c.word_count || ''} 字</span>
        <span class="spacer"></span>
        <button class="btn">查看全文 →</button></div>
        <div class="chapter-content">${esc(c.content.slice(0, 200))}${c.content.length > 200 ? '…' : ''}</div>
      </div>`).join('');
  }

  ws.innerHTML = html;
}

async function prepareNovel() {
  const id = state.novel.id;
  showLoading('正在生成大纲…', 'AI 正在分析写作风格并构建故事梗概与章节大纲，请稍候');
  try {
    const d = await api(`/api/novels/${id}/prepare`, { method: 'POST' });
    state.novel = d.novel;
    renderWorkspace();
    toast('大纲生成完成', 'ok');
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    hideLoading();
  }
}

// 流式请求：解析 SSE（data: {json}），逐事件回调
async function streamApi(path, onEvent, body) {
  const headers = { 'Accept': 'text/event-stream' };
  if (authToken) headers['Authorization'] = 'Bearer ' + authToken;
  const opts = { method: 'POST', headers };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    // 网络层错误（连接中断/代理超时等），转为友好中文提示
    throw new Error('网络连接中断，请重试。若原文较长，可尝试稍后重试或检查网络/代理设置。');
  }
  if (res.status === 401) {
    handleUnauthorized();
    throw new Error('未登录或登录已过期');
  }
  if (!res.ok || !res.body) {
    let msg = '请求失败（' + res.status + '）';
    try {
      const d = await res.json();
      msg = (typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail || d)) || msg;
    } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buf = '';
  while (true) {
    let chunk;
    try {
      const r = await reader.read();
      if (r.done) break;
      chunk = r.value;
    } catch (e) {
      // 读取 SSE 流时连接中断
      throw new Error('网络连接中断，请重试。若原文较长，可尝试稍后重试或检查网络/代理设置。');
    }
    buf += decoder.decode(chunk, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      let ev;
      try { ev = JSON.parse(payload); } catch (e) { continue; }
      onEvent(ev);
    }
  }
}

// 在顶部插入"生成中"实时输出面板，返回 panelId
function showGenPanel(index, label) {
  const ws = $('workspace');
  const panelId = 'gen-' + index + '-' + Date.now();
  ws.insertAdjacentHTML('afterbegin', `
    <div class="card gen-panel" id="${panelId}">
      <div class="row">
        <span class="title">${label}</span>
        <span class="badge gen-badge" id="${panelId}-badge">生成中…</span>
        <span class="spacer"></span>
        <span class="meta" id="${panelId}-words"></span>
      </div>
      <div class="gen-output" id="${panelId}-out"></div>
    </div>`);
  return panelId;
}

// 流式生成单章：实时追加正文，完成后更新 state.novel
async function generateChapterStream(index, outEl, badgeEl, wordsEl) {
  const id = state.novel.id;
  let full = '';
  let wordCount = 0;
  let receivedAny = false;
  let timer = null;
  // 等待首个 delta 超过 90 秒（模型在思考/推理），提示用户
  const waitTimer = setTimeout(() => {
    if (!receivedAny && badgeEl) badgeEl.textContent = '模型思考中（推理模型可能较慢）…';
  }, 9000);
  try {
    await streamApi(`/api/novels/${id}/chapter/${index}/stream`, (ev) => {
      if (ev.type === 'delta') {
        if (!receivedAny) {
          receivedAny = true;
          clearTimeout(waitTimer);
          if (badgeEl) badgeEl.textContent = '生成中…';
        }
        full += ev.content;
        if (outEl) { outEl.textContent = full; outEl.scrollTop = outEl.scrollHeight; }
      } else if (ev.type === 'chapter_done') {
        wordCount = ev.word_count || 0;
        if (wordsEl) wordsEl.textContent = `约 ${wordCount} 字`;
        if (badgeEl) badgeEl.textContent = '正文完成，正在生成摘要…';
      } else if (ev.type === 'done') {
        state.novel = ev.novel;
      } else if (ev.type === 'error') {
        throw new Error(ev.message);
      }
    });
  } finally {
    clearTimeout(waitTimer);
  }
  if (!receivedAny) {
    throw new Error('模型未返回任何内容（可能被服务商拒绝或超时）。可尝试换模型或重新点击。');
  }
  if (wordCount === 0 && !full.trim()) {
    throw new Error('生成完成但内容为空。请重试或换模型。');
  }
  return full;
}

// 即兴模式：重新生成指定章节（走即兴接口，带写作指引；原章节内容不发给 AI）
async function improvRegenerateStream(index, instruction, outEl, badgeEl, wordsEl) {
  const id = state.novel.id;
  // 默认引用本章之前的已生成章节（摘要方式），与即兴写作页默认勾选行为一致
  const contextChapters = (state.novel.chapters || [])
    .filter(c => c.index < index && c.content)
    .map(c => ({ index: c.index, mode: 'summary' }));
  let full = '';
  let wordCount = 0;
  let receivedAny = false;
  const waitTimer = setTimeout(() => {
    if (!receivedAny && badgeEl) badgeEl.textContent = '模型思考中（推理模型可能较慢）…';
  }, 9000);
  try {
    await streamApi(`/api/novels/${id}/improv/stream`, (ev) => {
      if (ev.type === 'delta') {
        if (!receivedAny) {
          receivedAny = true;
          clearTimeout(waitTimer);
          if (badgeEl) badgeEl.textContent = '生成中…';
        }
        full += ev.content;
        if (outEl) { outEl.textContent = full; outEl.scrollTop = outEl.scrollHeight; }
      } else if (ev.type === 'chapter_done') {
        wordCount = ev.word_count || 0;
        if (wordsEl) wordsEl.textContent = `约 ${wordCount} 字`;
        if (badgeEl) badgeEl.textContent = '正文完成，正在生成摘要…';
      } else if (ev.type === 'done') {
        state.novel = ev.novel;
      } else if (ev.type === 'error') {
        throw new Error(ev.message);
      }
    }, { instruction, regenerate_index: index, context_chapters: contextChapters });
  } finally {
    clearTimeout(waitTimer);
  }
  if (!receivedAny) {
    throw new Error('模型未返回任何内容（可能被服务商拒绝或超时）。可尝试换模型或重新点击。');
  }
  if (wordCount === 0 && !full.trim()) {
    throw new Error('生成完成但内容为空。请重试或换模型。');
  }
  return full;
}

async function generateChapter(index) {
  const panelId = showGenPanel(index, `第 ${index} 章 生成中`);
  const out = $(panelId + '-out');
  const badge = $(panelId + '-badge');
  const words = $(panelId + '-words');
  try {
    await generateChapterStream(index, out, badge, words);
    $(panelId).remove();
    renderWorkspace();
    loadNovels();
    toast(`第 ${index} 章完成`, 'ok');
  } catch (e) {
    // 错误时保留面板，把内容改为错误提示，便于排查
    if (out) {
      out.textContent = '⚠️ ' + e.message;
      out.classList.add('gen-error');
    }
    if (badge) badge.textContent = '生成失败';
    toast(e.message, 'err');
    // 8 秒后自动关闭错误面板
    setTimeout(() => { try { $(panelId).remove(); } catch (e) {} }, 8000);
  }
}

async function generateAll() {
  const n = state.novel;
  const total = n.chapters.length;
  const start = n.chapters.filter(c => c.content).length;
  if (!confirm(`将依次生成全部 ${total} 章（已完成 ${start} 章），可能耗时较长。确定开始？`)) return;

  const ws = $('workspace');
  const progId = 'prog-' + Date.now();
  ws.insertAdjacentHTML('afterbegin', `
    <div class="card gen-panel" id="${progId}">
      <div>正在逐章生成… <span id="${progId}-txt"></span></div>
      <div class="progress-wrap"><div class="progress-bar" id="${progId}-bar"></div></div>
      <div class="gen-output" id="${progId}-out"></div>
    </div>`);
  const bar = $(progId + '-bar'), txt = $(progId + '-txt'), out = $(progId + '-out');

  for (let i = 1; i <= total; i++) {
    txt.textContent = `第 ${i} / ${total} 章`;
    bar.style.width = (i / total * 100) + '%';
    out.textContent = '';
    try {
      await generateChapterStream(i, out, null, null);
    } catch (e) {
      toast(`第 ${i} 章生成失败：${e.message}`, 'err');
      if (out) {
        out.textContent = `第 ${i} 章失败：${e.message}\n（已停止后续章节）`;
        out.classList.add('gen-error');
      }
      renderWorkspace();
      return;
    }
  }
  $(progId).remove();
  renderWorkspace();
  loadNovels();
  toast('全部章节生成完成', 'ok');
}

async function exportNovel(id, format) {
  try {
    const headers = {};
    if (authToken) headers['Authorization'] = 'Bearer ' + authToken;
    const fmt = format || 'md';
    const res = await fetch(`/api/novels/${id}/export?format=${fmt}`, { headers });
    if (res.status === 401) { handleUnauthorized(); return; }
    if (!res.ok) { toast('导出失败', 'err'); return; }
    const blob = await res.blob();
    // 从 Content-Disposition 解析文件名
    let fname = 'novel.' + fmt;
    const cd = res.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename\*=UTF-8''(.+)/) || cd.match(/filename="?([^";]+)"?/);
    if (m) { try { fname = decodeURIComponent(m[1]); } catch (e) { fname = m[1]; } }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = fname;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch (e) { toast('导出失败：' + e.message, 'err'); }
}

// 前端文本下载工具
function downloadText(filename, text) {
  const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ============ AI 请求日志 ============
let logPage = 1;  // 当前日志页码

async function loadLogs(page = 1) {
  try {
    const d = await api(`/api/logs?page=${page}&page_size=20`);
    logPage = d.page || 1;
    renderLogs(d);
  } catch (e) { toast(e.message, 'err'); }
}

function renderLogs(data) {
  const box = $('log-list');
  const logs = data.logs || [];
  const total = data.total || 0;
  const page = data.page || 1;
  const totalPages = data.total_pages || 1;

  if (!logs.length) {
    box.innerHTML = '<div class="card meta">暂无 AI 请求日志。生成大纲、章节或分析照片后会自动记录。</div>';
    return;
  }

  const listHtml = logs.map(l => {
    const t = new Date((l.created_at || 0) * 1000);
    const timeStr = t.toLocaleString('zh-CN', { hour12: false });
    // 优先显示语义化名称（如「生成章节」「生成摘要」），无则回退到类型
    const kindLabel = { 'chat': '文本', 'chat_stream': '流式', 'vision': '视觉' }[l.kind] || l.kind;
    const nameLabel = l.name || kindLabel;
    const statusBadge = l.status === 'ok'
      ? '<span class="badge">成功</span>'
      : '<span class="badge" style="background:var(--danger);color:#fff">失败</span>';
    const tokens = (l.prompt_tokens != null || l.completion_tokens != null)
      ? ` · tokens: ${l.prompt_tokens ?? '-'} / ${l.completion_tokens ?? '-'}` : '';
    const elapsed = l.elapsed != null ? ` · ${(l.elapsed * 1000).toFixed(0)}ms` : '';
    return `
      <div class="card">
        <div class="row">
          <span class="badge" style="background:var(--accent);color:#fff">${esc(nameLabel)}</span>
          ${statusBadge}
          <span class="title" style="font-size:14px">${esc(l.provider || '')} / ${esc(l.model || '')}</span>
          <span class="spacer"></span>
          <span class="meta">${esc(timeStr)}${esc(tokens)}${esc(elapsed)}</span>
        </div>
        ${l.error ? `<div class="meta" style="color:var(--danger)">错误：${esc(l.error)}</div>` : ''}
        <details class="log-detail">
          <summary>查看提示词</summary>
          <pre class="log-prompt">${esc(l.prompt || '')}</pre>
        </details>
      </div>`;
  }).join('');

  // 分页控件
  const pager = `
    <div class="pager">
      <button class="btn" ${page <= 1 ? 'disabled' : ''} onclick="loadLogs(${page - 1})">← 上一页</button>
      <span class="meta">第 ${page} / ${totalPages} 页 · 共 ${total} 条</span>
      <button class="btn" ${page >= totalPages ? 'disabled' : ''} onclick="loadLogs(${page + 1})">下一页 →</button>
    </div>`;

  box.innerHTML = listHtml + pager;
}

async function clearLogs() {
  if (!confirm('确定清空所有请求日志？此操作不可恢复。')) return;
  // 后端未提供删除接口，简单提示（可扩展）
  toast('当前版本不支持直接清空（数据保留供排查）', 'err');
}

// ============ 题材库 ============
async function loadGenres() {
  try {
    const d = await api('/api/genres');
    state.genres = d.genres || [];
    renderGenres();
    renderGenreSelect();
  } catch (e) { toast(e.message, 'err'); }
}

function renderGenres() {
  const box = $('genre-list');
  if (!box) return;
  if (!state.genres.length) {
    box.innerHTML = '<div class="card meta">暂无题材，点「＋ 添加题材」或「导入题材库」。</div>';
    return;
  }
  box.innerHTML = state.genres.map(g => `
    <div class="card">
      <div class="row">
        <span class="title">${esc(g.name)}</span>
        <span class="spacer"></span>
        <button class="btn" onclick="editGenre('${g.id}')">编辑</button>
        <button class="btn danger" onclick="deleteGenre('${g.id}')">删除</button>
      </div>
      ${g.description ? `<div class="meta">${esc(g.description)}</div>` : ''}
      ${g.style ? `<div class="meta"><b>风格：</b>${esc(g.style)}</div>` : ''}
      ${g.reference_text ? `<div class="meta"><b>参考文本：</b>${esc(g.reference_text.slice(0, 80))}${g.reference_text.length > 80 ? '…' : ''}</div>` : ''}
    </div>`).join('');
}

// 预置常用题材（供题材类型输入框下拉选择）
const PRESET_GENRES = [
  '玄幻', '奇幻', '都市', '言情', '悬疑', '推理', '科幻', '历史',
  '武侠', '古言', '青春', '职场', '军事', '体育', '游戏', '电竞',
  '末世', '无限流', '脑洞', '治愈', '甜宠', '虐恋', '轻小说', '灵异',
];

// 填充小说创作页的题材下拉 + 题材类型 datalist
function renderGenreSelect() {
  const sel = $('n-genre-select');
  if (sel) {
    const cur = sel.value;
    const opts = ['<option value="">不使用题材库</option>'];
    (state.genres || []).forEach(g => {
      opts.push(`<option value="${g.id}">${esc(g.name)}</option>`);
    });
    sel.innerHTML = opts.join('');
    sel.value = cur || '';
  }
  // 题材类型 datalist：预置题材 + 题材库题材
  const dl = $('genre-presets');
  if (dl) {
    const names = new Set(PRESET_GENRES);
    (state.genres || []).forEach(g => { if (g.name) names.add(g.name); });
    dl.innerHTML = Array.from(names).map(n => `<option value="${esc(n)}">`).join('');
  }
}

// 选择题材后自动填充 genre/style/reference
function applyGenreTemplate() {
  const sel = $('n-genre-select');
  if (!sel) return;
  const gid = sel.value;
  if (!gid) return;
  const g = (state.genres || []).find(x => x.id === gid);
  if (!g) return;
  // 题材库只填充「风格」「参考文本」，不影响独立的「题材类型」「故事背景」字段
  if (g.style && $('n-style')) $('n-style').value = g.style;
  if (g.reference_text && $('n-reference')) $('n-reference').value = g.reference_text;
  toast('已套用题材「' + g.name + '」的风格与参考文本', 'ok');
}

function showGenreForm() {
  state.editingGenreId = null;
  $('genre-form-title').textContent = '添加题材';
  ['g-name', 'g-style', 'g-reference', 'g-description'].forEach(i => $(i).value = '');
  $('genre-form').style.display = 'block';
  $('genre-import').style.display = 'none';
}

function editGenre(id) {
  const g = (state.genres || []).find(x => x.id === id);
  if (!g) return;
  state.editingGenreId = id;
  $('genre-form-title').textContent = '编辑题材';
  $('g-name').value = g.name || '';
  $('g-style').value = g.style || '';
  $('g-reference').value = g.reference_text || '';
  $('g-description').value = g.description || '';
  $('genre-form').style.display = 'block';
  $('genre-import').style.display = 'none';
}

function hideGenreForm() {
  $('genre-form').style.display = 'none';
  state.editingGenreId = null;
}

async function saveGenre() {
  const name = $('g-name').value.trim();
  if (!name) return toast('请填写题材名称', 'err');
  const body = {
    name,
    style: $('g-style').value.trim(),
    reference_text: $('g-reference').value.trim(),
    description: $('g-description').value.trim(),
  };
  try {
    if (state.editingGenreId) {
      await api('/api/genres/' + state.editingGenreId, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
    } else {
      await api('/api/genres', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
    }
    hideGenreForm();
    await loadGenres();
    toast('题材已保存', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

async function deleteGenre(id) {
  if (!confirm('确定删除该题材？')) return;
  try {
    await api('/api/genres/' + id, { method: 'DELETE' });
    await loadGenres();
    toast('题材已删除', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

function showGenreImport() {
  $('genre-import').style.display = 'block';
  $('genre-form').style.display = 'none';
}

function hideGenreImport() {
  $('genre-import').style.display = 'none';
}

async function importGenres() {
  const text = $('g-import-text').value.trim();
  if (!text) return toast('请粘贴 JSON 数据', 'err');
  let items;
  try {
    items = JSON.parse(text);
  } catch (e) {
    return toast('JSON 格式错误：' + e.message, 'err');
  }
  if (!Array.isArray(items)) {
    // 兼容对象包裹 {genres: [...]}
    items = items.genres || [];
  }
  if (!items.length) return toast('没有可导入的题材', 'err');
  try {
    const d = await api('/api/genres/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ genres: items }),
    });
    hideGenreImport();
    $('g-import-text').value = '';
    await loadGenres();
    toast(`成功导入 ${d.imported} 个题材`, 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// ============ 世界书 ============
let worldbooksState = { list: [], editingId: null, entryEditing: null };

async function loadWorldbooks() {
  try {
    const d = await api('/api/worldbooks');
    worldbooksState.list = d.worldbooks || [];
  } catch (e) { toast(e.message, 'err'); }
  renderWorldbooks();
}

// 渲染小说向导步骤1的「关联世界书」多选框
async function renderNovelWorldbookSelect() {
  const box = $('n-worldbooks');
  if (!box) return;
  // 确保世界书列表已加载
  if (!worldbooksState.list.length) {
    try {
      const d = await api('/api/worldbooks');
      worldbooksState.list = d.worldbooks || [];
    } catch (e) { /* 忽略 */ }
  }
  const list = worldbooksState.list;
  const selected = (state.novel && state.novel.worldbook_ids) || [];
  if (!list.length) {
    box.innerHTML = '<span class="meta">暂无世界书，可先到「世界书」页创建或导入。</span>';
    return;
  }
  box.innerHTML = list.map(wb => {
    const checked = selected.includes(wb.id);
    return `
    <label class="worldbook-select-item">
      <input type="checkbox" value="${esc(wb.id)}" ${checked ? 'checked' : ''} onchange="toggleNovelWorldbook('${esc(wb.id)}', this.checked)">
      <span class="worldbook-select-name">${esc(wb.name)}</span>
      <span class="meta">${(wb.entries || []).length} 条目</span>
    </label>`;
  }).join('');
}

// 勾选/取消勾选世界书（仅更新本地 state，随「保存基本信息」一起提交）
function toggleNovelWorldbook(wid, checked) {
  let ids = (state.novel && state.novel.worldbook_ids) ? state.novel.worldbook_ids.slice() : [];
  if (checked) {
    if (!ids.includes(wid)) ids.push(wid);
  } else {
    ids = ids.filter(x => x !== wid);
  }
  if (state.novel) state.novel.worldbook_ids = ids;
}

function renderWorldbooks() {
  const box = $('worldbook-list');
  if (!box) return;
  const list = worldbooksState.list;
  if (!list.length) {
    box.innerHTML = '<div class="card meta">暂无世界书，点击右上角「新建世界书」或「导入世界书」开始。</div>';
    return;
  }
  box.innerHTML = list.map(wb => {
    const entries = wb.entries || [];
    const enabledCount = entries.filter(e => e.enabled !== false).length;
    return `
    <div class="card worldbook-item">
      <div class="row">
        <span class="title">${esc(wb.name)}</span>
        <span class="badge">${entries.length} 条目</span>
        ${enabledCount !== entries.length ? `<span class="badge">启用 ${enabledCount}</span>` : ''}
        <span class="spacer"></span>
        <button class="btn" onclick="toggleWorldbookEntries('${wb.id}')">条目</button>
        <button class="btn" onclick="startEditWorldbook('${wb.id}')">编辑</button>
        <button class="btn danger" onclick="deleteWorldbook('${wb.id}')">删除</button>
      </div>
      ${wb.description ? `<div class="meta">${esc(wb.description)}</div>` : ''}
      <div id="wb-entries-${wb.id}" style="display:none"></div>
    </div>`;
  }).join('');
}

// 展开/收起世界书条目
function toggleWorldbookEntries(wid) {
  const wrap = $('wb-entries-' + wid);
  if (!wrap) return;
  const wb = worldbooksState.list.find(x => x.id === wid);
  if (!wb) return;
  if (wrap.style.display === 'none') {
    wrap.style.display = 'block';
    const entries = wb.entries || [];
    if (!entries.length) {
      wrap.innerHTML = '<div class="meta" style="margin-top:8px">该世界书暂无条目，可通过「导入」添加。</div>';
      return;
    }
    wrap.innerHTML = `
      <div class="worldbook-entries">
        ${entries.map((e, i) => `
          <div class="worldbook-entry ${e.enabled === false ? 'disabled' : ''}">
            <div class="row">
              <span class="worldbook-entry-key">${esc((e.key || []).join(' / ') || '（无关键词）')}</span>
              ${e.comment ? `<span class="meta">${esc(e.comment)}</span>` : ''}
              ${e.constant ? '<span class="badge">恒常</span>' : ''}
              ${e.enabled === false ? '<span class="badge">已禁用</span>' : ''}
              <span class="spacer"></span>
              <button class="dialog-act-btn" onclick="editWorldbookEntry('${wb.id}', ${i})">编辑</button>
              <button class="dialog-act-btn danger" onclick="deleteWorldbookEntry('${wb.id}', ${i})">删除</button>
            </div>
            <div class="worldbook-entry-content">${esc(e.content || '')}</div>
          </div>`).join('')}
      </div>`;
  } else {
    wrap.style.display = 'none';
  }
}

// 新建世界书
function showWorldbookForm() {
  worldbooksState.editingId = null;
  $('worldbook-form-title').textContent = '新建世界书';
  $('wb-name').value = '';
  $('wb-description').value = '';
  $('worldbook-form').style.display = 'block';
}

function hideWorldbookForm() {
  $('worldbook-form').style.display = 'none';
}

function startEditWorldbook(wid) {
  const wb = worldbooksState.list.find(x => x.id === wid);
  if (!wb) return;
  worldbooksState.editingId = wid;
  $('worldbook-form-title').textContent = '编辑世界书';
  $('wb-name').value = wb.name || '';
  $('wb-description').value = wb.description || '';
  $('worldbook-form').style.display = 'block';
  $('worldbook-form').scrollIntoView({ behavior: 'smooth' });
}

async function saveWorldbook() {
  const name = $('wb-name').value.trim();
  if (!name) return toast('请填写世界书名称', 'err');
  const body = { name, description: $('wb-description').value.trim() };
  try {
    if (worldbooksState.editingId) {
      await api('/api/worldbooks/' + worldbooksState.editingId, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      toast('世界书已更新', 'ok');
    } else {
      await api('/api/worldbooks', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      toast('世界书已创建', 'ok');
    }
    worldbooksState.editingId = null;
    hideWorldbookForm();
    await loadWorldbooks();
  } catch (e) { toast(e.message, 'err'); }
}

async function deleteWorldbook(wid) {
  if (!confirm('确定删除该世界书？')) return;
  try {
    await api('/api/worldbooks/' + wid, { method: 'DELETE' });
    await loadWorldbooks();
    toast('已删除', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// 导入世界书
function showWorldbookImport() {
  $('worldbook-import').style.display = 'block';
}

function hideWorldbookImport() {
  $('worldbook-import').style.display = 'none';
}

function onWorldbookFileSelected(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    $('wb-import-text').value = reader.result;
    // 若未填名称，用文件名作为世界书名称
    if (!$('wb-import-name').value.trim()) {
      $('wb-import-name').value = file.name.replace(/\.json$/i, '');
    }
  };
  reader.readAsText(file, 'utf-8');
}

async function importWorldbook() {
  const text = $('wb-import-text').value.trim();
  if (!text) return toast('请粘贴 JSON 或选择文件', 'err');
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    return toast('JSON 格式错误：' + e.message, 'err');
  }
  try {
    const d = await api('/api/worldbooks/import', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: $('wb-import-name').value.trim(),
        data: data,
      }),
    });
    hideWorldbookImport();
    $('wb-import-text').value = '';
    $('wb-import-name').value = '';
    $('wb-import-file').value = '';
    await loadWorldbooks();
    toast(`成功导入世界书，共 ${d.imported} 个条目`, 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// 编辑/删除单条世界书条目（简化：弹窗编辑）
function editWorldbookEntry(wid, idx) {
  const wb = worldbooksState.list.find(x => x.id === wid);
  if (!wb) return;
  const entry = wb.entries[idx];
  if (!entry) return;
  const keys = (entry.key || []).join(', ');
  const comment = entry.comment || '';
  const content = entry.content || '';
  const enabled = entry.enabled !== false;
  const constant = !!entry.constant;
  const html = `
    <div class="card" style="margin-top:10px">
      <span class="title">编辑条目</span>
      <div class="form-grid">
        <label>触发关键词（逗号分隔）
          <input id="we-key" value="${esc(keys)}">
        </label>
        <label>备注
          <input id="we-comment" value="${esc(comment)}">
        </label>
      </div>
      <label>条目内容
        <textarea id="we-content" rows="5">${esc(content)}</textarea>
      </label>
      <div class="row" style="margin-top:8px">
        <label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="we-enabled" ${enabled ? 'checked' : ''}> 启用</label>
        <label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="we-constant" ${constant ? 'checked' : ''}> 恒常注入</label>
      </div>
      <div style="margin-top:10px">
        <button class="btn primary" onclick="saveWorldbookEntry('${wid}', ${idx})">保存</button>
        <button class="btn" onclick="toggleWorldbookEntries('${wid}'); toggleWorldbookEntries('${wid}')">取消</button>
      </div>
    </div>`;
  const wrap = $('wb-entries-' + wid);
  if (wrap) { wrap.innerHTML = html; wrap.style.display = 'block'; }
}

async function saveWorldbookEntry(wid, idx) {
  const wb = worldbooksState.list.find(x => x.id === wid);
  if (!wb) return;
  const entry = wb.entries[idx];
  if (!entry) return;
  const keys = $('we-key').value.split(',').map(s => s.trim()).filter(Boolean);
  entry.key = keys;
  entry.comment = $('we-comment').value.trim();
  entry.content = $('we-content').value;
  entry.enabled = $('we-enabled').checked;
  entry.constant = $('we-constant').checked;
  try {
    await api('/api/worldbooks/' + wid, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entries: wb.entries }),
    });
    toast('条目已保存', 'ok');
    await loadWorldbooks();
  } catch (e) { toast(e.message, 'err'); }
}

async function deleteWorldbookEntry(wid, idx) {
  const wb = worldbooksState.list.find(x => x.id === wid);
  if (!wb) return;
  if (!confirm('确定删除该条目？')) return;
  wb.entries.splice(idx, 1);
  try {
    await api('/api/worldbooks/' + wid, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entries: wb.entries }),
    });
    toast('条目已删除', 'ok');
    await loadWorldbooks();
  } catch (e) { toast(e.message, 'err'); }
}

// ============ 大纲编辑 ============
let outlineEditing = false;

// 切换大纲编辑模式
function toggleOutlineEdit() {
  outlineEditing = !outlineEditing;
  renderWorkspace();
}

// 收集大纲编辑表单内容并保存
async function saveOutline() {
  const n = state.novel;
  if (!n) return;
  const summary = ($('out-edit-summary') || {}).value || '';
  const worldbuilding = ($('out-edit-world') || {}).value || '';
  const chapters = [];
  for (const c of (n.chapters || [])) {
    const title = ($('out-edit-title-' + c.index) || {}).value || '';
    const cs = ($('out-edit-sum-' + c.index) || {}).value || '';
    chapters.push({ index: c.index, title, summary: cs });
  }
  try {
    const d = await api('/api/novels/' + n.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ summary, worldbuilding, chapters }),
    });
    state.novel = d.novel;
    outlineEditing = false;
    renderWorkspace();
    toast('大纲已保存', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// ============ 改写 / 续写模式（导入已有小说） ============
let rewriteGenerating = false;   // 改写中（防止重复提交）
let continueGenerating = false;  // 续写中

// 触发文件选择导入原文
function pickSourceFile() {
  const f = $('n-source-file');
  if (f) f.click();
}

// 读取选中文件内容到原文输入框
function onSourceFilePicked(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const text = String(reader.result || '');
    const ta = $('n-source');
    if (ta) ta.value = text;
    const info = $('n-source-info');
    if (info) info.textContent = `已导入：${file.name}（${text.length} 字）`;
    toast('原文已导入', 'ok');
    maybeAutoAnalyze();  // 清除旧的拆解结果
  };
  reader.onerror = () => toast('文件读取失败', 'err');
  reader.readAsText(file, 'utf-8');
  input.value = '';  // 允许重复选择同一文件
}

// ===== 改写模式 =====
async function openRewritePage(id) {
  try {
    const d = await api('/api/novels/' + id);
    state.novel = d.novel;
    currentNovelId = id;
    $('rewrite-title').textContent = '《' + (state.novel.title || '未命名') + '》 改写创作';
    const editLink = $('rewrite-edit-link');
    if (editLink) editLink.setAttribute('href', '#/novels/' + id + '/edit');
    $('rewrite-instruction').value = state.novel.task_instruction || '';
    renderRewrite();
    window.scrollTo({ top: 0 });
  } catch (e) {
    toast(e.message, 'err');
    nav('#/novels');
  }
}

function renderRewrite() {
  const n = state.novel;
  const chapters = n.chapters || [];
  const doneCount = chapters.filter(c => c.summary).length;
  const hint = $('rewrite-chapter-hint');
  if (hint) hint.textContent = chapters.length ? `共 ${chapters.length} 段 · 已改写 ${doneCount} 段` : '';
  const readBtn = $('rewrite-read-btn');
  if (readBtn) readBtn.style.display = doneCount ? '' : 'none';

  const body = $('rewrite-body');
  if (!chapters.length) {
    body.innerHTML = '<div class="card meta">尚未导入原文。点「编辑设定」，在基本信息中粘贴或从文件导入已有小说原文。</div>';
    return;
  }
  body.innerHTML = chapters.map(c => {
    const rewritten = !!c.summary;
    return `
    <div class="card rewrite-chapter-card" id="rewrite-card-${c.index}">
      <div class="row">
        <span class="title">${esc(c.title || ('第' + c.index + '段'))}</span>
        ${rewritten ? '<span class="badge">已改写</span>' : '<span class="meta">未改写</span>'}
        <span class="meta">${c.word_count ? '约 ' + c.word_count + ' 字' : ''}</span>
        <span class="spacer"></span>
        <button class="btn" onclick="nav('#/novels/${n.id}/chapter/${c.index}')">查看/编辑</button>
        <button class="btn primary" id="rewrite-btn-${c.index}" onclick="rewriteChapter(${c.index})">${rewritten ? '重新改写' : '改写本章'}</button>
      </div>
      <div class="chapter-content" style="max-height:240px;overflow:auto">${esc(c.content || '')}</div>
    </div>`;
  }).join('');
}

async function saveRewriteInstruction() {
  const instr = $('rewrite-instruction').value.trim();
  try {
    const d = await api('/api/novels/' + state.novel.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_instruction: instr }),
    });
    state.novel = d.novel;
    toast('改写要求已保存', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

async function rewriteChapter(index) {
  if (rewriteGenerating) return;
  rewriteGenerating = true;
  const card = $('rewrite-card-' + index);
  const btn = $('rewrite-btn-' + index);
  if (btn) { btn.disabled = true; btn.textContent = '改写中…'; }

  let out = null, badge = null;
  if (card) {
    card.insertAdjacentHTML('beforeend',
      `<div class="gen-panel"><span class="badge gen-badge" id="rewrite-badge-${index}">生成中…</span><div class="gen-output" id="rewrite-out-${index}"></div></div>`);
    out = $('rewrite-out-' + index);
    badge = $('rewrite-badge-' + index);
  }

  let full = '';
  let received = false;
  const waitTimer = setTimeout(() => { if (!received && badge) badge.textContent = '模型思考中…'; }, 9000);

  try {
    await streamApi(`/api/novels/${state.novel.id}/rewrite/stream`, (ev) => {
      if (ev.type === 'delta') {
        if (!received) { received = true; clearTimeout(waitTimer); if (badge) badge.textContent = '生成中…'; }
        full += ev.content;
        if (out) { out.textContent = full; out.scrollTop = out.scrollHeight; }
      } else if (ev.type === 'chapter_done') {
        if (badge) badge.textContent = '正文完成，生成摘要…';
      } else if (ev.type === 'done') {
        state.novel = ev.novel;
      } else if (ev.type === 'error') {
        throw new Error(ev.message);
      }
    }, { index });
  } catch (e) {
    toast(e.message, 'err');
  } finally {
    clearTimeout(waitTimer);
    rewriteGenerating = false;
  }

  if (!received) toast('模型未返回内容，请重试', 'err');
  else toast('本章改写完成', 'ok');
  renderRewrite();
}

async function rewriteAll() {
  const chapters = (state.novel.chapters || []).filter(c => !c.summary);
  if (!chapters.length) { toast('所有章节均已改写', 'ok'); return; }
  if (!confirm(`将依次改写 ${chapters.length} 个未改写章节，可能耗时较长，是否继续？`)) return;
  for (const c of chapters) {
    await rewriteChapter(c.index);
  }
  toast('全部改写完成', 'ok');
}

async function resplitSource() {
  if (!confirm('按当前原文重新切分章节，将丢弃已有的改写结果，确定？')) return;
  try {
    const d = await api('/api/novels/' + state.novel.id + '/resplit', { method: 'POST' });
    state.novel = d.novel;
    renderRewrite();
    toast('已按原文重新切分', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// ===== 续写模式 =====
async function openContinuePage(id) {
  try {
    const d = await api('/api/novels/' + id);
    state.novel = d.novel;
    currentNovelId = id;
    $('continue-title').textContent = '《' + (state.novel.title || '未命名') + '》 续写创作';
    const editLink = $('continue-edit-link');
    if (editLink) editLink.setAttribute('href', '#/novels/' + id + '/edit');
    renderContinue();
    window.scrollTo({ top: 0 });
  } catch (e) {
    toast(e.message, 'err');
    nav('#/novels');
  }
}

function renderContinue() {
  const n = state.novel;
  const chapters = (n.chapters || []).filter(c => c.content);
  const source = n.source_text || '';

  const hint = $('continue-chapter-hint');
  if (hint) hint.textContent = chapters.length ? `已续写 ${chapters.length} 章，接下来写第 ${chapters.length + 1} 章` : '接下来写第 1 章';
  const readBtn = $('continue-read-btn');
  if (readBtn) readBtn.style.display = chapters.length ? '' : 'none';

  const srcBox = $('continue-source-box');
  if (srcBox) {
    if (source) {
      srcBox.style.display = 'block';
      const tail = source.length > 600 ? '……' + source.slice(-600) : source;
      srcBox.innerHTML = `<div class="row"><span class="title">📄 已导入原文（结尾摘录）</span><span class="spacer"></span><span class="meta">共 ${source.length} 字</span></div><div class="chapter-content" style="max-height:200px;overflow:auto">${esc(tail)}</div>`;
    } else {
      srcBox.style.display = 'none';
    }
  }

  const body = $('continue-body');
  if (!chapters.length) {
    body.innerHTML = '<div class="card meta">还没有续写内容。在上方填写本章续写要求，点击「续写下一章」开始。</div>';
    return;
  }
  body.innerHTML = chapters.map(c => `
    <div class="card continue-chapter-card">
      <div class="row">
        <span class="title">${esc(c.title || ('第' + c.index + '章'))}</span>
        <span class="meta">约 ${c.word_count || ''} 字</span>
        <span class="spacer"></span>
        <button class="btn" onclick="nav('#/novels/${n.id}/chapter/${c.index}')">查看/编辑正文</button>
      </div>
      ${c.instruction ? `<div class="improv-instruction-hint">📝 本章续写要求：${esc(c.instruction)}</div>` : ''}
      <div class="chapter-content" style="max-height:300px;overflow:auto">${esc(c.content)}</div>
    </div>`).join('');
}

async function generateContinueChapter() {
  if (continueGenerating) return;
  const instruction = $('continue-instruction').value.trim();
  if (!instruction) return toast('请填写本章续写要求', 'err');
  if (!(state.novel.source_text || '').trim()) return toast('尚未导入原文，请先到「编辑设定」导入', 'err');

  continueGenerating = true;
  const btn = $('continue-gen-btn');
  btn.disabled = true;
  btn.textContent = '生成中…';
  $('continue-instruction').disabled = true;

  const body = $('continue-body');
  const panelId = 'continue-gen-' + Date.now();
  body.insertAdjacentHTML('afterbegin', `
    <div class="card gen-panel" id="${panelId}">
      <div class="row">
        <span class="title">新章节生成中</span>
        <span class="badge gen-badge" id="${panelId}-badge">生成中…</span>
        <span class="spacer"></span>
        <span class="meta" id="${panelId}-words"></span>
      </div>
      <div class="gen-output" id="${panelId}-out"></div>
    </div>`);
  const out = $(panelId + '-out');
  const badge = $(panelId + '-badge');
  const wordsEl = $(panelId + '-words');

  let full = '';
  let received = false;
  const waitTimer = setTimeout(() => { if (!received && badge) badge.textContent = '模型思考中…'; }, 9000);

  try {
    await streamApi(`/api/novels/${state.novel.id}/continue/stream`, (ev) => {
      if (ev.type === 'delta') {
        if (!received) { received = true; clearTimeout(waitTimer); if (badge) badge.textContent = '生成中…'; }
        full += ev.content;
        if (out) { out.textContent = full; out.scrollTop = out.scrollHeight; }
      } else if (ev.type === 'chapter_done') {
        if (wordsEl) wordsEl.textContent = `约 ${ev.word_count || 0} 字`;
        if (badge) badge.textContent = '正文完成，生成摘要…';
      } else if (ev.type === 'done') {
        state.novel = ev.novel;
      } else if (ev.type === 'error') {
        throw new Error(ev.message);
      }
    }, { instruction });
  } catch (e) {
    toast(e.message, 'err');
    $(panelId).remove();
    return;
  } finally {
    clearTimeout(waitTimer);
    continueGenerating = false;
    btn.disabled = false;
    btn.textContent = '续写下一章';
    $('continue-instruction').disabled = false;
  }

  if (!received) {
    toast('模型未返回内容，请重试', 'err');
    $(panelId).remove();
    return;
  }

  $(panelId).remove();
  $('continue-instruction').value = '';
  renderContinue();
  toast('本章续写完成', 'ok');
}

// ===== 原著结构化拆解（续写模式） =====
let editorAnalyzing = false;   // 编辑页自动拆解中

// 模型偶尔把字段输出成数组/对象（提示词要求字符串），归一化为可读文本
function profileVal(v) {
  if (v == null) return '';
  if (Array.isArray(v)) {
    return v.map(x => (x && typeof x === 'object') ? JSON.stringify(x) : String(x ?? ''))
      .map(s => s.trim()).filter(Boolean).join('；');
  }
  if (typeof v === 'object') {
    return Object.entries(v)
      .map(([k, x]) => `${k}：${(x && typeof x === 'object') ? JSON.stringify(x) : x}`)
      .filter(Boolean).join('；');
  }
  return String(v);
}

// 生成档案主体 HTML（人物/世界观/主线/摘要），供编辑页与续写页共用
function profileHTML(profile) {
  const chars = profile.characters || [];
  const ws = profile.world_setting || {};
  const mf = profile.main_frame || {};
  const sm = profile.summary || {};

  const charCards = chars.length ? `
    <h4 class="profile-h4">👥 人物档案（${chars.length}）</h4>
    <div class="profile-char-grid">${chars.map(c => `
      <div class="card profile-char">
        <div class="row"><span class="title">👤 ${esc(c.name || '未命名')}</span></div>
        ${profileVal(c.core_personality) ? `<div class="meta"><b>核心性格</b>：${esc(profileVal(c.core_personality))}</div>` : ''}
        ${profileVal(c.speaking_style) ? `<div class="meta"><b>说话风格</b>：${esc(profileVal(c.speaking_style))}</div>` : ''}
        ${profileVal(c.key_history) ? `<div class="meta"><b>重大经历</b>：${esc(profileVal(c.key_history))}</div>` : ''}
        ${profileVal(c.relationship) ? `<div class="meta"><b>人物关系</b>：${esc(profileVal(c.relationship))}</div>` : ''}
        ${profileVal(c.current_state) ? `<div class="meta"><b>当前状态</b>：${esc(profileVal(c.current_state))}</div>` : ''}
        ${profileVal(c.taboo) ? `<div class="meta"><b>🚫 行为禁忌</b>：${esc(profileVal(c.taboo))}</div>` : ''}
      </div>`).join('')}</div>` : '';

  const wsRows = [
    ['🌍 世界规则', profileVal(ws.world_rules)],
    ['🗺️ 重要地域', profileVal(ws.geography)],
    ['⚔️ 各大势力', profileVal(ws.forces)],
    ['📖 专有名词', profileVal(ws.noun_glossary)],
  ].filter(x => x[1]).map(x => `<div class="meta"><b>${x[0]}</b>：${esc(x[1])}</div>`).join('');
  const wsCard = wsRows ? `<h4 class="profile-h4">🌐 世界观设定</h4><div class="card profile-block">${wsRows}</div>` : '';

  const fg = Array.isArray(mf.foreshadowing_list) ? mf.foreshadowing_list : [];
  const fgList = fg.length ? `<ul class="profile-list">${fg.map(x => `<li>${esc(profileVal(x))}</li>`).join('')}</ul>` : '';
  const mfRows = [
    ['🎯 核心主题', profileVal(mf.core_theme)],
    ['🏁 主角长期目标', profileVal(mf.protagonist_goal)],
    ['💥 核心矛盾', profileVal(mf.main_conflict)],
    ['🎭 文风基调', profileVal(mf.story_tone)],
  ].filter(x => x[1]).map(x => `<div class="meta"><b>${x[0]}</b>：${esc(x[1])}</div>`).join('');
  const mfCard = (mfRows || fgList) ? `
    <h4 class="profile-h4">🧭 主线框架</h4>
    <div class="card profile-block">${mfRows}${fg.length ? `<div class="meta"><b>📌 待回收伏笔</b></div>${fgList}` : ''}</div>` : '';

  const chSummaries = Array.isArray(sm.chapter_summaries) ? sm.chapter_summaries : [];
  const chList = chSummaries.length ? `
    <h4 class="profile-h4">📑 章节脉络（${chSummaries.length}）</h4>
    <div class="card profile-block"><div class="profile-ch-grid">${chSummaries.map(cs => `
      <div class="profile-ch"><span class="badge">${esc(profileVal(cs.chapter))}</span><span class="meta">${esc(profileVal(cs.brief))}</span></div>`).join('')}</div></div>` : '';

  const smCard = (profileVal(sm.full_outline) ? `<h4 class="profile-h4">📜 全书脉络摘要</h4><div class="card profile-block"><div class="chapter-content">${esc(profileVal(sm.full_outline))}</div></div>` : '') + chList;

  return charCards + wsCard + mfCard + smCard;
}

// 无状态拆解：调 /api/analyze-source，返回 profile dict
async function analyzeSourceText(source) {
  let profile = null;
  let err = null;
  await streamApi('/api/analyze-source', (ev) => {
    if (ev.type === 'profile') profile = ev.profile;
    else if (ev.type === 'error') err = new Error(ev.message);
    else if (ev.type === 'progress') {
      const sub = $('loading-sub');
      if (sub && ev.message) sub.textContent = ev.message;
      const wp = $('wizard-analyze-progress');
      if (wp && ev.message) wp.textContent = ev.message;
    }
  }, { source_text: source, text_model_id: ($('n-model') ? $('n-model').value : '') });
  if (err) throw err;
  if (!profile) throw new Error('未收到拆解结果，请重试');
  return profile;
}

// 编辑页：续写模式下原文变化时清除内存中的旧拆解结果（档案展示与重新拆解在第二步进行）
function maybeAutoAnalyze() {
  const mode = $('n-mode') ? $('n-mode').value : '';
  if (mode !== 'continue') { state.novelProfile = null; state.novelProfileSource = ''; return; }
  const source = ($('n-source').value || '').trim();
  if (!source) {
    if (state.novelProfile || state.novelProfileSource) {
      state.novelProfile = null;
      state.novelProfileSource = '';
    }
    return;
  }
  if (state.novelProfileSource && state.novelProfileSource !== source) {
    state.novelProfile = null;
    state.novelProfileSource = '';
  }
}

// 编辑页向导第 2 步（AI 原著拆解）内容渲染：
// 未拆解 → 开始按钮；已拆解 → 完整档案（人物/世界观/主线/摘要）+ 重新拆解按钮
function renderWizardAnalyzeBox() {
  const box = $('wizard-analyze-box');
  if (!box || editorAnalyzing) return;
  const profile = state.novelProfile;
  if (profile && Object.keys(profile).length) {
    box.innerHTML = `
      <div class="row" style="margin-bottom:10px">
        <span class="badge">✅ 已拆解</span>
        <span class="spacer"></span>
        <button class="btn" onclick="analyzeInWizard()">🔄 重新拆解</button>
      </div>
      ${profileHTML(profile)}`;
  } else {
    box.innerHTML = '<button class="btn primary" id="wizard-analyze-btn" onclick="analyzeInWizard()">🧠 开始拆解原著</button>';
  }
}

// 编辑页向导：在第二步手动触发原著拆解
async function analyzeInWizard() {
  const source = ($('n-source').value || '').trim();
  if (!source) return toast('请先在第一步导入原文', 'err');
  if (editorAnalyzing) return;
  editorAnalyzing = true;
  const box = $('wizard-analyze-box');
  if (box) box.innerHTML = '<div class="meta" id="wizard-analyze-progress" style="margin-top:10px">AI 正在通读全文，提取人物档案、世界观、主线框架与伏笔…</div>';
  try {
    state.novelProfileSource = source;
    state.novelProfile = await analyzeSourceText(source);
    // 已有小说：立即持久化档案，避免刷新/跳转后丢失（新建小说在首次保存时写入）
    if (state.novel && state.novel.id) {
      try {
        const d = await api('/api/novels/' + state.novel.id, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ structured_profile: JSON.stringify(state.novelProfile) }),
        });
        state.novel = d.novel;
      } catch (e) {
        toast('档案已生成，但自动保存失败：' + e.message + '（请点击「保存基本信息」手动保存）', 'err');
      }
    }
    toast('原著拆解完成', 'ok');
  } catch (e) {
    toast(e.message, 'err');
    state.novelProfile = null;
    state.novelProfileSource = '';
  } finally {
    editorAnalyzing = false;
    renderWizardAnalyzeBox();
  }
}

// 角色设定步骤顶部展示 AI 拆解出的前 5 个角色
function renderAnalyzedCharacters() {
  const box = $('analyzed-chars-box');
  if (!box) return;
  const mode = $('n-mode') ? $('n-mode').value : '';
  const profile = state.novelProfile;
  if (mode !== 'continue' || !profile || !profile.characters || !profile.characters.length) {
    box.innerHTML = '';
    return;
  }
  const top = profile.characters.slice(0, 5);
  box.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="row"><span class="title">🧠 AI 拆解主要角色（前 ${top.length} 位）</span></div>
      <div class="profile-char-grid" style="margin-top:10px">
        ${top.map(c => `
          <div class="card profile-char">
            <div class="row"><span class="title">👤 ${esc(c.name || '未命名')}</span></div>
            ${profileVal(c.core_personality) ? `<div class="meta"><b>核心性格</b>：${esc(profileVal(c.core_personality))}</div>` : ''}
            ${profileVal(c.speaking_style) ? `<div class="meta"><b>说话风格</b>：${esc(profileVal(c.speaking_style))}</div>` : ''}
            ${profileVal(c.relationship) ? `<div class="meta"><b>人物关系</b>：${esc(profileVal(c.relationship))}</div>` : ''}
            ${profileVal(c.current_state) ? `<div class="meta"><b>当前状态</b>：${esc(profileVal(c.current_state))}</div>` : ''}
          </div>`).join('')}
      </div>
    </div>`;
}

// ============ 初始化 ============
(async function init() {
  // 加载版本号（公开接口，无需登录）
  try {
    const v = await fetch('/api/version').then(r => r.json());
    const el = $('app-version');
    if (el) el.textContent = v.version;
  } catch (_) {}

  // 登录表单 Enter 键支持
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      if (e.target.id === 'login-password' || e.target.id === 'login-username') doLogin();
      else if (e.target.id === 'reg-password' || e.target.id === 'reg-password2' || e.target.id === 'reg-username') doRegister();
    }
  });

  // 未登录：直接进入登录页，不加载数据
  if (!authToken) {
    await router();
    return;
  }
  try {
    // 恢复当前用户信息
    const me = await api('/api/auth/me');
    currentUser = me;
    updateUserUI();
    await loadSettings();
    await loadProviders();
    await loadAllCharacters();
    await loadGenres();
    await router();
  } catch (e) {
    if (authToken) {
      toast('初始化失败：' + e.message, 'err');
    }
  }
})();
