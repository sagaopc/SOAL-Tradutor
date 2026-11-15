"""Termos padronizados: expressoes que se repetem e devem ter sempre a mesma traducao
("Blue Rogues" = "Piratas Azuis").

Cada termo tem as formas em ingles e em portugues (singular / plural) e uma lista de
traducoes diferentes que o botao Padronizar troca pela escolhida. A conferencia aponta as
falas cujo original tem o termo e cuja traducao nao tem nenhuma forma escolhida.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from typing import Dict, List, Optional, Tuple

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "termos_padrao.json")


def defaults() -> List[dict]:
    with open(DATA, encoding="utf-8") as fh:
        return json.load(fh)["termos"]


def forms(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split("/") if x.strip()]


def variants(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def clean(terms) -> List[dict]:
    out = []
    for t in terms or []:
        if not isinstance(t, dict):
            continue
        en, pt = str(t.get("en", "")).strip(), str(t.get("pt", "")).strip()
        if en and pt:
            out.append({"en": en[:200], "pt": pt[:200], "trocar": str(t.get("trocar", "")).strip()[:2000]})
    return out[:500]


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


def _rx(phrase: str) -> "re.Pattern":
    words = [re.escape(w) for w in phrase.split()]
    return re.compile(r"(?<![\w])" + r"[\s\n]+".join(words) + r"(?![\w])", re.I | re.U)


class Checker:
    def __init__(self, terms: List[dict]):
        self.terms = []
        for t in clean(terms):
            en = forms(t["en"])
            pt = forms(t["pt"])
            # o original pode trazer a forma mais longa primeiro ("Blue Rogues" antes de "Blue Rogue")
            self.terms.append({"t": t, "en": [_rx(x) for x in sorted(en, key=len, reverse=True)],
                               "pt": [_rx(x) for x in sorted(pt, key=len, reverse=True)],
                               "ptf": pt, "var": [(v, _rx(v)) for v in sorted(variants(t["trocar"]), key=len, reverse=True)
                                                 if _fold(v) not in {_fold(x) for x in pt}]})

    def missing(self, body: str, t: str) -> List[dict]:
        """Termos que o original tem e a traducao nao segue."""
        out = []
        if not t:
            return out
        for x in self.terms:
            if any(r.search(body) for r in x["en"]) and not any(r.search(t) for r in x["pt"]):
                out.append(x["t"])
        return out

    def issues(self, body: str, t: str) -> List[str]:
        return [f"Termo padronizado: “{m['en']}” é “{m['pt']}”" for m in self.missing(body, t)]

    def fix(self, body: str, t: str) -> Tuple[str, int]:
        """Troca, na traducao, as variantes pelo termo escolhido (so' quando o original tem
        o termo). Devolve o texto novo e quantas trocas fez."""
        n = 0
        for x in self.terms:
            if not any(r.search(body) for r in x["en"]):
                continue
            sing = x["ptf"][0]
            plur = x["ptf"][1] if len(x["ptf"]) > 1 else sing
            for v, rv in x["var"]:
                plural = v.split()[0].lower().endswith("s") and len(x["ptf"]) > 1
                std = plur if plural else sing

                def rep(m, std=std):
                    s = std
                    if m.group(0)[:1].isupper() and s[:1].islower():
                        s = s[:1].upper() + s[1:]
                    return s
                t, k = rv.subn(rep, t)
                n += k
        return t, n
