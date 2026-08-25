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
// 进入登录页：判断是首次设置密码还是常规登录
async function prepareLogin() {
  try {
    const res = await fetch('/api/auth/status');
    const d = await res.json();
    const hint = $('login-hint');
    const btn = $('login-btn');
    if (d.has_password) {
      if (hint) hint.textContent = '请输入访问密码';
      if (btn) btn.textContent = '登录';
    } else {
      if (hint) hint.textContent = '首次使用，请设置访问密码';
      if (btn) btn.textContent = '设置密码并进入';
    }
    const pwd = $('login-password');
    if (pwd) pwd.value = '';
  } catch (e) {
    // 忽略，保持默认提示
  }
}

async function doLogin() {
  const pwd = ($('login-password') || {}).value || '';
  if (!pwd) { toast('请输入密码', 'err'); return; }
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pwd }),
    });
    const d = await res.json();
    if (!res.ok) {
      toast(d.detail || '登录失败', 'err');
      return;
    }
    authToken = d.token;
    localStorage.setItem('novel_token', authToken);
    toast(d.first_setup ? '密码已设置' : '登录成功', 'ok');
    // 登录成功后加载基础数据，再进入主页面
    try {
      await loadSettings();
      await loadProviders();
      await loadCharacters();
      await loadGenres();
    } catch (e) { /* 忽略，路由加载时还会再触发 */ }
    location.hash = '#/novels';
    await router();
  } catch (e) { toast('登录失败：' + e.message, 'err'); }
}

function logout() {
  fetch('/api/auth/logout', {
    method: 'POST',
    headers: { 'Authorization': 'Bearer ' + authToken },
  }).catch(() => {});
  authToken = '';
  localStorage.removeItem('novel_token');
  location.hash = '#/login';
  showView('login');
  prepareLogin();
}

function handleUnauthorized() {
  authToken = '';
  localStorage.removeItem('novel_token');
  location.hash = '#/login';
  showView('login');
  prepareLogin();
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
const VIEWS = ['login', 'providers', 'genres', 'worldbooks', 'novels', 'trash', 'editor', 'generate', 'chapter', 'reader', 'improv', 'dialog', 'logs'];

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
  const logoutBtn = $('btn-logout');
  const providersBtn = $('btn-providers');
  if (tabs) tabs.style.display = isLogin ? 'none' : '';
  if (logoutBtn) logoutBtn.style.display = isLogin ? 'none' : '';
  if (providersBtn) providersBtn.style.display = isLogin ? 'none' : '';
  // 顶部标签高亮（providers/配置页 与 login 不点亮任何标签）
  document.querySelectorAll('.tab').forEach(b => {
    const tab = b.dataset.tab;
    let active = false;
    if (name === 'genres' && tab === 'genres') active = true;
    else if (name === 'worldbooks' && tab === 'worldbooks') active = true;
    else if (name === 'logs' && tab === 'logs') active = true;
    else if (name !== 'genres' && name !== 'worldbooks' && name !== 'logs' && name !== 'login' && name !== 'providers' && tab === 'novels') active = true;
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

  if (section === 'genres') {
    showView('genres');
    return;
  }

  if (section === 'worldbooks') {
    showView('worldbooks');
    return;
  }

  if (section === 'logs') {
    showView('logs');
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

// ================= 角色设定（小说创作步骤 2） =================
async function loadCharacters() {
  const d = await api('/api/characters');
  state.characters = d.characters;
  if (state.wizardStep === 3) renderCharacters();
}

function currentNovelCharacters() {
  const ids = (state.novel && state.novel.character_ids) || [];
  return state.characters.filter(c => ids.includes(c.id));
}

function renderCharacters() {
  const box = $('character-list');
  const chars = currentNovelCharacters();
  box.innerHTML = chars.length
    ? chars.map(c => `
      <div class="card" id="char-${c.id}">
        <div class="row">
          ${c.photo_path ? `<img class="avatar" src="/${esc(c.photo_path)}" alt="">` : '<div class="avatar"></div>'}
          <input style="font-weight:600" id="char-name-${c.id}" value="${esc(c.name)}" placeholder="角色姓名" oninput="markCharDirty('${c.id}')">
          <span class="spacer"></span>
          <button class="btn" onclick="uploadCharPhoto('${c.id}')">上传/更换照片并分析</button>
          <button class="btn danger" onclick="deleteCharacter('${c.id}')">移除</button>
        </div>
        <div class="char-detail">
          <div class="kv"><span class="k">外貌</span><textarea id="char-appearance-${c.id}" rows="3" oninput="markCharDirty('${c.id}')">${esc(c.appearance)}</textarea></div>
          <div class="kv"><span class="k">性格</span><textarea id="char-personality-${c.id}" rows="3" oninput="markCharDirty('${c.id}')">${esc(c.personality)}</textarea></div>
          <div class="kv"><span class="k">背景</span><textarea id="char-background-${c.id}" rows="3" oninput="markCharDirty('${c.id}')">${esc(c.background)}</textarea></div>
          <div class="kv"><span class="k">补充</span><textarea id="char-notes-${c.id}" rows="2" oninput="markCharDirty('${c.id}')">${esc(c.notes)}</textarea></div>
        </div>
        <div class="row" style="margin-top:12px">
          <span class="meta" id="char-dirty-${c.id}"></span>
          <span class="spacer"></span>
          <button class="btn primary" onclick="saveCharacter('${c.id}')">保存</button>
        </div>
      </div>`).join('')
    : '<div class="card meta">本小说还没有角色，上传照片或手动添加。</div>';
}

async function addCharacter() {
  const name = $('c-name').value.trim();
  const appearance = $('c-appearance').value.trim();
  const personality = $('c-personality').value.trim();
  const background = $('c-background').value.trim();
  const notes = $('c-notes').value.trim();
  const photoInput = $('c-photo');
  if (!name) return toast('请填写角色姓名', 'err');
  if (!state.novel) return toast('请先完成基本信息', 'err');
  try {
    const d = await api('/api/characters', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, appearance, personality, background, notes }),
    });
    const cid = d.character.id;
    // 自动归入当前小说
    const ids = state.novel.character_ids || [];
    if (!ids.includes(cid)) ids.push(cid);
    const nd = await api('/api/novels/' + state.novel.id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_ids: ids }),
    });
    state.novel = nd.novel;
    ['c-name', 'c-appearance', 'c-personality', 'c-background', 'c-notes'].forEach(i => $(i).value = '');
    if (photoInput.files.length) {
      showLoading('正在分析人物照片…', 'AI 正在识别外貌与性格特征，请稍候');
      try {
        const r = await uploadPhoto(cid, photoInput.files[0]);
        photoInput.value = '';
        if (r.analyzed === true) {
          toast('角色已添加，AI 分析完成', 'ok');
        } else if (r.analyzed === false) {
          toast('角色已添加（照片分析失败：' + (r.analyze_error || '未配置视觉模型') + '）', 'err');
        } else {
          toast('角色已添加（未配置视觉模型，仅保存照片）', 'ok');
        }
      } finally {
        hideLoading();
      }
    } else {
      toast('角色已添加', 'ok');
    }
    loadCharacters();
    loadNovels();
  } catch (e) { toast(e.message, 'err'); }
}

async function uploadCharPhoto(id) {
  const input = document.createElement('input');
  input.type = 'file'; input.accept = 'image/*';
  input.onchange = async () => {
    if (!input.files.length) return;
    showLoading('正在分析人物照片…', 'AI 正在识别外貌与性格特征，请稍候');
    try {
      const r = await uploadPhoto(id, input.files[0]);
      if (r.analyzed === false) {
        toast('照片已上传，但分析失败：' + (r.analyze_error || '未配置视觉模型'), 'err');
      } else if (r.analyzed) {
        toast('外貌性格分析完成', 'ok');
      } else {
        toast('照片已上传（未配置视觉模型，仅保存照片）', 'ok');
      }
      loadCharacters();
    } catch (e) {
      toast(e.message, 'err');
    } finally {
      hideLoading();
    }
  };
  input.click();
}

async function uploadPhoto(id, file) {
  const fd = new FormData();
  fd.append('file', file);
  return await api(`/api/characters/${id}/photo`, { method: 'POST', body: fd });
}

// 标记角色字段被修改（未保存状态提示）
function markCharDirty(id) {
  const el = $('char-dirty-' + id);
  if (el) el.textContent = '有未保存的修改';
}

// 保存单个角色的所有字段（姓名 + 外貌 + 性格 + 背景 + 补充）
async function saveCharacter(id) {
  const name = ($('char-name-' + id) || {}).value || '';
  const appearance = ($('char-appearance-' + id) || {}).value || '';
  const personality = ($('char-personality-' + id) || {}).value || '';
  const background = ($('char-background-' + id) || {}).value || '';
  const notes = ($('char-notes-' + id) || {}).value || '';
  if (!name.trim()) return toast('角色姓名不能为空', 'err');
  try {
    await api('/api/characters/' + id, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.trim(), appearance: appearance.trim(), personality: personality.trim(), background: background.trim(), notes: notes.trim() }),
    });
    const el = $('char-dirty-' + id);
    if (el) el.textContent = '已保存';
    setTimeout(() => { if (el) el.textContent = ''; }, 1500);
    toast('角色已保存', 'ok');
    loadCharacters();
  } catch (e) {
    toast(e.message, 'err');
  }
}

async function deleteCharacter(id) {
  if (!confirm('确定从本小说移除该角色？')) return;
  try {
    await api('/api/characters/' + id, { method: 'DELETE' });
    if (state.novel) {
      const ids = (state.novel.character_ids || []).filter(x => x !== id);
      const nd = await api('/api/novels/' + state.novel.id, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_ids: ids }),
      });
      state.novel = nd.novel;
    }
    loadCharacters();
    loadNovels();
  } catch (e) { toast(e.message, 'err'); }
}

// ================= 小说创作（向导） =================
async function loadNovels() {
  const d = await api('/api/novels');
  state.novels = d.novels;
  novelPage = 1;
  renderNovelFilterOptions();
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

// 状态显示名
function statusLabel(s) {
  return { 'draft': '草稿', 'outlined': '已生成大纲', 'generating': '生成中', 'done': '已完成', 'finished': '已完结' }[s] || s;
}

// 小说列表分页状态
let novelPage = 1;
const NOVEL_PAGE_SIZE = 5;

// 创作模式显示名
function modeLabel(m) {
  return { 'outline': '大纲', 'improv': '即兴', 'dialog': '对话' }[m] || '大纲';
}

// 渲染一个小说卡片（供列表与垃圾箱复用）
function novelCardHTML(n) {
  const isImprov = n.mode === 'improv';
  const isDialog = n.mode === 'dialog';
  const hasOutline = n.chapters && n.chapters.length;
  const genCount = (n.chapters || []).filter(c => c.content).length;
  const isFinished = n.status === 'finished';
  const created = n.created_at ? new Date(n.created_at * 1000).toLocaleString('zh-CN', { hour12: false }) : '';
  let primaryBtn;
  if (isDialog) {
    primaryBtn = `<button class="btn primary" onclick="nav('#/novels/${n.id}/dialog')">进入对话</button>`;
  } else if (isImprov) {
    primaryBtn = `<button class="btn primary" onclick="nav('#/novels/${n.id}/improv')">进入写作（${genCount} 章）</button>`;
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
        <button class="btn" onclick="exportNovel('${n.id}')">导出</button>
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
      <button class="btn" onclick="exportNovel('${n.id}')">导出</button>
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
  currentNovelId = null;
  ['n-title', 'n-genre', 'n-style', 'n-reference', 'n-background', 'n-worldbuilding'].forEach(i => $(i).value = '');
  $('n-chapters').value = 10;
  $('n-words').value = 2000;
  $('n-mode').value = 'outline';
  onModeChange();
  renderNovelModelSelect();
  renderSettings();
  renderGenreSelect();
  state.wizardStep = 1;
  $('editor-title').textContent = '新建小说';
  renderSteps();
  window.scrollTo({ top: 0 });
}

// 创作模式切换：即兴交互式、对话模式不需要预设章节数
function onModeChange() {
  const mode = $('n-mode') ? $('n-mode').value : 'outline';
  const chaptersLabel = $('n-chapters').closest('label');
  if (chaptersLabel) {
    chaptersLabel.style.display = (mode === 'improv' || mode === 'dialog') ? 'none' : '';
  }
}

function goStep(n) {
  state.wizardStep = n;
  renderSteps();
}

function renderSteps() {
  [1, 2, 3].forEach(i => {
    const panel = $('step-' + i);
    if (panel) panel.style.display = (i === state.wizardStep) ? 'block' : 'none';
    const dot = $('step-dot-' + i);
    if (dot) {
      dot.classList.toggle('active', i === state.wizardStep);
      dot.classList.toggle('done', i < state.wizardStep);
    }
  });
  if (state.wizardStep === 3) {
    renderCharacters();
    renderRelations();
  }
}

async function saveNovelBasics() {
  const title = $('n-title').value.trim();
  if (!title) return toast('请填写小说标题', 'err');
  const body = {
    title,
    genre: $('n-genre').value.trim(),
    style: $('n-style').value.trim(),
    reference_text: $('n-reference').value.trim(),
    background: $('n-background').value.trim(),
    worldbuilding: $('n-worldbuilding').value.trim(),
    chapter_count: parseInt($('n-chapters').value) || 10,
    words_per_chapter: parseInt($('n-words').value) || 2000,
    text_model_id: $('n-model').value || '',
    mode: $('n-mode').value || 'outline',
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
    goStep(3);
    loadNovels();
  } catch (e) { toast(e.message, 'err'); }
}

async function saveNovelChars() {
  if (!state.novel) return toast('请先完成基本信息', 'err');
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
    // 根据创作模式跳转：即兴 → 即兴写作页；对话 → 对话页；大纲 → 章节生成页
    if (state.novel.mode === 'improv') {
      nav('#/novels/' + state.novel.id + '/improv');
    } else if (state.novel.mode === 'dialog') {
      nav('#/novels/' + state.novel.id + '/dialog');
    } else {
      nav('#/novels/' + state.novel.id + '/generate');
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
    $('n-chapters').value = state.novel.chapter_count || 10;
    $('n-words').value = state.novel.words_per_chapter || 2000;
    renderNovelModelSelect();
    renderSettings();
    renderGenreSelect();
    $('n-mode').value = state.novel.mode || 'outline';
    onModeChange();
    state.relations = (state.novel.relationships || []).map(r => ({ ...r }));
    $('editor-title').textContent = '编辑《' + (state.novel.title || '未命名') + '》';
    // 若已有大纲，更新"编辑设定"链接指向正确 id
    const editLink = $('gen-edit-link');
    if (editLink) editLink.setAttribute('href', '#/novels/' + id + '/edit');
    state.wizardStep = 1;
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
      // 根据创作模式决定返回目标：即兴 → 即兴写作页，对话 → 对话页，大纲 → 生成页
      const backTarget = state.novel.mode === 'improv' ? '/improv'
        : state.novel.mode === 'dialog' ? '/dialog' : '/generate';
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

  // 渲染"引用前文章节"选择区（有已生成章节时显示）
  const ctxBox = $('improv-context-chapters');
  if (ctxBox) {
    if (done.length) {
      ctxBox.style.display = 'block';
      ctxBox.innerHTML = `<div class="improv-context-title">引用前文章节（选择要带入上下文的章节及方式）</div>` +
        done.map(c => `
          <label class="improv-context-item">
            <input type="checkbox" id="improv-ref-${c.index}" checked>
            <span>第${c.index}章 ${esc(c.title || '')}</span>
            <select id="improv-ref-mode-${c.index}">
              <option value="summary">摘要</option>
              <option value="full">完整内容</option>
            </select>
          </label>`).join('');
    } else {
      ctxBox.style.display = 'none';
    }
  }

  if (!done.length) {
    body.innerHTML = '<div class="card meta">还没有章节。在上方输入本章写作指引，点击「生成本章」开始创作。</div>';
    return;
  }

  body.innerHTML = done.map(c => `
    <div class="card improv-chapter-card">
      <div class="row">
        <span class="title">第${c.index}章</span>
        <input class="improv-title-input" id="improv-title-${c.index}" value="${esc(c.title || '')}" placeholder="第${c.index}章标题（可编辑）" onchange="saveImprovTitle(${c.index})">
        <span class="meta">约 ${c.word_count || ''} 字</span>
        <span class="spacer"></span>
        <button class="btn" onclick="nav('#/novels/${n.id}/chapter/${c.index}')">查看/编辑正文</button>
      </div>
      ${c.instruction ? `<div class="improv-instruction-hint">📝 本章写作提示：${esc(c.instruction)}</div>` : ''}
      <div class="chapter-content" style="max-height:300px">${esc(c.content)}</div>
    </div>`).join('');
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
    // 每条消息的操作按钮：编辑 + （AI 消息）生成章节
    const actions = `
      <div class="dialog-msg-actions">
        <button class="dialog-act-btn" onclick="editDialogMessage(${idx})">编辑</button>
        ${!isUser ? `<button class="dialog-act-btn" onclick="dialogToChapter(${idx})">生成章节</button>` : ''}
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
    const wlEl = $('dialog-word-limit');
    const wordLimit = wlEl && wlEl.value.trim() !== '' ? parseInt(wlEl.value, 10) : null;
    const body = { text: newText, history: prefix };
    if (wordLimit !== null && !isNaN(wordLimit)) body.word_limit = wordLimit;
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
  // 读取本轮期望字数（留空则后端默认 500）
  const wlEl = $('dialog-word-limit');
  const wordLimit = wlEl && wlEl.value.trim() !== '' ? parseInt(wlEl.value, 10) : null;
  if (wordLimit !== null && (isNaN(wordLimit) || wordLimit < 50 || wordLimit > 5000)) {
    return toast('字数需在 50~5000 之间', 'err');
  }

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
    if (wordLimit !== null) body.word_limit = wordLimit;
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
    if (backLink) backLink.setAttribute('href', '#/novels');
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
      <div class="reader-ch-content">${esc(c.content)}</div>
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
    html += `<div class="chapter-content full-chapter-content">${esc(chapter.content)}</div>`;
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
    <button class="btn" onclick="exportNovel('${n.id}')">导出 Markdown</button>
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
  const res = await fetch(path, opts);
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
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
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

async function exportNovel(id) {
  try {
    const headers = {};
    if (authToken) headers['Authorization'] = 'Bearer ' + authToken;
    const res = await fetch(`/api/novels/${id}/export`, { headers });
    if (res.status === 401) { handleUnauthorized(); return; }
    if (!res.ok) { toast('导出失败', 'err'); return; }
    const blob = await res.blob();
    // 从 Content-Disposition 解析文件名
    let fname = 'novel.md';
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
  if (g.name && $('n-genre')) $('n-genre').value = g.name;
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

// ============ 初始化 ============
(async function init() {
  // 未登录：直接进入登录页，不加载数据
  if (!authToken) {
    await router();
    return;
  }
  try {
    await loadSettings();
    await loadProviders();
    await loadCharacters();
    await loadGenres();
    // 根据 hash 路由进入对应视图
    await router();
  } catch (e) {
    // 401 等认证错误已由 api() 处理跳转登录
    if (authToken) {
      toast('初始化失败：' + e.message, 'err');
    }
  }
})();
