"""Projeto de traducao: extracao dos textos, armazenamento das traducoes e gravacao no jogo."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from . import aklz
from . import font as fontmod
from . import recomp, sct, text

PROJECT_FILE = "projeto.json"
CACHE_FILE = "textos.json"
ORIG_DIR = "originais"
CACHE_VERSION = 4

CATEGORIES = [
    ("cidades", "Cidades e ilhas"),
    ("masmorras", "Masmorras"),
    ("cenas", "Cenas"),
    ("navios", "Batalhas de navio"),
    ("mundo", "Mundo aberto"),
    ("outros", "Testes e outros"),
]

# letra acentuada -> simbolo da fonte que sera' redesenhado (nenhum deles aparece nos dialogos)
DEFAULT_CHARMAP = {
    "á": "#", "à": "$", "â": "<", "ã": ">", "é": "@", "ê": "^",
    "í": "_", "ó": "`", "ô": "{", "õ": "|", "ú": "}", "ç": "=",
    "É": "+", "Á": "/", "Ó": '"',
}
FREE_SLOTS = '#$<>@^_`{|}=+/"'

DEFAULT_SETTINGS = {
    "cols": 48,
    "lines": 3,
    "accents": "font",       # font = redesenha simbolos da fonte; strip = grava sem acento
    "charmap": DEFAULT_CHARMAP,
    "autofill": True,
    "keep_states": False,    # so' no recomp: tamanhos em blocos de 32 KB (experimental)
}


class ProjectError(Exception):
    pass


def category_of(name: str) -> str:
    n = name.lower()
    if n.startswith("me099"):
        return "mundo"
    if n.startswith("me0"):
        return "cidades"
    if n.startswith("me1"):
        return "masmorras"
    if n.startswith("me2"):
        return "cenas"
    if n.startswith("me5"):
        return "navios"
    return "outros"


def find_game(root: str) -> Tuple[str, Optional[str]]:
    """Acha a pasta 'field' (com os .sct) e o arquivo de fonte dentro de uma extracao do jogo."""
    root = os.path.abspath(root)
    candidates = [os.path.join(root, "files", "field"), os.path.join(root, "field"), root]
    for field in candidates:
        if os.path.isdir(field) and any(f.lower().endswith(".sct") for f in os.listdir(field)):
            parent = os.path.dirname(field)
            fnt = None
            for f in os.listdir(parent):
                if f.lower().startswith("fontdata."):
                    fnt = os.path.join(parent, f)
                    break
            return field, fnt
    raise ProjectError(
        "Nao encontrei arquivos .sct nessa pasta. Escolha a pasta onde a ISO foi extraida "
        "(a que contem 'files' e 'sys', ou a que contem 'field').")


def _atomic_write(path: str, data: bytes):
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


class Project:
    def __init__(self, project_dir: str):
        self.dir = os.path.abspath(project_dir)
        self.lock = threading.RLock()
        self.meta: dict = {}
        self.files: List[dict] = []          # cache de extracao
        self.by_name: Dict[str, dict] = {}
        self.same: Dict[str, List[Tuple[str, str]]] = {}   # corpo original -> [(arquivo, chave)]
        self._dirty = False
        self._last_save = 0.0

    # ------------------------------------------------------------ caminhos
    @property
    def orig_field(self) -> str:
        return os.path.join(self.dir, ORIG_DIR, "field")

    @property
    def orig_font(self) -> Optional[str]:
        d = os.path.join(self.dir, ORIG_DIR)
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower().startswith("fontdata."):
                    return os.path.join(d, f)
        return None

    @property
    def settings(self) -> dict:
        return self.meta["settings"]

    @property
    def tr(self) -> Dict[str, Dict[str, dict]]:
        return self.meta["tr"]

    @property
    def names(self) -> Dict[str, str]:
        return self.meta["names"]

    # ------------------------------------------------------------ abrir / criar
    @staticmethod
    def default_dir(game_root: str) -> str:
        game_root = os.path.abspath(game_root).rstrip("\\/")
        if recomp.is_recomp_game(game_root):
            # dentro de "games" o launcher do port poderia confundir a pasta com um jogo
            return os.path.join(os.path.expanduser("~"), "SOAL Tradutor", os.path.basename(game_root))
        return game_root + "_traducao"

    @classmethod
    def create_or_open(cls, game_root: str, project_dir: Optional[str] = None,
                       progress: Optional[Callable[[str, int, int], None]] = None) -> "Project":
        field, fnt = find_game(game_root)
        gid = recomp.game_id(game_root)
        if gid and gid != recomp.SUPPORTED_ID:
            raise ProjectError(
                f"Esta pasta e' da versao {recomp.REGION_NAMES.get(gid, gid)} ({gid}). "
                "Por enquanto o programa so' traduz a versao americana (GEAE8P).")
        pdir = project_dir or cls.default_dir(game_root)
        p = cls(pdir)
        os.makedirs(p.orig_field, exist_ok=True)
        meta_path = os.path.join(pdir, PROJECT_FILE)
        if os.path.exists(meta_path):
            p._load_meta()
        else:
            p.meta = {"version": 1, "created": time.strftime("%Y-%m-%d %H:%M"),
                      "settings": json.loads(json.dumps(DEFAULT_SETTINGS)), "names": {}, "tr": {}}
        p.meta["game_root"] = os.path.abspath(game_root)
        p.meta["game_field"] = field
        p.meta["game_font"] = fnt
        # guarda os originais uma unica vez; depois disso o jogo pode ser sobrescrito a vontade
        names = sorted((f for f in os.listdir(field) if f.lower().endswith(".sct")), key=str.lower)
        for i, f in enumerate(names):
            dst = os.path.join(p.orig_field, f)
            if not os.path.exists(dst):
                shutil.copy2(os.path.join(field, f), dst)
            if progress and i % 20 == 0:
                progress("Guardando copias dos originais", i, len(names))
        if fnt and not p.orig_font:
            shutil.copy2(fnt, os.path.join(pdir, ORIG_DIR, os.path.basename(fnt)))
        p.meta["not_original"] = p.check_originals()
        p._dirty = True
        p.save(force=True)
        p.extract(progress)
        return p

    @classmethod
    def open(cls, project_dir: str, progress=None) -> "Project":
        p = cls(project_dir)
        if not os.path.exists(os.path.join(p.dir, PROJECT_FILE)):
            raise ProjectError("Essa pasta nao tem um projeto de traducao.")
        p._load_meta()
        p.extract(progress)
        return p

    def check_originals(self) -> List[str]:
        """Arquivos guardados como originais que nao batem com os do disco americano
        (pasta que ja' tinha traducao gravada, ou romhack)."""
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                                   "originais_geae8p.json"), encoding="utf-8") as fh:
                known = json.load(fh)["files"]
        except (OSError, ValueError, KeyError):
            return []
        bad = []
        for f in sorted(os.listdir(self.orig_field)):
            want = known.get(f.lower())
            if want and self._sha1_file(os.path.join(self.orig_field, f)) != want:
                bad.append(f)
        of = self.orig_font
        if of and known.get(os.path.basename(of).lower()) not in (None, self._sha1_file(of)):
            bad.append(os.path.basename(of))
        return bad

    def _load_meta(self):
        with open(os.path.join(self.dir, PROJECT_FILE), encoding="utf-8") as fh:
            self.meta = json.load(fh)
        st = json.loads(json.dumps(DEFAULT_SETTINGS))
        st.update(self.meta.get("settings") or {})
        self.meta["settings"] = st
        self.meta.setdefault("names", {})
        self.meta.setdefault("tr", {})

    def save(self, force: bool = False):
        with self.lock:
            if not self._dirty and not force:
                return
            data = json.dumps(self.meta, ensure_ascii=False, indent=0).encode("utf-8")
            _atomic_write(os.path.join(self.dir, PROJECT_FILE), data)
            self._dirty = False
            self._last_save = time.time()

    def touch(self):
        self._dirty = True

    # ------------------------------------------------------------ extracao
    def extract(self, progress=None, force: bool = False):
        cache_path = os.path.join(self.dir, CACHE_FILE)
        names = sorted((f for f in os.listdir(self.orig_field) if f.lower().endswith(".sct")), key=str.lower)
        if not force and os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as fh:
                    c = json.load(fh)
                if c.get("version") == CACHE_VERSION and [f["name"] for f in c["files"]] == names:
                    self._set_files(c["files"])
                    return
            except (ValueError, KeyError):
                pass
        files = []
        for i, f in enumerate(names):
            if progress:
                progress("Lendo os textos do jogo", i, len(names))
            files.append(self._extract_file(f))
        _atomic_write(cache_path, json.dumps({"version": CACHE_VERSION, "files": files},
                                             ensure_ascii=False).encode("utf-8"))
        self._set_files(files)

    def _extract_file(self, fname: str) -> dict:
        entry = {"name": fname, "cat": category_of(fname), "entries": [], "error": None}
        try:
            s = sct.load(os.path.join(self.orig_field, fname))
        except (sct.SctError, OSError, ValueError) as exc:
            entry["error"] = str(exc)
            return entry
        if s.problems:
            entry["error"] = "; ".join(s.problems[:3])
        seen: Dict[str, int] = {}
        prev_cont = False
        prev_index = -2
        for sec in s.string_sections():
            n = seen.get(sec.name, 0)
            seen[sec.name] = n + 1
            key = sec.name if n == 0 else f"{sec.name}~{n}"
            raw = s.text_bytes(sec)
            e = {"k": key, "sec": sec.name, "i": sec.index}
            try:
                gt = text.decode(raw)
                e.update(head=gt.head, br=gt.brackets, body=gt.body, end=gt.end)
            except text.TextError:
                e.update(head=None, br=False, body="", end="", raw=raw.hex())
            e["cont"] = bool(prev_cont and prev_index == sec.index - 1)
            if text.has_japanese(e["body"]) or e["body"].startswith("//"):
                e["dbg"] = True
            prev_cont = e["end"] == "c"
            prev_index = sec.index
            entry["entries"].append(e)
        for k, fs in enumerate(x for x in s.footer if x.dialog):
            raw = s.footer_bytes(fs)
            e = {"k": f"@rodape{k}", "sec": "rodape", "i": -1, "pos": fs.start, "cont": False}
            try:
                gt = text.decode(raw)
                e.update(head=gt.head, br=gt.brackets, body=gt.body, end=gt.end)
            except text.TextError:
                continue
            if text.has_japanese(e["body"]) or entry["cat"] == "outros":
                e["dbg"] = True
            entry["entries"].append(e)
        return entry

    def _set_files(self, files: List[dict]):
        self.files = files
        self.by_name = {f["name"]: f for f in files}
        self.same = {}
        for f in files:
            f["_idx"] = {e["k"]: e for e in f["entries"]}
            for e in f["entries"]:
                if e["body"] and not e.get("raw"):
                    self.same.setdefault(e["body"], []).append((f["name"], e["k"]))

    # ------------------------------------------------------------ consulta
    def translated(self, fname: str, key: str) -> Optional[dict]:
        return self.tr.get(fname, {}).get(key)

    def file_stats(self, f: dict) -> Tuple[int, int]:
        tr = self.tr.get(f["name"], {})
        total = done = 0
        for e in f["entries"]:
            if e.get("dbg") or e.get("raw") or not e["body"].strip():
                continue
            total += 1
            t = tr.get(e["k"])
            if t and t.get("t"):
                done += 1
        return total, done

    def summary(self) -> dict:
        out = []
        gt = gd = 0
        for f in self.files:
            t, d = self.file_stats(f)
            gt += t
            gd += d
            out.append({"name": f["name"], "cat": f["cat"], "total": t, "done": d,
                        "count": len(f["entries"]), "error": f.get("error")})
        return {"files": out, "total": gt, "done": gd,
                "unique": len(self.same), "categories": CATEGORIES}

    def file_entries(self, fname: str) -> dict:
        f = self.by_name.get(fname)
        if f is None:
            raise ProjectError("arquivo desconhecido")
        tr = self.tr.get(fname, {})
        rows = []
        for e in f["entries"]:
            t = tr.get(e["k"], {})
            row = {k: v for k, v in e.items() if k not in ("raw",)}
            row["t"] = t.get("t", "")
            row["st"] = t.get("st", "")
            row["auto"] = bool(t.get("auto"))
            row["dup"] = len(self.same.get(e["body"], ())) if e["body"] else 0
            rows.append(row)
        return {"name": fname, "cat": f["cat"], "entries": rows, "error": f.get("error")}

    # ------------------------------------------------------------ edicao
    def set_translation(self, fname: str, key: str, value: str, status: Optional[str] = None) -> dict:
        with self.lock:
            f = self.by_name.get(fname)
            if f is None or key not in f["_idx"]:
                raise ProjectError("texto desconhecido")
            e = f["_idx"][key]
            value = value.replace("\r\n", "\n").replace("\r", "\n")
            ft = self.tr.setdefault(fname, {})
            cur = ft.get(key, {})
            new = dict(cur)
            new["t"] = value
            new.pop("auto", None)
            if status is not None:
                new["st"] = status
            if not new.get("t") and not new.get("st"):
                ft.pop(key, None)
            else:
                ft[key] = new
            filled = []
            if value and self.settings.get("autofill", True):
                for of, ok in self.same.get(e["body"], ()):
                    if of == fname and ok == key:
                        continue
                    oft = self.tr.setdefault(of, {})
                    o = oft.get(ok)
                    if o is None or not o.get("t") or o.get("auto"):
                        oft[ok] = {"t": value, "auto": True, "st": (o or {}).get("st", "")}
                        filled.append([of, ok])
            self.touch()
            return {"filled": filled}

    def set_status(self, fname: str, key: str, status: str):
        with self.lock:
            f = self.by_name.get(fname)
            if f is None or key not in f["_idx"]:
                raise ProjectError("texto desconhecido")
            ft = self.tr.setdefault(fname, {})
            cur = ft.setdefault(key, {"t": ""})
            cur["st"] = status
            if not cur.get("t") and not status:
                ft.pop(key, None)
            self.touch()

    def name_list(self) -> List[dict]:
        counts: Dict[str, int] = {}
        for f in self.files:
            for e in f["entries"]:
                h = e.get("head")
                if h and e.get("br") and not e.get("dbg"):
                    counts[h] = counts.get(h, 0) + 1
        return [{"name": n, "count": c, "t": self.names.get(n, "")}
                for n, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]

    def set_name(self, name: str, value: str):
        with self.lock:
            value = value.strip()
            if value and value != name:
                self.names[name] = value
            else:
                self.names.pop(name, None)
            self.touch()

    def search(self, query: str, limit: int = 400) -> List[dict]:
        q = query.casefold().strip()
        if not q:
            return []
        out = []
        for f in self.files:
            tr = self.tr.get(f["name"], {})
            for e in f["entries"]:
                t = tr.get(e["k"], {}).get("t", "")
                hay = (e["body"] + "\n" + t + "\n" + (e.get("head") or "") + "\n" + e["sec"]).casefold()
                if q in hay:
                    out.append({"file": f["name"], "k": e["k"], "head": e.get("head"),
                                "body": e["body"], "t": t})
                    if len(out) >= limit:
                        return out
        return out

    # ------------------------------------------------------------ conferencia
    def charmap_codes(self) -> Dict[str, int]:
        if self.settings.get("accents") != "font":
            return {}
        return {ch: ord(sym) for ch, sym in (self.settings.get("charmap") or {}).items()
                if len(ch) == 1 and len(sym) == 1}

    def check_text(self, body: str) -> List[str]:
        cm = self.charmap_codes()
        cols = int(self.settings.get("cols", 48))
        maxl = int(self.settings.get("lines", 3))
        issues = []
        for page in re.split(r"\\c", body):
            lines = page.split("\n")
            if len(lines) > maxl:
                issues.append(f"{len(lines)} linhas (a caixa mostra {maxl})")
            for ln in lines:
                w = text.columns(ln, cm)
                if w > cols:
                    issues.append(f"linha com {w} colunas (limite {cols})")
        return issues

    # ------------------------------------------------------------ planilha
    def export_csv(self) -> bytes:
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["arquivo", "chave", "personagem", "original", "traducao", "situacao"])
        for f in self.files:
            tr = self.tr.get(f["name"], {})
            for e in f["entries"]:
                if e.get("raw"):
                    continue
                t = tr.get(e["k"], {})
                w.writerow([f["name"], e["k"], e.get("head") or "", e["body"], t.get("t", ""), t.get("st", "")])
        return (chr(0xFEFF) + buf.getvalue()).encode("utf-8")

    def export_unique_csv(self) -> bytes:
        """Uma linha por fala unica (as repetidas sao preenchidas sozinhas na importacao)."""
        cols = int(self.settings.get("cols", 48))
        maxl = int(self.settings.get("lines", 3))
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        w.writerow(["arquivo", "chave", "personagem", "tipo", "repeticoes", "fala_anterior",
                    "original", "traducao", "situacao"])
        seen = set()
        for f in self.files:
            tr = self.tr.get(f["name"], {})
            prev = ""
            for e in f["entries"]:
                if e.get("raw") or e.get("dbg") or not e["body"].strip():
                    continue
                body = e["body"]
                who = e.get("head") if e.get("br") else ""
                if body not in seen:
                    seen.add(body)
                    t = tr.get(e["k"], {})
                    kind = ("menu: mantenha uma opcao por linha" if text.is_menu(body)
                            else f"fala: ate {maxl} linhas de {cols} colunas")
                    w.writerow([f["name"], e["k"], who or "", kind, len(self.same.get(body, ())) or 1,
                                prev, body, t.get("t", ""), t.get("st", "")])
                prev = ((who + ": ") if who else "") + body.replace("\n", " ")
        return (chr(0xFEFF) + buf.getvalue()).encode("utf-8")

    def import_csv(self, data: bytes) -> dict:
        txt = data.decode("utf-8-sig", "replace")
        first = txt.split("\n", 1)[0]
        delim = ";" if first.count(";") >= first.count(",") and ";" in first else ("\t" if "\t" in first else ",")
        rd = csv.reader(io.StringIO(txt), delimiter=delim)
        head = [h.strip().lower() for h in next(rd, [])]
        try:
            ci, ck, ct = head.index("arquivo"), head.index("chave"), head.index("traducao")
        except ValueError:
            raise ProjectError("A planilha precisa das colunas 'arquivo', 'chave' e 'traducao'.")
        cs = head.index("situacao") if "situacao" in head else -1
        cols = int(self.settings.get("cols", 48))
        maxl = int(self.settings.get("lines", 3))
        cm = self.charmap_codes()
        applied = skipped = filled = wrapped = 0
        with self.lock:
            for row in rd:
                if len(row) <= max(ci, ck, ct):
                    continue
                f = self.by_name.get(row[ci].strip())
                key = row[ck].strip()
                if f is None or key not in f["_idx"]:
                    skipped += 1
                    continue
                e = f["_idx"][key]
                val = row[ct].replace("\r\n", "\n").replace("\r", "\n").strip("\n")
                if val and not text.is_menu(e["body"]):
                    val, ch = text.wrap(val, cols, maxl, cm)
                    wrapped += ch
                st = row[cs].strip() if cs >= 0 and len(row) > cs else None
                ft = self.tr.setdefault(f["name"], {})
                cur = ft.get(key, {})
                if val != cur.get("t", "") or (st is not None and st != cur.get("st", "")):
                    if not val and not st:
                        ft.pop(key, None)
                    else:
                        ft[key] = {"t": val, "st": st if st is not None else cur.get("st", "")}
                    applied += 1
                # falas identicas em outros lugares: preenche as que ainda nao tem traducao propria
                if val:
                    for of, ok in self.same.get(e["body"], ()):
                        if of == f["name"] and ok == key:
                            continue
                        oft = self.tr.setdefault(of, {})
                        o = oft.get(ok)
                        if o is None or not o.get("t") or o.get("auto"):
                            if not o or o.get("t") != val:
                                oft[ok] = {"t": val, "auto": True, "st": (o or {}).get("st", "")}
                                filled += 1
            self.touch()
        self.save()
        return {"applied": applied, "skipped": skipped, "filled": filled, "wrapped": wrapped}

    # ------------------------------------------------------------ destinos
    def targets(self) -> List[dict]:
        """Pastas onde a traducao e' gravada: a do jogo aberto e, se marcado, a do recomp."""
        out = []
        main = self.meta.get("game_root")
        if main:
            out.append(self._target(main))
        extra = self.meta.get("recomp_root")
        if extra and self.meta.get("use_recomp") and os.path.isdir(extra):
            t = self._target(extra)
            if all(os.path.normcase(t["field"]) != os.path.normcase(o["field"]) for o in out):
                out.append(t)
        return out

    def _target(self, root: str) -> dict:
        field, fnt = find_game(root)
        is_rc = recomp.is_recomp_game(root)
        tag = hashlib.sha1(os.path.normcase(os.path.abspath(field)).encode("utf-8")).hexdigest()[:8]
        fst = os.path.join(root, "sys", "fst.bin")
        return {"root": os.path.abspath(root), "field": field, "font": fnt, "recomp": is_rc, "tag": tag,
                "fst": fst if (is_rc and os.path.exists(fst)) else None,
                "manifest": os.path.join(self.dir, f"gravacao_{tag}.json"),
                "backup": os.path.join(self.dir, "copias_do_destino", tag)}

    def set_recomp(self, root: Optional[str], use: bool):
        with self.lock:
            if root:
                gid = recomp.game_id(root)
                if gid != recomp.SUPPORTED_ID:
                    raise ProjectError("O jogo importado no recomp nao e' a versao americana (GEAE8P).")
                find_game(root)
                self.meta["recomp_root"] = os.path.abspath(root)
            self.meta["use_recomp"] = bool(use)
            self.touch()
        self.save()

    @staticmethod
    def _sha1_file(path: str) -> Optional[str]:
        try:
            with open(path, "rb") as fh:
                return hashlib.sha1(fh.read()).hexdigest()
        except OSError:
            return None

    @staticmethod
    def _load_manifest(t: dict) -> dict:
        try:
            with open(t["manifest"], encoding="utf-8") as fh:
                m = json.load(fh)
            if m.get("field") == t["field"] and isinstance(m.get("files"), dict):
                return m
        except (OSError, ValueError):
            pass
        return {"field": t["field"], "files": {}, "first": True}

    def _keep_copy(self, t: dict, rel: str, current: str, original: Optional[bytes]):
        """Antes de sobrescrever pela primeira vez um arquivo do destino que nao e' igual ao
        original guardado (outro romhack, outra traducao), guarda uma copia dele."""
        dst = os.path.join(t["backup"], rel)
        if os.path.exists(dst) or not os.path.exists(current):
            return False
        with open(current, "rb") as fh:
            cur = fh.read()
        if original is not None and cur == original:
            return False
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        _atomic_write(dst, cur)
        return True

    # ------------------------------------------------------------ gravar no jogo
    def _new_texts(self, f: dict, enc: text.Encoder, report: dict):
        tr = self.tr.get(f["name"], {})
        names = self.names
        new_sec: Dict[int, bytes] = {}
        new_foot: Dict[int, bytes] = {}
        for e in f["entries"]:
            if e.get("raw"):
                continue
            t = tr.get(e["k"], {}).get("t", "")
            head = e.get("head")
            new_head = names.get(head, head) if (head and e.get("br")) else head
            if not t and new_head == head:
                continue
            body = t if t else e["body"]
            if t:
                report["entries"] += 1
                issues = self.check_text(t)
                if issues:
                    report["long"].append({"file": f["name"], "k": e["k"], "issue": issues[0]})
            raw = enc.encode(text.GameText(new_head, bool(e.get("br")), body, e["end"]))
            if e["i"] >= 0:
                new_sec[e["i"]] = raw
            else:
                new_foot[e["pos"]] = raw
        return new_sec, new_foot

    def build(self, progress=None) -> dict:
        """Grava os .sct traduzidos (e a fonte com acentos) em cada destino."""
        with self.lock:
            self.save()
            targets = self.targets()
            if not targets:
                raise ProjectError("Nenhuma pasta de destino.")
            cm = self.charmap_codes()
            enc = text.Encoder(cm)
            pad = bool(self.settings.get("keep_states"))
            report = {"entries": 0, "long": [], "errors": [], "targets": []}
            states = []
            for t in targets:
                os.makedirs(t["field"], exist_ok=True)
                m = self._load_manifest(t)
                states.append({"t": t, "m": m, "first": bool(m.pop("first", False)),
                               "r": {"root": t["root"], "recomp": t["recomp"], "written": 0, "restored": 0,
                                     "unchanged": 0, "kept": 0, "font": "", "fst": "", "note": ""}})
            n = len(self.files)
            for i, f in enumerate(self.files):
                if progress:
                    progress("Gravando " + f["name"], i, n)
                name = f["name"]
                try:
                    with open(os.path.join(self.orig_field, name), "rb") as fh:
                        orig = fh.read()
                    if f.get("error") and not f["entries"]:
                        new_sec, new_foot = {}, {}
                    else:
                        new_sec, new_foot = self._new_texts(f, enc, report)
                    plain = digest = raw = None
                    if new_sec or new_foot:
                        s = sct.SctFile(orig, name)
                        plain = s.rebuild(new_sec, new_foot, compress=False)
                        digest = hashlib.sha1(plain).hexdigest()
                    for st in states:
                        t, mf, r = st["t"], st["m"]["files"], st["r"]
                        dst = os.path.join(t["field"], name)
                        if st["first"] and self._keep_copy(t, os.path.join("field", name), dst, orig):
                            r["kept"] += 1
                        if plain is None:
                            if mf.pop(name, None) or self._sha1_file(dst) != hashlib.sha1(orig).hexdigest():
                                _atomic_write(dst, orig)
                                r["restored"] += 1
                            continue
                        do_pad = pad and t["recomp"]
                        old = mf.get(name) or {}
                        if old.get("plain") == digest and old.get("pad") == do_pad and \
                                self._sha1_file(dst) == old.get("out"):
                            r["unchanged"] += 1
                            continue
                        if raw is None:
                            # confere o arquivo novo antes de gravar: abre sem erro e mantem os links
                            chk = sct.SctFile(plain, name)
                            if chk.problems or len(chk.links) != len(s.links) or \
                                    len(chk.sections) != len(s.sections):
                                raise ProjectError("o arquivo reconstruido nao passou na conferencia")
                            raw = aklz.compress(plain) if s.was_compressed else plain
                        out = recomp.pad_to_block(raw) if do_pad else raw
                        _atomic_write(dst, out)
                        mf[name] = {"plain": digest, "out": hashlib.sha1(out).hexdigest(), "pad": do_pad}
                        r["written"] += 1
                except (sct.SctError, ProjectError, OSError, ValueError) as exc:
                    report["errors"].append({"file": name, "error": str(exc)})
            # fonte
            of = self.orig_font
            fdata = fnew = None
            if of:
                try:
                    with open(of, "rb") as fh:
                        fdata = fh.read()
                    if cm:
                        fnt = fontmod.Font(fdata)
                        failed = fontmod.apply_charmap(fnt, dict(cm))
                        fnew = fnt.build()
                        font_note = "acentos desenhados na fonte"
                        if failed:
                            font_note += " (sem desenho para: " + " ".join(failed) + ")"
                    else:
                        fnew, font_note = fdata, "fonte original"
                except (fontmod.FontError, OSError) as exc:
                    report["errors"].append({"file": os.path.basename(of), "error": str(exc)})
            for st in states:
                t, r = st["t"], st["r"]
                try:
                    if fnew is not None:
                        dstf = t["font"] or os.path.join(os.path.dirname(t["field"]), os.path.basename(of))
                        if st["first"] and self._keep_copy(t, os.path.basename(dstf), dstf, fdata):
                            r["kept"] += 1
                        if self._sha1_file(dstf) != hashlib.sha1(fnew).hexdigest():
                            _atomic_write(dstf, fnew)
                        r["font"] = font_note
                    elif cm:
                        r["font"] = "arquivo de fonte nao encontrado: os acentos vao aparecer como simbolos"
                    if t["fst"]:
                        r["fst"] = self._update_fst(t)
                    if t["recomp"]:
                        r["states"] = recomp.count_states(os.path.dirname(os.path.dirname(t["root"])))
                    _atomic_write(t["manifest"], json.dumps(st["m"]).encode("utf-8"))
                except (recomp.FstError, OSError) as exc:
                    report["errors"].append({"file": t["root"], "error": str(exc)})
                report["targets"].append(r)
            report["stripped"] = enc.stripped
            report["missing"] = enc.missing
            if progress:
                progress("Pronto", n, n)
            return report

    def _update_fst(self, t: dict) -> str:
        """Atualiza no sys/fst.bin do destino o tamanho dos arquivos que a traducao mexe.
        Parte sempre do fst.bin original, guardado na primeira gravacao."""
        keep = os.path.join(t["backup"], "fst.bin.original")
        if not os.path.exists(keep):
            os.makedirs(t["backup"], exist_ok=True)
            shutil.copy2(t["fst"], keep)
        with open(keep, "rb") as fh:
            base = fh.read()
        fst = recomp.Fst(base)
        files_dir = os.path.dirname(t["field"])
        changed = 0
        paths = [("field/" + f, os.path.join(t["field"], f)) for f in os.listdir(t["field"])
                 if f.lower().endswith(".sct")]
        if t["font"]:
            paths.append((os.path.basename(t["font"]), t["font"]))
        for rel, full in paths:
            size = os.path.getsize(full)
            old = fst.size(rel)
            if old is not None and old != size:
                fst.set_size(rel, size)
                changed += 1
        new = fst.build()
        with open(t["fst"], "rb") as fh:
            cur = fh.read()
        if new != cur:
            _atomic_write(t["fst"], new)
        if new == base:
            return "tabela de arquivos original (nenhum tamanho mudou)"
        return f"tabela de arquivos atualizada ({changed} tamanhos)"

    def restore_originals(self) -> dict:
        """Devolve os arquivos originais a cada destino."""
        with self.lock:
            out = []
            for t in self.targets():
                n = 0
                for f in os.listdir(self.orig_field):
                    src = os.path.join(self.orig_field, f)
                    dst = os.path.join(t["field"], f)
                    kept = os.path.join(t["backup"], "field", f)
                    shutil.copy2(kept if os.path.exists(kept) else src, dst)
                    n += 1
                of = self.orig_font
                if of and t["font"]:
                    kept = os.path.join(t["backup"], os.path.basename(t["font"]))
                    shutil.copy2(kept if os.path.exists(kept) else of, t["font"])
                keep_fst = os.path.join(t["backup"], "fst.bin.original")
                if t["fst"] and os.path.exists(keep_fst):
                    shutil.copy2(keep_fst, t["fst"])
                try:
                    os.remove(t["manifest"])
                except OSError:
                    pass
                out.append({"root": t["root"], "files": n})
            return {"targets": out, "restored": sum(x["files"] for x in out)}
