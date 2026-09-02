// ============ 国际化（i18n） ============
// 以「中文原文」作为 key，简体中文直接回退原文，其他语言查字典。
// 支持 {变量} 占位符替换。

const I18N_DICTS = {
  en: {
    // ---- 通用 ----
    "保存": "Save",
    "取消": "Cancel",
    "删除": "Delete",
    "编辑": "Edit",
    "刷新": "Refresh",
    "关闭": "Close",
    "导入": "Import",
    "创建": "Create",
    "发送": "Send",
    "配置": "Settings",
    "用户管理": "Users",
    "退出登录": "Sign out",
    "处理中…": "Processing…",
    "加载中…": "Loading…",
    "确定": "Confirm",
    "返回": "Back",

    // ---- 顶部导航 ----
    "题材库": "Genres",
    "世界书": "World Book",
    "角色": "Characters",
    "小说阅读": "Library",
    "日志": "Logs",
    "小说创作": "Writing",
    "切换夜间模式": "Toggle dark mode",

    // ---- 登录/注册 ----
    "登录": "Sign in",
    "请输入用户名和密码": "Enter your username and password",
    "用户名": "Username",
    "密码": "Password",
    "创建管理员": "Create admin",
    "首次使用，请创建管理员账号": "First time here? Create an admin account",
    "密码（至少4位）": "Password (min 4 chars)",
    "确认密码": "Confirm password",
    "创建并登录": "Create & sign in",

    // ---- 用户管理 ----
    "创建用户": "Create user",
    "角色": "Role",
    "普通用户": "User",
    "管理员": "Admin",

    // ---- 配置 ----
    "大模型API": "LLM API",
    "提示词": "Prompts",
    "添加服务商": "Add provider",
    "预设（可选）": "Preset (optional)",
    "自定义": "Custom",
    "名称": "Name",
    "Base URL": "Base URL",
    "API Key": "API Key",
    "代理模式": "Proxy mode",
    "直连（国内服务商）": "Direct (domestic)",
    "系统代理（走环境变量）": "System proxy (env vars)",
    "自定义代理": "Custom proxy",
    "自定义代理地址": "Custom proxy URL",
    "取消编辑": "Cancel edit",
    "生成参数（全局默认，模型可单独覆盖）": "Generation params (global defaults, per-model overrides)",
    "创意度 temperature（0~1.5）": "Temperature (0~1.5)",
    "字数→token 系数": "Chars→token ratio",
    "保存生成参数": "Save params",

    // ---- 题材库 ----
    "添加题材": "Add genre",
    "导入题材库": "Import genres",
    "题材名称": "Genre name",
    "参考风格": "Reference style",
    "参考文本片段（可选，创作时作为参考原文）": "Reference text (optional)",
    "题材描述（可选）": "Description (optional)",
    "保存": "Save",

    // ---- 世界书 ----
    "新建世界书": "New world book",
    "导入世界书": "Import world book",
    "世界书名称": "World book name",
    "世界书名称（可选，留空用文件内名称）": "World book name (optional, use file name if empty)",
    "描述（可选）": "Description (optional)",
    "导入世界书（SillyTavern 格式）": "Import world book (SillyTavern format)",

    // ---- 角色库 ----
    "角色库": "Characters",
    "添加角色": "Add character",
    "小说名称": "Novel",
    "最新角色（默认）": "Latest (default)",
    "展示最新的角色。": "Showing latest characters.",
    "角色姓名": "Character name",
    "照片（可选）": "Photo (optional)",
    "选择照片并裁切": "Choose & crop photo",
    "AI 分析": "AI analyze",
    "重新选择": "Re-select",
    "外貌": "Appearance",
    "性格": "Personality",
    "补充": "Notes",
    "保存角色": "Save character",
    "角色详情": "Character",
    "更换照片": "Change photo",
    "本书背景设定": "Background in this novel",
    "删除角色": "Delete character",
    "编辑角色": "Edit character",
    "角色卡": "Character card",
    "本书背景": "Background here",
    "未上传照片": "No photo",

    // ---- 日志 ----
    "清空日志": "Clear logs",

    // ---- 小说列表 ----
    "我的小说": "My Novels",
    "新建小说": "New novel",
    "垃圾箱": "Trash",
    "排序": "Sort",
    "时间（新→旧）": "Time (new→old)",
    "时间（旧→新）": "Time (old→new)",
    "标题": "Title",
    "创作模式": "Mode",
    "模型": "Model",
    "全部模型": "All models",
    "状态": "Status",
    "全部状态": "All statuses",
    "草稿": "Draft",
    "已生成大纲": "Outlined",
    "生成中": "Generating",
    "已完成": "Done",
    "已完结": "Finished",
    "小说阅读": "Library",
    "返回小说列表": "Back to novels",
    "开始阅读": "Start reading",
    "编辑设定": "Edit settings",
    "阅读全文": "Read full text",
    "阅读": "Read",
    "导出 MD": "Export MD",
    "导出 EPUB": "Export EPUB",
    "重开": "Reopen",
    "完结": "Finish",
    "恢复": "Restore",
    "彻底删除": "Delete forever",

    // ---- 小说编辑器 ----
    "新建小说": "New novel",
    "基本信息": "Basic info",
    "AI 原著拆解": "AI source analysis",
    "角色设定": "Characters",
    "模型与提示词": "Model & prompts",
    "小说标题": "Novel title",
    "题材类型（可下拉选择常用题材，也可直接输入自定义题材）": "Genre (pick or type)",
    "从题材库选择（选中后自动填充题材/风格/参考文本）": "Pick from genre library",
    "不使用题材库": "Don't use genre library",
    "大纲式（先生成大纲，再逐章写）": "Outline (outline first, then chapters)",
    "即兴交互式（边写边定，无需大纲）": "Improv (write as you go)",
    "对话模式（像聊天一样推进剧情）": "Dialog (chat to advance plot)",
    "改写（导入已有小说，按要求改写）": "Rewrite (import & rewrite)",
    "续写（导入已有小说，续写后续）": "Continue (import & continue)",
    "章节数": "Chapter count",
    "每章字数": "Words per chapter",
    "导入已有小说原文": "Import existing novel",
    "原文内容": "Source text",
    "从文件导入（.txt / .md）": "Import from file (.txt / .md)",
    "改写要求 / 续写要求": "Rewrite / continue instructions",
    "故事背景（时代/地点/大环境设定）": "Story background (era / place / setting)",
    "世界观（力量体系/规则/特殊设定）": "Worldbuilding (power system / rules)",
    "写作风格（留空则用默认流畅叙事）": "Writing style (default if empty)",
    "参考小说文本（粘贴一段想模仿的小说，生成大纲时自动分析其风格）": "Reference text (paste a novel to mimic its style)",
    "关联世界书（可选，勾选后在生成时注入对应世界设定）": "Link world books (optional)",
    "保存基本信息": "Save basics",
    "下一步 →": "Next →",
    "上一步": "Back",
    "下一步：角色设定 →": "Next: characters →",
    "下一步：模型与提示词 →": "Next: model & prompts →",
    "开始拆解原著": "Analyze source",
    "新建角色": "New character",
    "从角色库选择": "Pick from library",
    "从角色库选择角色": "Pick characters",
    "人物关系设定": "Relationships",
    "添加关系": "Add relation",
    "保存角色设定": "Save characters",
    "创作模型与前置提示词": "Model & global prompt",
    "创作模型": "Generation model",
    "全局前置提示词": "Global prompt",
    "保存模型与提示词": "Save model & prompt",
    "保存并进入生成 →": "Save & generate →",

    // ---- 章节生成 / 即兴 / 对话 / 改写 / 续写 ----
    "章节生成": "Chapter generation",
    "即兴写作": "Improv writing",
    "对话创作": "Dialog writing",
    "改写创作": "Rewrite",
    "续写创作": "Continue writing",
    "章节": "Chapter",
    "本章写作指引": "This chapter's direction",
    "生成本章": "Generate chapter",
    "已生成章节": "Generated chapters",
    "排序：最新在前": "Sort: newest first",
    "改写要求": "Rewrite instructions",
    "保存要求": "Save instructions",
    "改写全部章节": "Rewrite all chapters",
    "按原文重新切分": "Re-split source",
    "本章续写要求": "This chapter's continuation",
    "续写下一章": "Continue next chapter",
    "返回小说": "Back to novel",
    "减小字号": "Decrease font",
    "增大字号": "Increase font",

    // ---- 裁切 ----
    "裁切照片（拖动框移动，拖动四角调整大小）": "Crop photo (drag to move, drag corners to resize)",
    "裁剪后将以 JPEG 保存": "Will be saved as JPEG",
    "确认裁切": "Apply crop",

    // ---- 创作模式 ----
    "大纲": "Outline",
    "即兴": "Improv",
    "对话": "Dialog",
    "改写": "Rewrite",
    "续写": "Continue",

    // ---- 小说列表按钮/信息 ----
    "进入对话": "Enter dialog",
    "进入写作（{n} 章）": "Write ({n} ch.)",
    "进入改写（{n} 段）": "Rewrite ({n} parts)",
    "进入续写（{n} 章）": "Continue ({n} ch.)",
    "进入生成（{n}/{m}）": "Generate ({n}/{m})",
    "继续创作": "Continue",
    "未设题材": "No genre",
    "章": "ch.",
    "字/章": "words/ch.",
    "已生成": "generated",
    "（全局）": "(global)",
    "共 {n} 本": "{n} novels",
    "没有符合条件的小说。": "No matching novels.",
    "个": "",

    // ---- 状态/动态 ----
    "接下来写第 {n} 章": "Next: chapter {n}",
    "未命名": "Untitled",
    "未设题材": "No genre",
    "暂无": "None",
    "成功": "Success",
    "失败": "Failed",
    "暂无外貌描述": "No appearance",
    "暂无人物设定": "No character settings",
    "暂无背景设定": "No background",
  }
};

let I18N_LOCALE = 'zh';

// 当前语言
function getLocale() {
  return I18N_LOCALE;
}

// 设置语言并持久化（refresh 为 false 时不触发动态视图重渲染，供初始化使用）
function setLocale(locale, persist = true, refresh = true) {
  I18N_LOCALE = locale || 'zh';
  if (persist) {
    try { localStorage.setItem('nexTaleLocale', I18N_LOCALE); } catch (e) {}
  }
  document.documentElement.lang = I18N_LOCALE === 'en' ? 'en' : 'zh-CN';
  applyStaticI18n();
  // 让 app.js 有机会刷新动态渲染内容（若已加载）
  if (refresh && typeof onLocaleChanged === 'function') onLocaleChanged();
}

// 初始化语言（仅应用静态文案，不触发重渲染）
function initLocale() {
  let saved = 'zh';
  try { saved = localStorage.getItem('nexTaleLocale') || 'zh'; } catch (e) {}
  setLocale(saved, false, false);
}

// 翻译函数：t('中文原文') -> 当前语言文本；支持 {var} 替换
function t(key, vars) {
  if (key == null) return '';
  let s = key;
  if (I18N_LOCALE !== 'zh') {
    const dict = I18N_DICTS[I18N_LOCALE] || {};
    if (dict[key] !== undefined) s = dict[key];
  }
  if (vars) {
    for (const k in vars) {
      s = s.split('{' + k + '}').join(vars[k]);
    }
  }
  return s;
}

// 扫描并应用静态文案：data-i18n（文本）与 data-i18n-placeholder（占位符）
function applyStaticI18n(root) {
  const scope = root || document;
  scope.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.getAttribute('data-i18n'));
  });
  scope.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
  });
}
