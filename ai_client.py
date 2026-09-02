"""OpenAI 兼容接口封装：一套 SDK 支持 OpenAI / DeepSeek / 智谱 / Kimi 等。

通过 base_url 区分不同服务商，文本生成与视觉分析可分别指定不同服务商。
每个服务商可单独配置代理模式：直连 / 系统代理 / 自定义代理地址。
"""
from openai import OpenAI
from httpx2 import Client as HttpxClient
import base64
import re
import time

# 常见服务商 base_url 参考（用户可在界面自定义覆盖）
PRESET_BASE_URLS = {
    "OpenAI": "https://api.openai.com/v1",
    "DeepSeek": "https://api.deepseek.com/v1",
    "智谱 GLM": "https://open.bigmodel.cn/api/paas/v4",
    "Kimi (Moonshot)": "https://api.moonshot.cn/v1",
    "通义千问": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "硅基流动 SiliconFlow": "https://api.siliconflow.cn/v1",
}


class AIClientError(Exception):
    """统一的上层异常，用于向用户展示友好错误信息。"""


def _log_request(kind, provider, model, prompt, status="ok", elapsed=0.0,
                 prompt_tokens=None, completion_tokens=None, error="", name="", user_id=""):
    """记录 AI 请求日志（延迟导入 storage，避免循环依赖）。"""
    try:
        import storage
        pname = (provider or {}).get("name", "") if isinstance(provider, dict) else str(provider or "")
        storage.add_log(kind, pname, model or "", prompt or "",
                        status=status, elapsed=elapsed,
                        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                        error=error, name=name, user_id=user_id)
    except Exception:  # noqa: BLE001
        pass  # 日志失败不影响主流程


def _snapshot_messages(messages):
    """把 messages 序列化为可读的 prompt 摘要（用于日志）。"""
    if not messages:
        return ""
    parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            # 多模态内容（视觉）
            text = "".join(p.get("text", "") for p in content if p.get("type") == "text")
            content = text + " [图片]"
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


def _build_client(provider):
    proxy = (provider.get("proxy") or "").strip()
    kwargs = {
        "api_key": provider.get("api_key", ""),
        "base_url": provider.get("base_url", ""),
        "timeout": 300.0,
        "max_retries": 1,
    }
    # 代理策略：
    #   "" 或 "direct" -> 直连，忽略系统代理（国内服务商默认）
    #   "system"      -> 使用系统环境变量代理（http_proxy/all_proxy）
    #   其他           -> 视为自定义代理 URL
    if proxy in ("", "direct"):
        http_client = HttpxClient(trust_env=False)
    elif proxy == "system":
        http_client = HttpxClient(trust_env=True)
    else:
        http_client = HttpxClient(proxy=proxy, trust_env=False)
    kwargs["http_client"] = http_client
    return OpenAI(**kwargs)


def chat_text(provider, model, messages, temperature=0.8, max_tokens=None, name="", user_id=""):
    """纯文本对话补全，返回 (content, usage)。name 为语义化操作名（用于日志）。"""
    prompt_snapshot = _snapshot_messages(messages)
    start = time.time()
    try:
        client = _build_client(provider)
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        resp = client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        usage = None
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }
        _log_request("chat", provider, model, prompt_snapshot,
                     status="ok", elapsed=time.time() - start,
                     prompt_tokens=(usage or {}).get("prompt_tokens"),
                     completion_tokens=(usage or {}).get("completion_tokens"),
                     name=name, user_id=user_id)
        return content, usage
    except AIClientError as e:
        _log_request("chat", provider, model, prompt_snapshot,
                     status="error", elapsed=time.time() - start, error=str(e), name=name, user_id=user_id)
        raise
    except Exception as e:  # noqa: BLE001
        _log_request("chat", provider, model, prompt_snapshot,
                     status="error", elapsed=time.time() - start, error=str(e), name=name, user_id=user_id)
        raise AIClientError(_friendly_error(e)) from e


def chat_text_stream(provider, model, messages, temperature=0.8, max_tokens=None, name="", user_id=""):
    """流式文本对话补全，yield 每个增量片段（用于实时输出）。

    使用 httpx 原生 SSE 请求，逐 token 立即返回（避免 OpenAI SDK 内部缓冲）。
    name 为语义化操作名（用于日志）。
    """
    import json as _json
    prompt_snapshot = _snapshot_messages(messages)
    start = time.time()
    try:
        # 构造 OpenAI 兼容接口的 chat completion 请求
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens

        proxy = (provider.get("proxy") or "").strip()
        if proxy in ("", "direct"):
            http_client = HttpxClient(trust_env=False, timeout=300.0)
        elif proxy == "system":
            http_client = HttpxClient(trust_env=True, timeout=300.0)
        else:
            http_client = HttpxClient(proxy=proxy, trust_env=False, timeout=300.0)

        with http_client.stream(
            "POST",
            (provider.get("base_url", "") or "").rstrip("/") + "/chat/completions",
            headers={
                "Authorization": f"Bearer {provider.get('api_key', '')}",
                "Content-Type": "application/json",
            },
            json=body,
        ) as resp:
            if resp.status_code >= 400:
                # 读取错误响应
                text = resp.read().decode("utf-8", errors="replace")
                raise AIClientError(_friendly_error(Exception(f"{resp.status_code} {text}")))

            # 逐行解析 SSE
            for line in resp.iter_lines():
                if not line:
                    continue
                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    obj = _json.loads(payload)
                except Exception:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                c = delta.get("content")
                if c:
                    yield c
        _log_request("chat_stream", provider, model, prompt_snapshot,
                     status="ok", elapsed=time.time() - start, name=name, user_id=user_id)
    except AIClientError as e:
        _log_request("chat_stream", provider, model, prompt_snapshot,
                     status="error", elapsed=time.time() - start, error=str(e), name=name, user_id=user_id)
        raise
    except Exception as e:  # noqa: BLE001
        _log_request("chat_stream", provider, model, prompt_snapshot,
                     status="error", elapsed=time.time() - start, error=str(e), name=name, user_id=user_id)
        raise AIClientError(_friendly_error(e)) from e


def chat_vision(provider, model, prompt, image_base64, temperature=0.5, max_tokens=None, name="", user_id=""):
    """视觉分析：传入 base64 图片与文字提示，返回 (content, usage)。name 为语义化操作名（用于日志）。"""
    start = time.time()
    try:
        client = _build_client(provider)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        },
                    },
                ],
            }
        ]
        kwargs = {"model": model, "messages": messages, "temperature": temperature}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        resp = client.chat.completions.create(**kwargs)
        content = resp.choices[0].message.content or ""
        usage = None
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }
        _log_request("vision", provider, model, prompt,
                     status="ok", elapsed=time.time() - start,
                     prompt_tokens=(usage or {}).get("prompt_tokens"),
                     completion_tokens=(usage or {}).get("completion_tokens"),
                     name=name, user_id=user_id)
        return content, usage
    except Exception as e:  # noqa: BLE001
        _log_request("vision", provider, model, prompt,
                     status="error", elapsed=time.time() - start, error=str(e), name=name, user_id=user_id)
        raise AIClientError(_friendly_error(e)) from e


def _http_client(provider, timeout=300.0):
    """按服务商代理策略构造原生 httpx 客户端（用于非 chat 接口，如文生图）。"""
    proxy = (provider.get("proxy") or "").strip()
    if proxy in ("", "direct"):
        return HttpxClient(trust_env=False, timeout=timeout)
    if proxy == "system":
        return HttpxClient(trust_env=True, timeout=timeout)
    return HttpxClient(proxy=proxy, trust_env=False, timeout=timeout)


def generate_image(provider, model, prompt, size="1024*1024", name="", user_id=""):
    """文生图，返回图片字节。

    按 base_url 自动选择协议：
    - 百炼（dashscope）：原生异步任务接口（text2image），轮询任务状态后下载图片；
    - 其他 OpenAI 兼容服务商：调用 /images/generations。
    """
    start = time.time()
    try:
        base = (provider.get("base_url") or "").strip().lower()
        if "dashscope" in base:
            data = _gen_image_dashscope(provider, model, prompt, size)
        else:
            data = _gen_image_openai(provider, model, prompt, size)
        _log_request("image", provider, model, prompt,
                     status="ok", elapsed=time.time() - start, name=name, user_id=user_id)
        return data
    except AIClientError as e:
        _log_request("image", provider, model, prompt,
                     status="error", elapsed=time.time() - start, error=str(e), name=name, user_id=user_id)
        raise
    except Exception as e:  # noqa: BLE001
        _log_request("image", provider, model, prompt,
                     status="error", elapsed=time.time() - start, error=str(e), name=name, user_id=user_id)
        raise AIClientError(_friendly_error(e)) from e


def _gen_image_dashscope(provider, model, prompt, size):
    """百炼原生文生图：提交异步任务 → 轮询任务状态 → 下载图片。"""
    m = re.match(r"(https?://[^/]+)", (provider.get("base_url") or "").strip())
    root = m.group(1) if m else "https://dashscope.aliyuncs.com"
    api_key = provider.get("api_key", "")
    headers = {"Authorization": f"Bearer {api_key}", "X-DashScope-Async": "enable"}
    body = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {"size": size, "n": 1},
    }
    with _http_client(provider) as client:
        r = client.post(root + "/api/v1/services/aigc/text2image/image-synthesis",
                        headers=headers, json=body)
        if r.status_code >= 400:
            raise Exception(f"{r.status_code} {r.text[:300]}")
        task_id = (r.json().get("output") or {}).get("task_id")
        if not task_id:
            raise Exception("百炼未返回 task_id：" + r.text[:200])

        deadline = time.time() + 300
        while time.time() < deadline:
            time.sleep(2)
            tr = client.get(root + f"/api/v1/tasks/{task_id}",
                            headers={"Authorization": f"Bearer {api_key}"})
            out = (tr.json() or {}).get("output") or {}
            status = out.get("task_status")
            if status == "SUCCEEDED":
                results = out.get("results") or []
                item = results[0] if results else {}
                if item.get("url"):
                    img = client.get(item["url"])
                    if img.status_code >= 400:
                        raise Exception(f"图片下载失败：{img.status_code}")
                    return img.content
                if item.get("b64_image"):
                    return base64.b64decode(item["b64_image"])
                raise Exception("百炼返回的图片结果缺少数据：" + str(out)[:200])
            if status in ("FAILED", "UNKNOWN"):
                raise Exception(f"百炼生图任务失败：{out.get('message') or out.get('code') or status}")
        raise Exception("百炼生图任务超时（300 秒），请稍后重试")


def _gen_image_openai(provider, model, prompt, size):
    """OpenAI 兼容文生图：POST /images/generations，支持 url 或 b64_json 两种返回。"""
    base = (provider.get("base_url") or "").rstrip("/")
    body = {"model": model, "prompt": prompt, "size": size.replace("*", "x"), "n": 1}
    with _http_client(provider) as client:
        r = client.post(base + "/images/generations",
                        headers={"Authorization": f"Bearer {provider.get('api_key', '')}"},
                        json=body)
        if r.status_code >= 400:
            raise Exception(f"{r.status_code} {r.text[:300]}")
        data = (r.json() or {}).get("data") or []
        if not data:
            raise Exception("图片生成接口未返回结果")
        item = data[0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            img = client.get(item["url"])
            if img.status_code >= 400:
                raise Exception(f"图片下载失败：{img.status_code}")
            return img.content
        raise Exception("图片生成接口未返回图片数据")


def list_models(provider):
    """拉取服务商的模型列表，返回去重排序后的模型 id 列表。"""
    try:
        client = _build_client(provider)
        resp = client.models.list()
        return sorted({m.id for m in resp.data})
    except Exception as e:  # noqa: BLE001
        raise AIClientError(_friendly_error(e)) from e


def test_connection(provider, model, vision=False, image=False):
    """测试连通性，返回 (ok, message)。"""
    try:
        if image:
            # 图片模型：实际生成一张小图验证（会消耗少量额度）
            generate_image(provider, model, "a cute orange cat")
            return True, f"连接成功（{model}）"
        if vision:
            # 视觉测试用 1x1 纯色占位图
            tiny = (
                "/9j/4AAQSkZJRgABAQEAAAAAAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkS"
                "Ew8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAAB"
                "AAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAA"
                "AAD/2gAIAQEAAD8AKp//2Q=="
            )
            chat_vision(provider, model, "看到什么", tiny, max_tokens=16)
        else:
            chat_text(
                provider,
                model,
                [{"role": "user", "content": "回复 OK 两个字即可。"}],
                max_tokens=16,
            )
        return True, f"连接成功（{model}）"
    except AIClientError as e:
        return False, str(e)


def _friendly_error(e):
    msg = str(e)
    # 提取服务端返回的错误信息片段，去掉冗长的堆栈
    if "401" in msg or "Unauthorized" in msg or "authentication" in msg.lower():
        return "鉴权失败(401)：请检查 API Key 是否正确。"
    if "404" in msg or "model_not_found" in msg or "not found" in msg.lower():
        return "模型或接口地址(404)不存在：请检查 base_url 与模型名。"
    if "429" in msg or "rate" in msg.lower() or "quota" in msg.lower():
        return "额度/频率受限(429)：请检查账户余额或限流。"
    if "timeout" in msg.lower() or "timed out" in msg.lower():
        return "请求超时：网络或服务商响应过慢。"
    if "connection" in msg.lower() or "refused" in msg.lower():
        return "网络连接失败：请检查 base_url 是否能访问。"
    # 截断超长错误
    return ("调用失败：" + msg) if len(msg) <= 300 else ("调用失败：" + msg[:300] + "…")
