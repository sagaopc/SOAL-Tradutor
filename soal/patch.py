"""Patch de traducao: o trabalho do projeto num arquivo so' (.soalpatch), para levar a traducao
para outro jogo da mesma versao (outra ISO, outra pasta extraida, outro recomp).

O patch nao leva arquivos do jogo nem o texto original: so' as traducoes (com um resumo do
texto em ingles de cada fala, para saber se o jogo de destino tem o mesmo texto), os nomes, os
termos, os ajustes e as imagens que foram editadas. O SOAL Tradutor aplica o patch num projeto
do jogo de destino e grava a traducao nele como faz com o proprio projeto.

Formato: um .zip com
    patch.json       sobre o patch (versao, regiao, contagens, ajustes, nomes)
    traducao.json    {arquivo: {chave: {"t": traducao, "st": estado, "h": resumo do ingles}}}
    imagens.json     {chave da imagem: {"de": [arquivo, n], "w", "h"}}
    imagens/*.png    as imagens editadas
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import time
import zipfile
from typing import Dict, List, Optional

FORMAT = 1
EXT = ".soalpatch"
# ajustes que vao junto (os de pastas e copias de seguranca ficam de fora)
SETTINGS = ("cols", "lines", "accents", "charmap", "autofill", "eu_slot", "intro_font", "termos")


class PatchError(Exception):
    pass


def _h(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def default_name(region: str) -> str:
    return "Skies of Arcadia Legends PT-BR (%s)%s" % ("europeia" if region == "eu" else "americana", EXT)


def create(p, path: str, version: str) -> dict:
    """Grava o patch do projeto `p` em `path`."""
    path = (path or "").strip().strip('"')
    if not path:
        raise PatchError("Escolha onde salvar o patch.")
    if os.path.isdir(path):
        path = os.path.join(path, default_name(p.meta.get("region", "us")))
    if not path.lower().endswith(EXT):
        path += EXT
    tr: Dict[str, Dict[str, dict]] = {}
    n_tr = 0
    with p.lock:
        for fname, items in p.tr.items():
            f = p.by_name.get(fname)
            if f is None:
                continue
            out = {}
            for k, t in items.items():
                if not t.get("t") or t.get("auto"):
                    continue
                e = f["_idx"].get(k)
                if e is None:
                    continue
                d = {"t": t["t"], "h": _h(e["body"])}
                if t.get("st"):
                    d["st"] = t["st"]
                if e.get("virt"):
                    d["s"] = _h(p._skey(e))
                out[k] = d
            if out:
                tr[fname] = out
                n_tr += len(out)
        names = {k: v for k, v in p.names.items() if v}
        settings = {k: p.settings[k] for k in SETTINGS if k in p.settings}
        imgs = {}
        for key, m in (p.meta.get("imagens") or {}).items():
            if os.path.exists(os.path.join(p.img_dir, key + ".png")):
                imgs[key] = {"de": m.get("de"), "w": m.get("w"), "h": m.get("h")}
        extra = list(p.meta.get("img_extra") or [])
    info = {"formato": FORMAT, "programa": "SOAL Tradutor", "versao": version,
            "criado": time.strftime("%Y-%m-%d %H:%M"), "regiao": p.meta.get("region", "us"),
            "jogo": p.meta.get("game_id", ""), "falas": n_tr, "imagens": len(imgs), "nomes": len(names),
            "ajustes": settings, "nomes_falantes": names, "outros_arquivos_de_imagem": extra}
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("patch.json", json.dumps(info, ensure_ascii=False, indent=1))
        z.writestr("traducao.json", json.dumps(tr, ensure_ascii=False, separators=(",", ":")))
        z.writestr("imagens.json", json.dumps(imgs, ensure_ascii=False, indent=1))
        for key in imgs:
            z.write(os.path.join(p.img_dir, key + ".png"), "imagens/%s.png" % key)
    os.replace(tmp, path)
    return {"path": os.path.abspath(path), "falas": n_tr, "imagens": len(imgs), "nomes": len(names),
            "bytes": os.path.getsize(path)}


def read(path: str) -> dict:
    path = (path or "").strip().strip('"')
    if not path or not os.path.isfile(path):
        raise PatchError("Arquivo de patch não encontrado.")
    try:
        with zipfile.ZipFile(path) as z:
            info = json.loads(z.read("patch.json").decode("utf-8"))
            if info.get("formato") != FORMAT or info.get("programa") != "SOAL Tradutor":
                raise PatchError("Esse arquivo não é um patch do SOAL Tradutor (ou é de uma versão mais nova do programa).")
            tr = json.loads(z.read("traducao.json").decode("utf-8"))
            imgs = json.loads(z.read("imagens.json").decode("utf-8"))
            png = {}
            for key in imgs:
                try:
                    png[key] = z.read("imagens/%s.png" % key)
                except KeyError:
                    pass
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise PatchError("Esse arquivo não é um patch do SOAL Tradutor: %s" % exc)
    return {"info": info, "tr": tr, "imgs": imgs, "png": png}


def apply(q, data: dict) -> dict:
    """Aplica o patch ao projeto `q` (o do jogo de destino). As traducoes do patch tomam o
    lugar das que o projeto tiver. Devolve um relatorio."""
    info = data["info"]
    same_region = info.get("regiao", "us") == q.meta.get("region", "us")
    rep = {"falas": 0, "iguais": 0, "revisar": 0, "faltam": 0, "imagens": 0, "nomes": 0,
           "erros_imagens": [], "faltam_lista": [], "revisar_lista": [], "mesma_versao": same_region}
    with q.lock:
        vidx: Dict[str, List[tuple]] = {}
        for f in q.files:
            if f.get("virt"):
                for e in f["entries"]:
                    vidx.setdefault(_h(q._skey(e)), []).append((f["name"], e["k"]))
        low = {n.lower(): n for n in q.by_name}
        for fname, items in data["tr"].items():
            f = q.by_name.get(fname) or q.by_name.get(low.get(fname.lower(), ""))
            for k, d in items.items():
                tf, e = f, (f["_idx"].get(k) if f else None)
                if d.get("s") and (e is None or _h(q._skey(e)) != d["s"]):
                    # itens, menus e introducao: as chaves mudam entre as versoes; liga pelo ingles
                    hits = vidx.get(d["s"])
                    if hits:
                        tf = q.by_name[hits[0][0]]
                        k = hits[0][1]
                        e = tf["_idx"][k]
                if e is None:
                    rep["faltam"] += 1
                    if len(rep["faltam_lista"]) < 100:
                        rep["faltam_lista"].append(f"{fname}/{k}")
                    continue
                st = d.get("st", "")
                if _h(e["body"]) == d.get("h"):
                    rep["iguais"] += 1
                else:
                    st = "rev"
                    rep["revisar"] += 1
                    if len(rep["revisar_lista"]) < 100:
                        rep["revisar_lista"].append(f"{tf['name']}/{k}")
                val = q.fit(e, d["t"])
                q.tr.setdefault(tf["name"], {})[k] = {"t": val, "st": st}
                rep["falas"] += 1
                for sf, sk in q.same.get(q._skey(e), ()):
                    if (sf, sk) == (tf["name"], k):
                        continue
                    oft = q.tr.setdefault(sf, {})
                    o = oft.get(sk)
                    if o is None or not o.get("t") or o.get("auto"):
                        oft[sk] = {"t": val, "auto": True, "st": (o or {}).get("st", "")}
        for name, value in (info.get("nomes_falantes") or {}).items():
            if value:
                q.names[name] = value
                rep["nomes"] += 1
        for k, v in (info.get("ajustes") or {}).items():
            if k not in SETTINGS:
                continue
            if k in ("eu_slot", "accents", "charmap") and not same_region:
                continue
            q.settings[k] = v
        q.touch()
    q.save(force=True)
    if same_region:
        for rel in info.get("outros_arquivos_de_imagem") or []:
            try:
                q.img_add(rel)
            except Exception as exc:  # arquivo que nao existe neste jogo
                rep["erros_imagens"].append(f"{rel}: {exc}")
        for key, m in data["imgs"].items():
            png = data["png"].get(key)
            de = m.get("de") or []
            if png is None or len(de) != 2:
                continue
            try:
                r = q.img_save(de[0], int(de[1]), png)
                rep["imagens"] += 1 if r.get("edited") else 0
            except Exception as exc:
                rep["erros_imagens"].append(f"{de[0]} #{de[1]}: {exc}")
    return rep
