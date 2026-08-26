# 织叙-NexTale (NexTale)

> [简体中文](README.md) | [繁體中文](README.zh-TW.md) | [English](README.en.md) | [日本語](README.ja.md)

An AI novel-writing tool built with Python + Web UI. Supports multiple writing modes (Outline / Improvised / Conversational), multiple AI provider integrations, character photo cropping & AI analysis, worldbooks & genre library, prompt configuration, chapter polishing & expansion, chapter version history, multi-format export, finish/reopen management, trash bin, and a complete novel-writing workflow.

## Features

### Writing Modes

| Mode | Description |
|------|-------------|
| **Outline** | Generate a story synopsis, worldbuilding, and chapter outline first, then write chapter by chapter — ideal for long-form planning. |
| **Improvised** | No outline needed. Write as you go, generating one chapter at a time based on a "writing guide" — ideal for inspiration-driven writing. |
| **Conversational** | Advance the plot like an IM chat. The AI outputs at most 500 characters per turn, and you can merge conversations into formal chapters at any time. |

### Core Capabilities

1. **Multi-provider integration**: Supports all OpenAI-compatible APIs (OpenAI / DeepSeek / Zhipu GLM / Kimi / Qwen / SiliconFlow, etc.). Text generation and vision analysis can use different providers. Each provider supports its own proxy mode (direct / system proxy / custom proxy).
2. **Character photo cropping & AI analysis**: Crop the photo in the browser with a selection box (pure frontend canvas, no third-party library). AI analysis is now triggered manually via an "AI Analysis" button that uses a vision model to analyze appearance and personality, generating a character card ready for your novel. Appearance / personality / background / notes can all be manually edited before saving.
3. **Character library & relationships**: The character library is a dedicated top-level tab (list / add / detail), letting you maintain characters centrally and reuse them when creating novels. Supports multiple characters with relationship types and descriptions between them.
4. **Writing style & reference text**: Paste reference novel excerpts to automatically extract their style, or describe the style manually. Supports a global pre-prompt.
5. **Chapter polish & expansion**: While editing a chapter, select any text fragment to polish or expand it, with the result streamed back and replaced in place.
6. **Outline editing**: After the outline is generated, you can freely edit chapter titles and summaries.
7. **Real-time streaming**: Chapter generation, polishing, and expansion all stream output in real time, with loading overlays and progress indicators.
8. **Finish / Reopen**: A finished novel can no longer be edited; you can "reopen" it at any time to resume editing.
9. **Trash bin**: Deleted novels go to the trash bin first, and can be restored or permanently deleted.
10. **List management**: The novel list supports pagination, filtering by writing mode (Improv / Outline / Conversational), sorting by time / title, and filtering by model / status.
11. **Request logs**: Every AI request is logged and can be queried from the UI.
12. **Worldbook**: Create your own worldbooks or import SillyTavern-format ones. Entries support constant injection and keyword-based dynamic triggering (trigger words / selective / probability), automatically matched and injected into context during generation.
13. **Genre library**: Save frequently used genres as templates (style, reference text, description), import them in bulk, and apply them with one click when creating a novel.
14. **Prompt configuration**: All AI prompts (analysis / outline / chapter / polish / expand / conversation) are centrally managed and can be customized in the UI and persisted as overrides.
15. **Chapter version history**: Chapters are automatically snapshotted before editing or AI generation. You can view the history and revert to an older version with one click.
16. **Multi-format export**: Finished novels can be exported in Markdown / TXT / EPUB.

### Conversational Mode Details

- The user and AI advance the plot in an IM-chat fashion; the AI outputs a prose fragment of at most 500 characters per turn.
- Each message can be "edited": editing AI-generated content only modifies the text (no AI call); editing a user message regenerates the AI reply.
- After any AI message you can "Generate chapter": it merges previous AI output directly into a formal chapter (the prose is not regenerated — only the summary is extracted).
- Conversations that have been merged into chapters are automatically removed from the chat area; subsequent merges no longer include already-merged content.
- Generated chapters can be viewed, edited, and deleted.

### Worldbooks & Dynamic Triggering

Worldbooks store setting entries such as worldbuilding details, character backstories, and proper nouns. Each entry can be configured with:

- **Constant injection**: `constant` entries are unconditionally added to every generation's context.
- **Dynamic triggering**: non-constant entries use SillyTavern-style keyword matching — injected when a trigger word (`key`) appears in the current text/synopsis; `selective` entries require both primary and secondary keys to match; `probability` controls the chance of injection after a match.
- **SillyTavern import**: supports importing SillyTavern worldbook JSON (entries as either an object or an array), auto-normalizing trigger words, positions, probabilities, and other fields.

### Worldbuilding Source Protection

If you manually fill in the "Worldbuilding" field, the AI will not overwrite it when generating the outline; it is only auto-generated by the AI when left blank.

## Installation & Running

### Requirements

- Python 3.10+
- An OpenAI-compatible AI provider account (for text generation; vision analysis requires an image-capable model)

### One-click Install (Recommended)

```bash
cd novel-generator
bash install.sh
```

The script automatically: creates a Python virtual environment (`.venv`) → installs dependencies from `requirements.txt` → initializes the SQLite database (`data/novel.db` and all tables) → generates the `run.sh` startup script.

Custom port / public access:

```bash
PORT=9000 HOST=0.0.0.0 bash install.sh
```

### Start the Service

```bash
./run.sh                 # foreground (default http://127.0.0.1:8000)
./run.sh --reload        # development mode (auto-reload on code changes)
```

Open http://127.0.0.1:8000 in your browser (you will be prompted to set an access password on first use).

### Manual Install

```bash
cd novel-generator
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

> The database `data/novel.db` and all tables are created automatically on first startup — no manual database setup needed.

## First-Time Setup

1. **"API Config" → Add Provider**: fill in base_url + API Key + proxy mode, then save.
2. Click **"🔌 Connect"** on the provider card to fetch its model list.
3. Click **"＋ Add Model"**: choose a model name (from the dropdown after connecting, or type manually), choose a type (Text / Vision), optionally set temperature and max_tokens (leave empty for global defaults), then save.
4. Click **"●Text" / "●Vision"** on a model entry to mark which model to use for text generation / vision analysis (only one each).
5. Optional (advanced):
   - **"Genre Library"**: pre-save genre templates (style / reference text / description) and apply them with one click when creating a novel.
   - **"Worldbook"**: create or import SillyTavern worldbooks for worldbuilding details and proper-noun settings.
   - **"Prompt Config"**: customize the various AI prompts to override the defaults.
6. **"Novel Writing" → "＋ New Novel"**, then follow the wizard:
   - ① Basic info: title, genre (selectable from the genre library), writing mode (Outline / Improvised / Conversational), chapter count, words per chapter, writing style, reference text, pre-prompt.
   - ② Characters: pick from the character library or upload a photo (crop, then manually trigger AI analysis) for appearance/personality, and set up relationships.
   - ③ Enter the chosen mode and start writing: generate outline → write chapter by chapter / improvise / converse.
7. When done, you can "Finish" the novel and export it as Markdown / TXT / EPUB or read the full text.

## Common Provider base_url

| Provider | base_url | Example Models |
|----------|----------|----------------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` (vision) |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` (no vision) |
| Zhipu GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` / `glm-4v` (vision) |
| Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-32k` |
| Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` / `qwen-vl-plus` (vision) |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3` etc. |

> Note: Vision analysis requires an image-capable model. Many text-only providers (e.g., DeepSeek's main model) do not support vision — in that case, assign a separate vision-capable provider/model for "Vision Analysis".

## Proxy Notes

If `http_proxy` / `all_proxy` environment variables are set, the openai SDK reads them automatically. Domestic providers (DeepSeek / Zhipu / Kimi) should use "Direct"; OpenAI and others may need "System Proxy" or "Custom Proxy" with your local proxy address (e.g., `http://127.0.0.1:4780`).

## Directory Structure

```
novel-generator/
├── app.py            # FastAPI backend entry + all APIs
├── ai_client.py      # OpenAI-compatible API wrapper (proxy control, streaming)
├── generators.py     # Generation engine (style/outline/chapter/summary/polish/expand/conversation/worldbook matching)
├── prompts.py        # Centralized prompt templates (overridable via the "Prompt Config" page)
├── storage.py        # SQLite persistence (incl. chapter version history)
├── install.sh        # One-click install script
├── start.sh          # Startup script
├── run.sh            # Startup script (generated by install.sh)
├── requirements.txt  # Python dependencies
├── data/novel.db     # SQLite database file (auto-created)
├── uploads/          # Uploaded character photos
├── output/           # Exported Markdown/TXT/EPUB
└── static/           # Frontend (HTML/CSS/JS)
```

## How Generation Works

1. **Outline generation**: analyze reference text style → aggregate characters/relationships/style → generate synopsis + worldbuilding + chapter outline; if you manually filled in the worldbuilding, it is preserved and not overwritten.
2. **Chapter-by-chapter generation**: each chapter is injected with the full setting + outline + progress summary to ensure coherence; the progress summary is updated after each chapter and condensed automatically when too long.
3. **Conversational mode**: each turn injects the full setting + progress summary + conversation history into the prompt; the AI outputs a prose fragment of at most 500 characters.
4. **Worldbook injection**: during outline/chapter/conversation generation, constant entries are injected unconditionally, while non-constant entries are matched by trigger words and injected dynamically.
5. **Word count control**: constrained by both the prompt and max_tokens (the `token_ratio` coefficient is adjustable).
6. **Context length**: you can set the model's context length, and the tool automatically controls the amount of content sent in each generation.

## License

This project is for learning and personal use only.
