"""Revisao das traducoes por um servico de IA.

A IA recebe um lote de falas em sequencia (original, traducao atual, quem fala) e devolve so' os
problemas: para cada fala, "ok" ou uma traducao corrigida com o tipo do problema e o motivo.
Nada e' trocado sozinho: as sugestoes ficam guardadas na fala (campo "ia") ate' o usuario
aceitar ou recusar.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

from . import mt

TYPES = ("sentido", "português", "concordância", "termo", "nome", "naturalidade", "tamanho")

SYSTEM = (
    "Você revisa a tradução para o português do Brasil do RPG Skies of Arcadia Legends. Para cada "
    "fala, compare o original com a tradução atual e aponte SÓ problemas reais:\n"
    "- sentido: erro de tradução, trecho que falta ou que sobra, sentido invertido;\n"
    "- português: ortografia, acentuação, gramática, regência, crase, pontuação;\n"
    "- concordância: gênero e número (use quem fala, com quem fala e o contexto das falas vizinhas);\n"
    "- termo: termo do glossário traduzido de outro jeito;\n"
    "- nome: nome próprio trocado, traduzido sem estar no glossário ou escrito errado;\n"
    "- naturalidade: palavra deixada em inglês ou espanhol, ou tradução ao pé da letra que soa "
    "estranha no Brasil (adapte expressões e gírias; piratas falam como marujos).\n"
    "Não mude por gosto pessoal: se a tradução está correta e natural, ela está boa, mesmo que você "
    "escrevesse diferente. Mantenha o tom e o jeito de falar do personagem, o tratamento ('você', "
    "'senhor'), os marcadores [[1]], [[2]]... exatamente como estão e as reticências '…'. Não use ¡ "
    "nem ¿. A caixa de diálogo tem 3 linhas de 48 letras: a sugestão não pode ser muito mais longa "
    "que a tradução atual.\n"
    "Responda SOMENTE com um array JSON, um objeto por fala, na mesma ordem e com o mesmo id:\n"
    '{"id": 1, "ok": true} quando estiver boa, ou\n'
    '{"id": 2, "sugestao": "a tradução inteira corrigida", "tipo": "sentido|português|concordância|'
    'termo|nome|naturalidade", "motivo": "explicação curta em português do que estava errado"}'
)


class ReviewItem:
    __slots__ = ("id", "fname", "key", "who", "gender", "body", "src", "t", "menu", "note", "codes",
                 "prot", "keys")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


def build_user(items: List[ReviewItem], glossary: List[List[str]], src_name: str = "") -> str:
    parts = []
    if glossary:
        parts.append("Glossário (use sempre estas traduções):\n" + "\n".join(f"- {a} = {b}" for a, b in glossary))
    rows = []
    for it in items:
        r = {"id": it.id}
        if it.who:
            r["quem fala"] = it.who + (f" ({'homem' if it.gender == 'M' else 'mulher'})" if it.gender in ("M", "F") else "")
        if it.note:
            r["onde aparece"] = it.note
        r["original"] = it.body
        if it.src and src_name:
            r[src_name] = it.src
        r["tradução"] = it.prot
        if it.menu:
            r["menu"] = "opções de escolha: mantenha a mesma quantidade de linhas"
        rows.append(r)
    parts.append("Falas (em sequência, do mesmo trecho do jogo):\n" + json.dumps(rows, ensure_ascii=False, indent=0))
    return "\n\n".join(parts)


def parse(out: str) -> List[dict]:
    """O array JSON da resposta (aceita texto em volta, cercas ``` e objetos soltos)."""
    s = out.strip()
    s = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", s).strip()
    try:
        v = json.loads(s)
    except ValueError:
        a, b = s.find("["), s.rfind("]")
        v = None
        if a >= 0 and b > a:
            try:
                v = json.loads(s[a:b + 1])
            except ValueError:
                v = None
        if v is None:                        # objetos soltos, um por linha
            v = []
            for m in re.finditer(r"\{[^{}]*\}", s):
                try:
                    v.append(json.loads(m.group(0)))
                except ValueError:
                    pass
            if not v:
                raise mt.MTError("a IA não respondeu no formato pedido (JSON)")
    if isinstance(v, dict):
        v = v.get("falas") or v.get("revisao") or v.get("items") or [v]
    return [x for x in v if isinstance(x, dict)]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def check(it: ReviewItem, r: dict) -> Tuple[Optional[str], str, str]:
    """(sugestao com os codigos de volta, tipo, motivo); sugestao None = sem problema ou
    sugestao inaproveitavel."""
    if r.get("ok") is True and not r.get("sugestao"):
        return None, "", ""
    sug = r.get("sugestao") or r.get("sugestão") or r.get("correcao") or ""
    if not isinstance(sug, str) or not sug.strip():
        return None, "", ""
    sug = sug.replace("\r\n", "\n").replace("¡", "").replace("¿", "")
    sug = re.sub(r"…{2,}", "…", sug).strip()
    if _norm(sug) == _norm(it.prot):
        return None, "", ""
    # os marcadores dos codigos do jogo tem de voltar todos, uma vez cada
    want = sorted(re.findall(r"\[\[\d+\]\]", it.prot))
    if sorted(re.findall(r"\[\[\d+\]\]", sug)) != want:
        return None, "", ""
    if it.menu and len([l for l in sug.split("\n") if l.strip()]) != len([l for l in it.prot.split("\n") if l.strip()]):
        return None, "", ""
    tipo = str(r.get("tipo") or "").strip().lower()
    if tipo not in TYPES:
        tipo = {"portugues": "português", "gramatica": "português", "gramática": "português",
                "concordancia": "concordância", "ortografia": "português"}.get(tipo, tipo[:20] or "revisão")
    motivo = str(r.get("motivo") or "").strip()[:400]
    return mt.restore(sug, it.codes), tipo, motivo
