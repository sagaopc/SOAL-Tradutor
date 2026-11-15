"""Sugestoes de traducao para nomes curtos: itens, armas, pecas do navio, lugares e NPCs
genericos ("Valuan Soldier", "Boomerang", "Sacri Crystal").

Nao e' traducao automatica: e' um vocabulario fixo (data/vocabulario.json) com regras do
portugues. Em ingles o nome principal vem no fim ("Valuan Soldier"); em portugues vem no
comeco, com os adjetivos depois e concordando no genero ("Soldado Valuano"). Nomes proprios
(Sacri, Yafutoma) ficam como estao, depois do substantivo ("Cristal Sacri"). Complementos
viram "de"/"do"/"da" ("Iron Ring" = "Anel de Ferro", "Storm Cannon" = "Canhao da
Tempestade"); possessivos tambem ("Aika's Shorts" = "Shorts da Aika").

A sugestao e' um ponto de partida para o tradutor revisar. Palavra desconhecida fica em
ingles e a sugestao sai marcada como incompleta.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Tuple

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vocabulario.json")
_V = None

# nomes da casa: so' o que o tradutor ve como sec "nome" (e afins) recebe sugestao
NAME_SECS = {"nome", "personagem", "título do Vyse", "procurado", "lenda", "descoberta", "ilha",
             "loja", "golpe inimigo", "ação de navio inimigo", "lugar do save", "mapa", "tripulação",
             "ação do navio", "navio"}


def _v() -> dict:
    global _V
    if _V is None:
        with open(DATA, encoding="utf-8") as fh:
            _V = json.load(fh)
    return _V


ROMAN = re.compile(r"^(?:[IVX]+|\d+|[A-Z]\d*|\+\d+)$")
TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]*|\d+|\S")


def _plural_pt(w: str) -> str:
    if " " in w:
        a, b = w.split(" ", 1)
        return _plural_pt(a) + " " + b
    if w.endswith("ão"):
        return w[:-2] + "ões"
    if w.endswith(("r", "z", "s")):
        return w + ("es" if not w.endswith("s") else "")
    if w.endswith("l"):
        return w[:-1] + "is"
    if w.endswith("m"):
        return w[:-1] + "ns"
    return w + "s"


def _noun(word: str) -> Optional[Tuple[str, str, Optional[str], bool]]:
    """(portugues, genero, feminino, plural) ou None."""
    n = _v()["nomes"]
    w = word.lower()
    if w in n:
        x = n[w]
        return x[0], x[1], (x[2] if len(x) > 2 else None), False
    for suf, cut in (("ies", "y"), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) > len(suf) + 2:
            base = w[:-len(suf)] + cut
            if base in n:
                x = n[base]
                return _plural_pt(x[0]), x[1], (_plural_pt(x[2]) if len(x) > 2 and x[2] else None), True
    return None


def _adj(word: str):
    return _v()["adjetivos"].get(word.lower())


def _article(g: str, plural: bool) -> str:
    return {("m", False): "do", ("f", False): "da", ("m", True): "dos", ("f", True): "das"}[(g, plural)]


def _is_proper(tok: str) -> bool:
    return tok[:1].isupper() and _noun(tok) is None and _adj(tok) is None


def suggest(name: str, genders: Optional[Dict[str, str]] = None,
            known: Optional[Dict[str, str]] = None) -> Optional[dict]:
    """Sugere uma traducao. genders: genero de personagens ("Aika": "F"); known: nomes ja'
    traduzidos pelo usuario (usados nos possessivos). Devolve {"t": texto, "ok": completa}
    ou None quando nao ha' o que sugerir (nome proprio sozinho, por exemplo)."""
    genders = genders or {}
    known = known or {}
    raw = name
    s = name.strip()
    if not s or len(s) > 40 or "\n" in s:
        return None
    lead = raw[:len(raw) - len(raw.lstrip(" "))]
    trail = raw[len(raw.rstrip(" ")):]
    out = _phrase(s, genders, known)
    if out is None:
        return None
    t, ok = out
    if t == s:
        return None
    return {"t": lead + t + trail, "ok": ok}


FUNCTION_WORDS = {"you", "your", "do", "does", "did", "to", "in", "is", "are", "what", "where", "how",
                  "will", "would", "want", "from", "with", "and", "or", "for", "it", "this", "that",
                  "some", "i", "me", "my", "we", "be", "at", "on", "by", "about", "which", "who"}


def _phrase(s: str, genders, known) -> Optional[Tuple[str, bool]]:
    v = _v()
    low = s.lower()
    if low in v["expressoes"]:
        return v["expressoes"][low], True
    words = re.findall(r"[A-Za-z']+", low)
    if "?" in s or "!" in s or len(words) > 6 or FUNCTION_WORDS.intersection(words):
        return None                      # frase, nao nome
    m = re.match(r"^(?:the|an?)\s+(.+)$", s, re.I)
    if m:
        return _phrase(m.group(1), genders, known)
    # "Briggs the Vice Captain" = "Briggs, o Vice-Capitao"
    m = re.match(r"^(\S+)\s+the\s+(.+)$", s, re.I)
    if m:
        t = _phrase(m.group(2), genders, known)
        if not t and len(m.group(2).split()) == 1 and _adj(m.group(2)):
            a = _adj(m.group(2))
            f = genders.get(m.group(1)) == "F"
            return f"{m.group(1)}, {'a' if f else 'o'} {a[1] if f else a[0]}", True
        if not t:
            return None
        hn = _noun(m.group(2).split()[-1])
        art = "a" if (hn and hn[1] == "f") or genders.get(m.group(1)) == "F" else "o"
        return f"{m.group(1)}, {art} {t[0]}", t[1]
    # "A of the B" / "A of B"
    m = re.match(r"^(.+?)\s+of\s+(the\s+)?(.+)$", s, re.I)
    if m:
        a = _phrase(m.group(1), genders, known)
        b = _phrase(m.group(3), genders, known)
        if a is None:
            return None
        bt, bok = b if b else (m.group(3), not _has_unknown(m.group(3)))
        head = _noun(m.group(3).split()[-1])
        if head and (m.group(2) or not _is_proper(m.group(3).split()[0])):
            prep = _article(head[1], head[3])
        else:
            prep = "de"
        return f"{a[0]} {prep} {bt}", a[1] and bok
    # possessivo: "Aika's Shorts", "Warrior's Heart", "Sailors' Guild"
    m = re.match(r"^(.+?)'s\s+(.+)$", s) or re.match(r"^(.+?s)'\s+(.+)$", s)
    if m:
        o, thing = m.group(1).strip(), m.group(2)
        b = _phrase(thing, genders, known)
        if b is None:
            return None
        if o in known:
            return f"{b[0]} de {known[o]}", b[1]
        if o in genders:
            return f"{b[0]} {'do' if genders[o] == 'M' else 'da'} {o}", b[1]
        on = _noun(o) if " " not in o else None
        if on:
            return f"{b[0]} {_article(on[1], on[3])} {on[0]}", b[1]
        if _is_proper(o.split()[0]):
            return f"{b[0]} de {o}", b[1]
        ot = _phrase(o, genders, known)
        return f"{b[0]} de {ot[0] if ot else o}", b[1] and bool(ot and ot[1])
    return _compound(s)


def _has_unknown(s: str) -> bool:
    for tok in TOKEN.findall(s):
        if not tok[0].isalpha() or ROMAN.match(tok):
            continue
        if _noun(tok) is None and _adj(tok) is None and not tok[:1].isupper():
            return True
    return False


def _compound(s: str) -> Optional[Tuple[str, bool]]:
    v = _v()
    toks = s.split()
    # sufixos que ficam no fim: numeros, II, +1, "Mk2"
    tail = []
    while toks and ROMAN.match(toks[-1]):
        tail.insert(0, toks.pop())
    if not toks:
        return None
    # expressao no fim ("Old Man", "Moon Stone") vira a cabeca
    head = None
    for k in range(min(4, len(toks)), 1, -1):
        exp = " ".join(toks[-k:]).lower()
        if exp in v["expressoes"]:
            pt = v["expressoes"][exp]
            first = pt.split()[0]
            fn = _noun(first)
            head = (pt, fn[1] if fn else "m", None, False)
            toks = toks[:-k]
            break
    female = False
    if head is None:
        last = toks.pop()
        nn = _noun(last)
        if nn is None:
            # sem substantivo conhecido no fim: so' adjetivos/nome proprio -> nada a sugerir
            if len(toks) == 0:
                return None
            toks.append(last)
            return _loose(toks + tail)
        head = nn
    pt, g, fem, plural = head
    if toks and toks[0].lower() == "female" and fem:
        pt, g = fem, "f"
        toks = toks[1:]
        female = True
    elif toks and toks[0].lower() == "female":
        toks = toks[1:]
        female = True
    pre, post_adj, comps, proper = [], [], [], []
    ok = True
    for tok in toks:
        lw = tok.lower()
        a = _adj(lw)
        is_mat = lw in v["materiais"]
        nn = _noun(lw)
        if a and not (is_mat and nn):
            word = a[1] if g == "f" else a[0]
            if plural and not word.startswith("de ") and not word.startswith("do "):
                word = _plural_pt(word)
            if a[2] == "pre":
                pre.append(word)
            else:
                post_adj.append(word)
        elif nn:
            if is_mat:
                comps.append("de " + nn[0])
            else:
                comps.append(_article(nn[1], nn[3]) + " " + nn[0])
        elif tok[:1].isupper() or not tok[:1].isalpha():
            proper.append(tok)
        else:
            proper.append(tok)
            ok = False
    words = []
    for w in pre:
        if w.endswith("-"):
            words.append(w)
        else:
            words.append(w + " ")
    text = "".join(words) + pt
    text = text.replace("- ", "-")
    rest = post_adj + comps + proper + tail
    if rest:
        text += " " + " ".join(rest)
    if female and not fem:
        text += " (mulher)"
    return text.strip(), ok


def _loose(toks: List[str]) -> Optional[Tuple[str, bool]]:
    """Sem substantivo no fim: traduz palavra por palavra o que conhecer."""
    out, changed, ok = [], False, True
    for tok in toks:
        nn = _noun(tok)
        a = _adj(tok)
        if nn:
            out.append(nn[0])
            changed = True
        elif a:
            out.append(a[0])
            changed = True
        else:
            out.append(tok)
            if not tok[:1].isupper() and tok[:1].isalpha():
                ok = False
    if not changed:
        return None
    return " ".join(out), ok
