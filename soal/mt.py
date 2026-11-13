"""Traducao automatica opcional, feita pelo servico que o usuario escolher.

Servicos:
  deepl      DeepL API (Free ou Pro), com chave
  google     Google Cloud Translation v2, com chave
  libre      LibreTranslate (servidor proprio ou publico)
  openai     qualquer servidor compativel com a API do OpenAI: Ollama e LM Studio no
             proprio PC, OpenAI, OpenRouter...
  anthropic  Claude, pela API da Anthropic, com chave

Os servicos de modelo de linguagem (openai, anthropic) recebem instrucoes de estilo, o
glossario do projeto, quem fala e a fala anterior, para adaptar expressoes e acertar o
genero. DeepL recebe quem fala e a fala anterior como contexto. Google e LibreTranslate
traduzem so' o texto.

Tudo usa urllib (biblioteca padrao). A chave fica no arquivo de configuracao do usuario,
nunca no projeto.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

PROVIDERS = {
    "deepl": "DeepL",
    "google": "Google Cloud Translation",
    "libre": "LibreTranslate",
    "openai": "Ollama / LM Studio / OpenAI (compatível com OpenAI)",
    "anthropic": "Claude (API da Anthropic)",
}

DEFAULTS = {
    "provider": "",
    "key": "",
    "url": "",
    "model": "",
    "timeout": 90,
}

# Servidor no proprio PC ou na rede de casa (Ollama, LM Studio): o modelo pode demorar para
# carregar e para responder, entao o tempo de espera sem receber nada e' maior.
LOCAL_TIMEOUT = 300

CODE_RE = re.compile(r"\\[a-z]")


class MTError(Exception):
    """kind: "conexao" (sem resposta / tempo esgotado), "fatal" (chave recusada, cota ou limite
    de uso: nao adianta insistir) ou "" (erro so' desta fala)."""

    def __init__(self, msg: str = "", kind: str = ""):
        super().__init__(msg)
        self.kind = kind


def _load(name: str):
    try:
        with open(os.path.join(_DATA_DIR, name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


GLOSSARY: List[List[str]] = _load("glossario_ptbr.json").get("termos", [])
GENDER: Dict[str, str] = _load("glossario_ptbr.json").get("genero", {})


# ------------------------------------------------------------------ marcadores
def protect(text: str) -> Tuple[str, List[str]]:
    """Troca os codigos do jogo (\\c, \\e...) por marcadores [[1]], [[2]]... que os
    tradutores preservam."""
    codes: List[str] = []

    def sub(m):
        codes.append(m.group(0))
        return f"[[{len(codes)}]]"
    return CODE_RE.sub(sub, text), codes


def restore(text: str, codes: List[str]) -> str:
    for i, c in enumerate(codes, 1):
        pat = re.compile(r"\[\[\s*" + str(i) + r"\s*\]\]")
        if not pat.search(text):
            raise MTError("o tradutor removeu um código do jogo; traduza esta fala à mão")
        text = pat.sub(lambda _m, c=c: c, text, count=1)
    if re.search(r"\[\[\s*\d+\s*\]\]", text):
        raise MTError("o tradutor duplicou um código do jogo; traduza esta fala à mão")
    return text


def glossary_for(text: str, extra: Optional[List[List[str]]] = None) -> List[List[str]]:
    low = text.lower()
    out = []
    for en, pt in (extra or []) + GLOSSARY:
        keys = [re.sub(r"\(.*?\)", "", k).strip().lower() for k in re.split(r"/|,", en)]
        keys = [k for k in keys if len(k) > 1]
        if any(k and k in low for k in keys):
            out.append([en, pt])
    return out[:25]


# ------------------------------------------------------------------ http
def _is_local(url: str) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host in ("localhost", "::1") or host.endswith(".local") or host.startswith("127."):
        return True
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    m = re.match(r"172\.(\d+)\.", host)
    return bool(m and 16 <= int(m.group(1)) <= 31)


def _read_stream(r) -> dict:
    """Le uma resposta em pedacos (server-sent events) de /chat/completions."""
    content, reasoning, finish = [], 0, None
    for raw in r:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            ev = json.loads(data)
        except ValueError:
            continue
        if ev.get("error"):
            raise MTError("o servidor respondeu com erro: " + json.dumps(ev["error"], ensure_ascii=False)[:200])
        for ch in ev.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content"):
                content.append(d["content"])
            for k in ("reasoning_content", "reasoning"):
                if isinstance(d.get(k), str):
                    reasoning += len(d[k])
            finish = ch.get("finish_reason") or finish
    return {"content": "".join(content), "reasoning_chars": reasoning, "finish": finish}


def _post(url: str, payload: dict, headers: Dict[str, str], timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            if "event-stream" in (r.headers.get("Content-Type") or ""):
                return {"_stream": _read_stream(r)}
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        if e.code in (401, 403):
            raise MTError(f"o serviço recusou a chave (HTTP {e.code}). Confira a chave em Ajustes.", "fatal")
        if e.code == 429:
            raise MTError("limite de uso do serviço atingido (HTTP 429). Espere um pouco e tente de novo.", "fatal")
        if e.code == 456:
            raise MTError("a cota de caracteres da sua conta acabou (HTTP 456).", "fatal")
        raise MTError(f"o serviço respondeu HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise MTError(f"não consegui falar com o serviço ({e.reason}). Confira o endereço e a internet.", "conexao")
    except (TimeoutError, OSError) as e:
        extra = (" O servidor ficou {} s sem mandar nada: confira se o modelo está carregado e se cabe "
                 "na memória da placa de vídeo.".format(timeout)) if _is_local(url) else ""
        raise MTError(f"o serviço demorou demais ou caiu ({e}).{extra}", "conexao")
    except ValueError:
        raise MTError("o serviço respondeu algo que não é JSON.")


# ------------------------------------------------------------------ instrucoes
STYLE = (
    "Você é tradutor de videogames e localiza o RPG Skies of Arcadia Legends do inglês para o "
    "português do Brasil. Regras:\n"
    "1. Não traduza ao pé da letra: adapte expressões idiomáticas, gírias e piadas para "
    "equivalentes naturais no Brasil (ex.: 'a piece of cake' -> 'moleza'; 'cost an arm and a leg' "
    "-> 'custar os olhos da cara'; 'so far, so good' -> 'até aqui, tudo bem').\n"
    "2. Adapte o jeito de falar dos piratas para termos de marujo usados no Brasil (ex.: 'Aye' -> "
    "'Às ordens'/'Sim'; 'lad' -> 'rapaz'; 'landlubber' -> 'rato de terra firme').\n"
    "3. Concordância de gênero: use o gênero de quem fala informado abaixo e o contexto para "
    "saber com quem se fala. Quando não der para saber, prefira frases neutras.\n"
    "4. Mantenha nomes próprios de personagens, navios e lugares que não estiverem no glossário. "
    "Siga o glossário quando o termo aparecer.\n"
    "5. Use 'você'. Nobres e oficiais tratam superiores por 'senhor'/'senhora'.\n"
    "6. Seja conciso: a caixa de diálogo tem 3 linhas de 48 caracteres (cerca de 140 caracteres).\n"
    "7. Preserve exatamente os marcadores [[1]], [[2]]... e as reticências '…'.\n"
    "8. Responda SOMENTE com a tradução, sem aspas extras, sem comentários e sem explicações."
)


def build_prompt(text: str, who: Optional[str], prev: Optional[str], menu: bool,
                 extra_glossary: Optional[List[List[str]]] = None) -> str:
    parts = []
    if who:
        g = GENDER.get(who)
        parts.append(f"Quem fala: {who}" + (f" ({'homem' if g == 'M' else 'mulher'})" if g in ("M", "F") else ""))
    if prev:
        parts.append(f"Fala anterior (só contexto, não traduza): {prev}")
    gl = glossary_for(text + " " + (who or ""), extra_glossary)
    if gl:
        parts.append("Glossário:\n" + "\n".join(f"- {a} = {b}" for a, b in gl))
    if menu:
        parts.append("Este texto é um menu de escolhas: traduza cada linha separadamente, mantenha "
                     "a mesma quantidade de linhas e as aspas “ ” de cada opção.")
    parts.append("Texto para traduzir:\n" + text)
    return "\n\n".join(parts)


def _clean_llm(out: str) -> str:
    # modelos que "pensam" em voz alta: descarta o raciocinio
    out = re.sub(r"(?s)<(think|thinking|reasoning)>.*?</\1>", "", out)
    out = re.sub(r"(?s)^.*?</(think|thinking)>", "", out) if re.search(r"</(think|thinking)>", out) else out
    out = out.strip()
    out = re.sub(r"^```[a-z]*\n?|\n?```$", "", out).strip()
    for p in ("Tradução:", "Traducao:", "Tradução", "Translation:"):
        if out.startswith(p):
            out = out[len(p):].strip()
    if len(out) > 1 and out[0] == out[-1] == '"':
        out = out[1:-1]
    return out


# ------------------------------------------------------------------ servicos
class Translator:
    def __init__(self, cfg: dict):
        self.cfg = dict(DEFAULTS)
        self.cfg.update(cfg or {})
        self.provider = self.cfg.get("provider") or ""
        if self.provider not in PROVIDERS:
            raise MTError("Escolha um serviço de tradução automática em Ajustes.")
        self.timeout = int(self.cfg.get("timeout") or 90)
        # um tempo escolhido de proposito vale tambem para servidor local
        self.timeout_explicit = bool((cfg or {}).get("timeout"))

    def translate(self, text: str, who: Optional[str] = None, prev: Optional[str] = None,
                  menu: bool = False, extra_glossary: Optional[List[List[str]]] = None) -> str:
        """text vem com as quebras de linha do jogo como '\\n'. Devolve no mesmo formato."""
        if not text.strip():
            return ""
        src, codes = protect(text)
        if menu:
            lines = src.split("\n")
        else:
            lines = [" ".join(l.strip() for l in src.split("\n"))]
        fn = getattr(self, "_" + self.provider)
        if self.provider in ("openai", "anthropic"):
            out = fn("\n".join(lines), who, prev, menu, extra_glossary)
            if menu:
                got = [l for l in out.split("\n") if l.strip()]
                if len(got) != len(lines):
                    raise MTError("o tradutor mudou a quantidade de opções do menu")
                out = "\n".join(got)
        else:
            res = fn(lines, who, prev)
            out = "\n".join(res)
        return restore(out, codes).strip()

    # -- DeepL ---------------------------------------------------------------
    def _deepl(self, lines: List[str], who, prev) -> List[str]:
        key = (self.cfg.get("key") or "").strip()
        if not key:
            raise MTError("Informe a chave da DeepL em Ajustes.")
        base = (self.cfg.get("url") or "").strip().rstrip("/") or (
            "https://api-free.deepl.com" if key.endswith(":fx") else "https://api.deepl.com")
        ctx = []
        if who:
            ctx.append(f"{who} is speaking in a fantasy pirate role-playing game.")
        if prev:
            ctx.append(f"Previous line: {prev}")
        payload = {"text": lines, "source_lang": "EN", "target_lang": "PT-BR",
                   "formality": "prefer_less", "preserve_formatting": True}
        if ctx:
            payload["context"] = " ".join(ctx)
        r = _post(base + "/v2/translate", payload, {"Authorization": "DeepL-Auth-Key " + key}, self.timeout)
        try:
            return [t["text"] for t in r["translations"]]
        except (KeyError, TypeError):
            raise MTError("resposta inesperada da DeepL")

    # -- Google ---------------------------------------------------------------
    def _google(self, lines: List[str], who, prev) -> List[str]:
        key = (self.cfg.get("key") or "").strip()
        if not key:
            raise MTError("Informe a chave do Google Cloud em Ajustes.")
        base = (self.cfg.get("url") or "").strip().rstrip("/") or "https://translation.googleapis.com"
        url = base + "/language/translate/v2?key=" + urllib.request.quote(key)
        r = _post(url, {"q": lines, "source": "en", "target": "pt-BR", "format": "text"}, {}, self.timeout)
        try:
            return [t["translatedText"] for t in r["data"]["translations"]]
        except (KeyError, TypeError):
            raise MTError("resposta inesperada do Google")

    # -- LibreTranslate -------------------------------------------------------
    def _libre(self, lines: List[str], who, prev) -> List[str]:
        base = (self.cfg.get("url") or "").strip().rstrip("/")
        if not base:
            raise MTError("Informe o endereço do servidor LibreTranslate em Ajustes.")
        payload = {"q": lines, "source": "en", "target": (self.cfg.get("model") or "pt").strip(), "format": "text"}
        if self.cfg.get("key"):
            payload["api_key"] = self.cfg["key"].strip()
        r = _post(base + "/translate", payload, {}, self.timeout)
        t = r.get("translatedText") if isinstance(r, dict) else None
        if isinstance(t, list):
            return t
        if isinstance(t, str):
            return [t]
        raise MTError("resposta inesperada do LibreTranslate: " + str(r.get("error", r))[:200])

    # -- compativel com OpenAI (Ollama, LM Studio, OpenAI...) -----------------
    def _openai(self, text: str, who, prev, menu, extra) -> str:
        base = (self.cfg.get("url") or "").strip().rstrip("/") or "http://localhost:11434/v1"
        model = (self.cfg.get("model") or "").strip()
        if not model:
            raise MTError("Informe o nome do modelo em Ajustes (ex.: o nome que aparece em 'ollama list').")
        headers = {}
        if (self.cfg.get("key") or "").strip():
            headers["Authorization"] = "Bearer " + self.cfg["key"].strip()
        local = _is_local(base)
        payload = {"model": model, "temperature": 0.3, "max_tokens": 2048,
                   "messages": [{"role": "system", "content": STYLE},
                                {"role": "user", "content": build_prompt(text, who, prev, menu, extra)}]}
        if local:
            # Em pedacos: enquanto o modelo gera, a conexao nao fica parada esperando.
            payload["stream"] = True
            # Pede para nao "pensar" antes de responder (Ollama e LM Studio recentes).
            payload["reasoning_effort"] = "none"
            payload["think"] = False
        else:
            payload["stream"] = False
        timeout = max(self.timeout, LOCAL_TIMEOUT) if local and not self.timeout_explicit else self.timeout
        url = base + "/chat/completions"
        try:
            r = _post(url, payload, headers, timeout)
        except MTError as e:
            # servidor que nao conhece as opcoes de raciocinio: tenta de novo sem elas
            if local and "HTTP 4" in str(e) and re.search(r"reason|think|effort", str(e), re.I):
                for k in ("reasoning_effort", "think"):
                    payload.pop(k, None)
                r = _post(url, payload, headers, timeout)
            else:
                raise
        if "_stream" in r:
            st = r["_stream"]
            out = _clean_llm(st["content"])
            if not out:
                if st["reasoning_chars"]:
                    raise MTError("o modelo gastou a resposta inteira \"pensando\" e não traduziu. Desligue o "
                                  "raciocínio (thinking) do modelo no LM Studio/Ollama ou use outro modelo.")
                raise MTError("o servidor respondeu vazio. Confira o nome do modelo em Ajustes.")
            return out
        try:
            msg = r["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise MTError("resposta inesperada do servidor: " + json.dumps(r)[:200])
        out = _clean_llm(msg.get("content") or "")
        if not out and (msg.get("reasoning_content") or msg.get("reasoning")):
            raise MTError("o modelo gastou a resposta inteira \"pensando\" e não traduziu. Desligue o "
                          "raciocínio (thinking) do modelo ou use outro modelo.")
        if not out:
            raise MTError("o servidor respondeu vazio. Confira o nome do modelo em Ajustes.")
        return out

    # -- Claude ---------------------------------------------------------------
    def _anthropic(self, text: str, who, prev, menu, extra) -> str:
        key = (self.cfg.get("key") or "").strip()
        if not key:
            raise MTError("Informe a chave da API da Anthropic em Ajustes.")
        base = (self.cfg.get("url") or "").strip().rstrip("/") or "https://api.anthropic.com"
        model = (self.cfg.get("model") or "").strip() or "claude-sonnet-5-5"
        payload = {"model": model, "max_tokens": 1024, "system": STYLE,
                   "messages": [{"role": "user", "content": build_prompt(text, who, prev, menu, extra)}]}
        r = _post(base + "/v1/messages", payload,
                  {"x-api-key": key, "anthropic-version": "2023-06-01"}, self.timeout)
        try:
            return _clean_llm("".join(b.get("text", "") for b in r["content"] if b.get("type") == "text"))
        except (KeyError, TypeError):
            raise MTError("resposta inesperada da Anthropic: " + json.dumps(r)[:200])


# Campos que cada servico usa (os mesmos que a tela mostra).
FIELDS = {"deepl": ("key",), "google": ("key",), "libre": ("url", "model", "key"),
          "openai": ("url", "model", "key"), "anthropic": ("key", "model")}


def effective_config(cfg: dict) -> dict:
    """So' os campos que o servico escolhido usa. Evita, por exemplo, que o endereco do LM Studio
    salvo antes seja usado pela DeepL depois da troca de servico."""
    c = dict(cfg or {})
    c.pop("salvos", None)
    used = FIELDS.get(c.get("provider") or "", ())
    for f in ("key", "url", "model"):
        if f not in used:
            c.pop(f, None)
    return c


def _hint(k: str) -> str:
    return ("…" + k[-4:]) if len(k) >= 8 else ("definida" if k else "")


def public_config(cfg: dict) -> dict:
    """Configuracao para mostrar na tela, sem expor a chave."""
    c = dict(DEFAULTS)
    c.update(effective_config(cfg))
    k = c.get("key") or ""
    c["key"] = ""
    c["has_key"] = bool(k)
    c["key_hint"] = _hint(k)
    c["providers"] = PROVIDERS
    # o que ficou guardado de cada servico, para a tela mostrar ao trocar (sem as chaves)
    salvos = {}
    for prov, v in ((cfg or {}).get("salvos") or {}).items():
        if isinstance(v, dict):
            salvos[prov] = {"url": v.get("url") or "", "model": v.get("model") or "",
                            "has_key": bool(v.get("key")), "key_hint": _hint(v.get("key") or "")}
    cur = (cfg or {}).get("provider")
    if cur:
        salvos[cur] = {"url": c.get("url") or "", "model": c.get("model") or "",
                       "has_key": c["has_key"], "key_hint": c["key_hint"]}
    c["salvos"] = salvos
    return c
