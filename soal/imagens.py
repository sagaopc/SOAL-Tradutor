"""Imagens com texto: catalogo das texturas do jogo que trazem palavras desenhadas
(logotipo, aviso, GAME OVER, comandos de batalha, lojas, mapa-mundi) e a gravacao das
imagens editadas.

Cada edicao e' guardada no projeto como PNG, com a chave da textura original (um hash dos
pixels). Assim a mesma imagem que aparece em varios arquivos (os nomes das regioes estao nos
16 arquivos do mapa-mundi, os numeros estao em varias telas) e' traduzida uma vez so'.

Na versao europeia cada imagem tem uma copia por idioma. A edicao parte da copia em ingles e
vai para a copia do idioma escolhido em Configuracoes (o mesmo das falas).
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional

from . import textura

# (arquivo na versao americana, rotulo, texturas com texto ou None = todas, o que esta' escrito)
GROUPS = [
    ("Tela-título e abertura", [
        ("title/ts900000.mld", "Logotipo da tela-título", {0: "SKIES OF ARCADIA LEGENDS · New Game · Continue · Homepage · PRESS START"}),
        ("title/title0.mld", "Logotipo pequeno", {8: "SKIES OF ARCADIA LEGENDS · New Game · Continue · Homepage · PRESS START"}),
        ("title/ts900026.mld", "Presented by SEGA", {0: "Presented by SEGA · Created by Overworks"}),
        ("title/warning.mld", "Aviso de luzes piscando", {0: "Flashing lights and similar effects are used in this game…"}),
    ]),
    ("Fim de jogo", [
        ("field/a090a.mld", "GAME OVER", {1: "GAME OVER"}),
    ]),
    ("Batalha", [
        ("battle/command.mld", "Comandos", {15: "Attack · Guard · Run · Item · Focus · S-move · Crew · Magic · wSp.",
                                            18: "ITEM · rich", 27: "Rd Bl Si Gr Pu Ye (cores das Pedras da Lua)"}),
        ("battle/PCWindow.mld", "Janela dos personagens", {2: "Hp · Mp · Lv", 1: "nomes", 17: "nome", 18: "nome", 19: "nome",
                                                            20: "nome", 21: "nome", 22: "nome"}),
        ("battle/stsicon.mld", "Ícones de estado", {11: "MISS", 16: "up · Mp"}),
        ("field/stsicon.mld", "Ícones de estado (campo)", {11: "MISS", 16: "up · Kp"}),
    ]),
    ("Batalha de navios", [
        ("field/HrsBin_sbp.mll", "Comandos do navio", {15: "Attack · Guard · Run · Item · Focus · Crew · S-Can · Magic · non",
                                                       25: "Rd Bl Si Gr Pu Ye", 39: "Hp · Mp · Lv", 38: "nomes",
                                                       43: "nome", 44: "nome", 45: "nome", 46: "nome", 47: "nome", 48: "nome"}),
    ]),
    ("Menus e lojas", [
        ("field/sprite00.mld", "Status, loja e recordes", {0: "Attack · Agility · Will · Power · Dodge% · Defense · Vigor · Quick · Hit% · Spirit · Magic Def…",
                                                           1: "Next · Gold · Gr Rd Bl Pu Ye Si", 4: "Spirit · Time · Money · Gold · Limit · Party",
                                                           5: "MAXHP · MAXMP · MAX · Spirit · Rank · Next · LEVEL UP · NEW RECORD"}),
        ("field/shop_hrse.mll", "Loja", {0: "Attack · Agility · Will · Power · Dodge% · Defense · Vigor · Quick · Hit% · Spirit…",
                                         1: "Next · Gold · Gr Rd Bl Pu Ye Si", 4: "Spirit · Time · Money · Gold · Limit · Party"}),
        ("field/ts000110.gvr", "Tela de menu", {0: "Exp · Magic Exp · LEVEL UP! · RANK UP! …"}),
        ("field/save_hrs.mll", "Gravar jogo", {0: "Lv"}),
        ("field/HrsBin_Hakken.mll", "Descobertas", {3: "Guts · Time · Money · Rich · Party", 4: "MAXHP · MAXKP · MAX · Rank · NEXT · LEVEL UP · NEW RECORD"}),
    ]),
    ("Mapa-múndi", [
        ("field/sekai200.mld", "Nomes das regiões", {15: "Mid Ocean · South Ocean · North Ocean · Valuan Empire · Nasr Kingdom · Ixa'taka Kingdom · Lands of Ice",
                                                    16: "Soltis · Yafutoma · The Dark Rift · Cape Victory · The Vortex · ? · S. Dannel Strait N.",
                                                    17: "lista em letra cursiva", 18: "lista em letra cursiva"}),
    ]),
]
# arquivos com a mesma imagem de outro do catalogo (recebem a traducao junto)
SAME = ["field/sekai%03d.mld" % n for n in range(201, 217)]

# versao europeia: arquivo de cada idioma
_EU_LETTERS = {"en": "", "fr": "f", "de": "g", "es": "s"}
_EU_NUMBERED = {"field/a090a.mld": {"en": "field/a090a0.mld", "fr": "field/a090a1.mld",
                                    "es": "field/a090a2.mld", "de": "field/a090a3.mld"}}
# na versao europeia estes arquivos tem outro conteudo
_EU_OTHER = {"title/ts900000.mld": "Tela de abertura (aviso)", "title/warning.mld": "Tela de abertura"}
_EU_E = {"field/shop_hrse.mll": "field/shop_hrs", "field/save_hrs.mll": "field/save_hrs"}


def eu_variants(rel: str, exists) -> Dict[str, str]:
    """{idioma: arquivo} na versao europeia; vazio se o arquivo nao tem copias por idioma."""
    if rel in _EU_NUMBERED:
        return dict(_EU_NUMBERED[rel])
    if rel in _EU_E:
        stem = _EU_E[rel]
        ext = rel[rel.rindex("."):]
        out = {k: stem + (v or "e") + ext for k, v in _EU_LETTERS.items()}
        return out if all(exists(x) for x in out.values()) else {}
    stem, ext = rel[:rel.rindex(".")], rel[rel.rindex("."):]
    out = {k: stem + v + ext for k, v in _EU_LETTERS.items()}
    return out if all(exists(x) for x in out.values()) else {}


def catalog(eu: bool, exists) -> List[dict]:
    """Grupos com os arquivos que existem no jogo aberto. Cada item: id (arquivo de onde a
    imagem e' lida, em ingles), rotulo, texturas com texto e, na versao europeia, os
    arquivos de cada idioma."""
    out = []
    for label, items in GROUPS:
        g = []
        for rel, name, text in items:
            src, var = rel, {}
            if eu:
                var = eu_variants(rel, exists)
                if var:
                    src = var["en"]
            if not exists(src):
                continue
            if eu and rel in _EU_OTHER:
                name, text = _EU_OTHER[rel], {}
            g.append({"id": src, "label": name, "text": {str(k): v for k, v in text.items()} or None, "var": var})
        if g:
            out.append({"label": label, "items": g})
    return out


def tex_key(tf: "textura.TexFile", n: int) -> str:
    t = tf.tex[n]
    size = textura.level_size(t.fmt, t.w, t.h)
    h = hashlib.sha1(b"%d:%d:%d:" % (t.fmt, t.w, t.h))
    h.update(bytes(tf.data[t.data_off:t.data_off + size]))
    return h.hexdigest()[:20]


def apply(orig: bytes, src: Optional[bytes], edits: Dict[str, "object"], errors: List[str]) -> Optional[bytes]:
    """Aplica as imagens editadas (chave -> imagem do Pillow) ao arquivo `orig`.
    `src` e' o arquivo de onde vieram as chaves (o ingles, na versao europeia); None = o
    proprio orig. Devolve o arquivo novo, ou None se nada mudou."""
    tf = textura.TexFile(orig)
    before = bytes(tf.data)
    ref = tf if src is None else textura.TexFile(src)
    changed = False
    for t in ref.tex:
        if not t.ok:
            continue
        img = edits.get(tex_key(ref, t.n))
        if img is None:
            continue
        if t.n >= len(tf.tex) or (tf.tex[t.n].w, tf.tex[t.n].h) != (t.w, t.h) or not tf.tex[t.n].ok:
            errors.append(f"imagem {t.n}: o arquivo deste idioma é diferente do inglês")
            continue
        tf.set_image(t.n, img)
        changed = True
    if not changed or bytes(tf.data) == before:
        return None
    return tf.build()
