# -*- coding: utf-8 -*-
"""第 4 步：模型接入层（OpenAI 兼容的 /chat/completions）。

对外只暴露一件事：把 messages 换成「回复文本 + 用量 + 耗时」。协议用 OpenAI 兼容格式，
换模型只改 base_url / model，不动业务代码（需求 1.4②「结构化档案独立于 Agent」）。

凭据解析顺序（先显式、后环境、最后复用本机 DSH 自己的配置）：
  1. 显式参数（--api-key / --base-url / --model）
  2. 环境变量 GROWTH_LLM_API_KEY / GROWTH_LLM_BASE_URL / GROWTH_LLM_MODEL / GROWTH_LLM_PROVIDER
  3. 环境变量 NEORIGIN_API_KEY（DSH 启动模型插件时注入的名字）
  4. ~/.dsh/.credentials.yaml 的 refs 段与 ~/.dsh/profiles/<profile>/cordis.patch.yml
     （本机装了 DSH 时可直接复用它的网关与凭据，密钥只读进内存，不写日志、不落库）

ai_job 只记录 provider 与模型名，不记录密钥。
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://ai-gateway.neorigin.com.cn/v1"
DEFAULT_MODEL = "deepseek-v4-1-flash"
DEFAULT_PROVIDER = "neorigin"
# 推理型模型会先花 token 思考，留足额度，避免只拿到空内容
DEFAULT_MAX_TOKENS = 16384


class LLMError(Exception):
    """模型调用失败。code 直接对应 ai_job.error_code 的取值。"""

    def __init__(self, message, code="model_error", status=None):
        super().__init__(message)
        self.code = code
        self.status = status


class LLMReply:
    def __init__(self, text, usage=None, model=None, duration_ms=0, finish_reason=None, raw=None):
        self.text = text
        self.usage = usage or {}
        self.model = model
        self.duration_ms = duration_ms
        self.finish_reason = finish_reason
        self.raw = raw

    def usage_summary(self):
        """ai_job.token_usage 的口径：input / output / total 三段。"""
        return {
            "input": self.usage.get("prompt_tokens"),
            "output": self.usage.get("completion_tokens"),
            "total": self.usage.get("total_tokens"),
            "cached_input": (self.usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            "reasoning_output": (self.usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        }


class LLMConfig:
    def __init__(self, base_url, model, api_key=None, provider=None, key_source=None,
                 timeout=180, max_tokens=None, profile_config=None):
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.provider = provider or DEFAULT_PROVIDER
        self.key_source = key_source
        self.timeout = timeout
        self.max_tokens = max_tokens or DEFAULT_MAX_TOKENS
        self.profile_config = profile_config or {}

    @property
    def has_key(self):
        return bool(self.api_key)

    def masked_key(self):
        if not self.api_key:
            return None
        if len(self.api_key) <= 10:
            return self.api_key[:2] + "…"
        return self.api_key[:6] + "…" + self.api_key[-4:]

    def describe(self):
        """给人看（与落库）的配置摘要，绝不包含密钥。"""
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "key": self.masked_key(),
            "key_source": self.key_source,
            "timeout": self.timeout,
            "max_tokens": self.max_tokens,
        }


# ---- 本机 DSH 配置读取 ------------------------------------------------
def dsh_home():
    return os.environ.get("DSH_HOME") or os.path.join(os.path.expanduser("~"), ".dsh")


def _read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fp:
            return fp.read()
    except OSError:
        return ""


def dsh_credentials(home=None):
    """读 ~/.dsh/.credentials.yaml 的 refs 段（只取值，不打印）。"""
    text = _read_text(os.path.join(home or dsh_home(), ".credentials.yaml"))
    if not text:
        return {}
    refs = {}
    m = re.search(r"^refs:\s*$", text, re.M)
    if not m:
        return refs
    for line in text[m.end():].splitlines():
        if line and not line[0].isspace():
            break
        mm = re.match(r"\s+([A-Za-z0-9_\-\.]+)\s*:\s*[\"']?([^\"'\s]+)", line)
        if mm:
            refs[mm.group(1)] = mm.group(2)
    return refs


def dsh_profile_config(profile=None, home=None):
    """从 DSH 的 profile 配置里取网关地址、凭据变量名与模型清单。"""
    profile = profile or os.environ.get("DSH_PROFILE") or "desktop"
    path = os.path.join(home or dsh_home(), "profiles", profile, "cordis.patch.yml")
    text = _read_text(path)
    out = {"path": path, "models": []}
    if not text:
        return out
    m = re.search(r"^\s*baseURL:\s*[\"']?([^\"'\s]+)", text, re.M)
    if m:
        out["base_url"] = m.group(1)
    m = re.search(r"^\s*apiKeyEnv:\s*[\"']?([^\"'\s]+)", text, re.M)
    if m:
        out["api_key_env"] = m.group(1)
    out["models"] = re.findall(r"^\s*-\s*id:\s*[\"']?([^\"'\s]+)", text, re.M)
    return out


def resolve_config(model=None, base_url=None, api_key=None, provider=None, timeout=None,
                   max_tokens=None, profile=None):
    """按「显式参数 → 环境变量 → 本机 DSH 配置」的顺序解析出可用配置。"""
    profile_config = dsh_profile_config(profile=profile)
    base_url = (base_url or os.environ.get("GROWTH_LLM_BASE_URL")
                or profile_config.get("base_url") or DEFAULT_BASE_URL)
    model = model or os.environ.get("GROWTH_LLM_MODEL") or DEFAULT_MODEL
    provider = provider or os.environ.get("GROWTH_LLM_PROVIDER") or DEFAULT_PROVIDER
    key_env = profile_config.get("api_key_env") or "NEORIGIN_API_KEY"
    candidates = [
        ("参数 --api-key", api_key),
        ("环境变量 GROWTH_LLM_API_KEY", os.environ.get("GROWTH_LLM_API_KEY")),
        ("环境变量 NEORIGIN_API_KEY", os.environ.get("NEORIGIN_API_KEY")),
        ("环境变量 %s" % key_env, os.environ.get(key_env)),
        ("%s/.credentials.yaml" % dsh_home(), dsh_credentials().get(key_env)),
    ]
    key, source = None, None
    for label, value in candidates:
        if value:
            key, source = value, label
            break
    return LLMConfig(base_url=base_url, model=model, api_key=key, provider=provider,
                     key_source=source,
                     timeout=timeout or int(os.environ.get("GROWTH_LLM_TIMEOUT") or 180),
                     max_tokens=max_tokens, profile_config=profile_config)


def _http_post(url, headers, payload, timeout):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class LLMClient:
    """OpenAI 兼容客户端。transport 可注入，便于离线测试。"""

    def __init__(self, config=None, transport=None):
        self.config = config or resolve_config()
        self.transport = transport or _http_post

    # ---- 调用 -------------------------------------------------------
    def chat(self, messages, max_tokens=None, temperature=None, json_object=False, timeout=None):
        cfg = self.config
        if not cfg.api_key:
            raise LLMError(
                "没有可用的模型凭据。请设置环境变量 GROWTH_LLM_API_KEY（或 NEORIGIN_API_KEY），"
                "或在本机 DSH 配置好 provider 后重试", code="invalid_input")
        payload = {
            "model": cfg.model,
            "messages": messages,
            "max_tokens": max_tokens or cfg.max_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % cfg.api_key,
        }
        url = cfg.base_url.rstrip("/") + "/chat/completions"

        started = time.time()
        try:
            raw = self.transport(url, headers, payload, timeout or cfg.timeout)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            code = {401: "invalid_input", 403: "invalid_input", 429: "rate_limited",
                    408: "timeout"}.get(exc.code, "model_error")
            raise LLMError("模型网关返回 HTTP %s：%s" % (exc.code, body), code=code, status=exc.code)
        except urllib.error.URLError as exc:
            reason = str(getattr(exc, "reason", exc))
            code = "timeout" if ("timed out" in reason.lower() or "timeout" in reason.lower()) else "model_error"
            raise LLMError("调用模型失败：%s" % reason, code=code)
        except TimeoutError:
            raise LLMError("调用模型超时（%s 秒）" % (timeout or cfg.timeout), code="timeout")
        except ValueError as exc:  # 网关返回的不是 JSON
            raise LLMError("模型返回不是合法 JSON：%s" % exc, code="parse_failed")

        duration_ms = int((time.time() - started) * 1000)
        try:
            choice = raw["choices"][0]
            message = choice.get("message") or {}
            text = message.get("content") or ""
            finish = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError):
            raise LLMError("模型返回结构异常：%s" % json.dumps(raw, ensure_ascii=False)[:300],
                           code="model_error")
        reply = LLMReply(text=text, usage=raw.get("usage") or {},
                         model=raw.get("model") or cfg.model, duration_ms=duration_ms,
                         finish_reason=finish, raw=raw)
        if not text.strip():
            raise LLMError(
                "模型没有返回内容（finish_reason=%s；推理型模型可能被 max_tokens 截断，"
                "可用 --max-tokens 提高）" % finish, code="parse_failed")
        return reply

    def health_check(self):
        """最小可用性检查：能否拿到一段非空回复。"""
        reply = self.chat([{"role": "user", "content": "只回复两个字：可用"}], max_tokens=1024)
        return reply
