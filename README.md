# 织叙-NexTale

一个基于 Python + Web 界面的 AI 小说生成工具。

## 功能

1. **配置不同 AI API**：支持所有 OpenAI 兼容接口的服务商（OpenAI / DeepSeek / 智谱 GLM / Kimi / 通义千问 / 硅基流动等），通过 base_url 区分；文本生成与视觉分析可分别指定不同服务商；每个服务商可单独设置代理模式（直连 / 系统代理 / 自定义代理）。
2. **上传人物照片分析**：上传照片后用视觉模型自动分析人物外貌与性格，生成可直接用于小说的角色卡。
3. **写作风格 + 参考小说**：可粘贴参考小说片段，生成大纲时自动提炼其风格；也可手动描述风格。
4. **人物角色关系设定**：多角色 + 角色间关系类型与描述。
5. **章节数和字数**：设置总章数、每章目标字数，自动生成大纲并逐章创作。

## 安装与运行

### 一键安装（推荐）

```bash
cd novel-generator
bash install.sh
```

脚本会自动：创建 Python 虚拟环境（`.venv`）→ 安装 `requirements.txt` 依赖 → 初始化 SQLite 数据库（`data/novel.db` 及全部表）→ 生成启动脚本 `run.sh`。

自定义监听端口 / 对外访问：

```bash
PORT=9000 HOST=0.0.0.0 bash install.sh
```

### 启动服务

```bash
./run.sh                 # 前台运行
./run.sh --reload        # 开发模式（代码改动自动热重载）
```

浏览器打开 http://127.0.0.1:8000（首次使用会提示设置访问密码）。

### 手动安装

```bash
cd novel-generator
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

> 数据库 `data/novel.db` 及所有表会在首次启动时自动创建，无需手动建库。

## 首次使用步骤

1. 「API 配置」→ 添加服务商：填 base_url + API Key + 代理模式，保存。
2. 在服务商卡片上点「🔌 连接」，拉取该服务商的模型列表。
3. 点「＋ 添加模型」：选模型名（连接后从下拉选择，也可手输）、选类型（文本 / 视觉，二选一）、可配 temperature 与 max_tokens（留空用全局默认），保存。
4. 在模型条目上点「●文本」「●视觉」标记，指定当前文本生成 / 视觉分析用哪个模型（各只能选一个）。
5. 「小说创作」→ 点「＋ 新建小说」，按向导三步走：
   - ① 基本信息：标题、题材、章节数、每章字数、写作风格、参考小说文本。
   - ② 角色设定：上传照片 AI 分析外貌性格（或手填），设定人物关系。
   - ③ 生成小说：生成大纲 → 逐章生成全文 → 导出 Markdown。

## 常见服务商 base_url

| 服务商 | base_url | 模型示例 |
|--------|----------|----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o`（支持视觉） |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat`（无视觉） |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` / `glm-4v`（视觉） |
| Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-32k` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` / `qwen-vl-plus`（视觉） |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3` 等 |

> 注意：视觉分析需要一个支持图片输入的模型。很多纯文本服务商（如 DeepSeek 主模型）不支持视觉，此时请为「视觉分析」单独指定一个支持视觉的服务商/模型。

## 代理说明

本机若设置了 `http_proxy` / `all_proxy` 环境变量，openai SDK 会自动读取。国内服务商（DeepSeek/智谱/Kimi）应选「直连」，OpenAI 等需选「系统代理」或「自定义代理」填入本地代理地址（如 `http://127.0.0.1:4780`）。

## 目录结构

```
novel-generator/
├── app.py            # FastAPI 后端入口 + 全部 API
├── ai_client.py      # OpenAI 兼容接口封装（含代理控制）
├── generators.py     # 生成引擎（风格/大纲/章节/前情提要）
├── storage.py        # SQLite 持久化（providers/models/settings/characters/novels/chapters 六张表）
├── data/novel.db     # SQLite 数据库文件（自动创建）
├── uploads/          # 上传的角色照片
├── output/           # 导出的 Markdown
└── static/           # 前端页面
```

## 生成原理

1. 生成大纲时：先分析参考文本风格 → 汇总角色/关系/风格 → 生成故事梗概 + 世界观 + 章节大纲。
2. 逐章生成时：每章注入完整设定 + 大纲 + 前情提要，保证连贯性；每章生成后自动更新前情提要，过长时自动浓缩。
3. 字数控制：通过提示词 + max_tokens 双重约束（`token_ratio` 系数可调）。
