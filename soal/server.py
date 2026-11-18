"""Servidor local: entrega a interface (web/index.html) e a API usada por ela.

So' aceita conexoes da propria maquina (127.0.0.1).
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from . import font as fontmod
from . import project as pj
from . import dublagem, exportar, intro, iso, janela, mt, patch, recomp, text

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".soal_tradutor.json")
VERSION = "0.14.0"


class App:
    def __init__(self):
        self.project: Optional[pj.Project] = None
        self.job = {"running": False, "label": "", "cur": 0, "total": 0, "error": None,
                    "result": None, "kind": ""}
        self.cancel = False
        self.job_lock = threading.Lock()
        self.config = self._load_config()
        self._glyph_cache = None
        self.last_ping = 0.0
        threading.Thread(target=self._autosave, daemon=True).start()

    # --------------------------------------------------------------- config
    def _load_config(self) -> dict:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                c = json.load(fh)
                if isinstance(c, dict):
                    return c
        except (OSError, ValueError):
            pass
        return {"recent": []}

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(self.config, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass

    def _remember(self, p: pj.Project):
        rec = [r for r in self.config.get("recent", []) if r.get("dir") != p.dir]
        rec.insert(0, {"dir": p.dir, "game": p.meta.get("game_root", ""), "region": p.meta.get("region", "us")})
        self.config["recent"] = rec[:6]
        self._save_config()

    def _autosave(self):
        while True:
            time.sleep(2.0)
            p = self.project
            if p is not None:
                try:
                    p.save()
                except OSError:
                    pass

    # ----------------------------------------------------------------- jobs
    def _progress(self, label: str, cur: int, total: int):
        self.job.update(label=label, cur=cur, total=total)

    def start_job(self, kind: str, fn):
        with self.job_lock:
            if self.job["running"]:
                raise pj.ProjectError("Ja' existe uma tarefa em andamento.")
            self.job.update(running=True, label="Preparando", cur=0, total=0, error=None,
                            result=None, kind=kind)
            self.cancel = False

        def run():
            try:
                self.job["result"] = fn()
            except (pj.ProjectError, OSError, mt.MTError, patch.PatchError, iso.IsoError) as exc:
                self.job["error"] = str(exc)
            except Exception as exc:  # erro inesperado: mostra na tela em vez de sumir
                traceback.print_exc()
                self.job["error"] = f"Erro inesperado: {exc}"
            finally:
                self.job["running"] = False

        threading.Thread(target=run, daemon=True).start()

    def open_game(self, game_root: str):
        # a pasta escolhida ja' e' de um projeto (por exemplo, um projeto que foi movido)
        if pj.is_project_dir(game_root):
            return self.open_project(game_root)
        # o projeto deste jogo foi movido para outro lugar: abre ele em vez de criar outro
        want = os.path.normcase(os.path.abspath(game_root).rstrip("\\/"))
        for r in self.config.get("recent", []):
            if (os.path.normcase(os.path.abspath(r.get("game") or "").rstrip("\\/")) == want
                    and pj.is_project_dir(r.get("dir") or "")):
                return self.open_project(r["dir"])

        def fn():
            p = pj.Project.create_or_open(game_root, progress=self._progress)
            self.project = p
            self._glyph_cache = None
            self._remember(p)
            return {"opened": p.dir}
        self.start_job("open", fn)

    def open_project(self, project_dir: str):
        def fn():
            p = pj.Project.open(project_dir, progress=self._progress)
            self.project = p
            self._glyph_cache = None
            self._remember(p)
            return {"opened": p.dir}
        self.start_job("open", fn)

    def move_project(self, new_dir: str):
        p = self.need()
        old = p.dir

        def fn():
            nd = p.move_to(new_dir, progress=self._progress)
            self.config["recent"] = [r for r in self.config.get("recent", []) if r.get("dir") != old]
            self._remember(p)
            return {"dir": nd}
        self.start_job("move", fn)

    def build(self):
        p = self.need()
        self.start_job("build", lambda: p.build(progress=self._progress))

    def iso_default(self, p: pj.Project) -> str:
        root = os.path.abspath(p.meta.get("game_root") or "").rstrip("\\/")
        return os.path.join(os.path.dirname(root), os.path.basename(root) + " (PT-BR).iso")

    # ------------------------------------------------------------- remaster
    def remaster_info(self) -> dict:
        """Onde ler o jogo (o jogo aberto e o do recomp, ja' com a traducao gravada) e onde
        gravar a extracao."""
        p = self.need()
        srcs = []
        for t in p.targets():
            files = os.path.dirname(t["field"])
            srcs.append({"root": t["root"], "files": files, "recomp": t["recomp"],
                         "label": ("Jogo do recomp" if t["recomp"] else "Jogo do projeto") + " — " + t["root"]})
        rc = p.meta.get("recomp_root")
        data_dir = os.path.dirname(os.path.dirname(rc)) if rc and recomp.is_recomp_game(rc) else ""
        if not data_dir:
            for t in p.targets():
                if t["recomp"]:
                    data_dir = os.path.dirname(os.path.dirname(t["root"]))
        out = self.config.get("remaster_out") or os.path.join(os.path.dirname(os.path.abspath(p.dir).rstrip("\\/")),
                                                               "SOAL remaster")
        folders = []
        if srcs:
            fdir = srcs[-1]["files"]
            for k, label in exportar.FOLDERS.items():
                d = os.path.join(fdir, k) if k else fdir
                if os.path.isdir(d):
                    folders.append({"id": k, "label": label})
        dumped = recomp.dumped_textures(data_dir) if data_dir else []
        return {"sources": srcs, "out": out, "folders": folders, "recomp": data_dir,
                "hires": recomp.hires_textures(data_dir) if data_dir else False,
                "installed": os.path.isdir(os.path.join(data_dir, "Load", "Textures", "GEA", "SOAL Tradutor")) if data_dir else False,
                "dumped": len(dumped)}

    def remaster_extract(self, files: str, out: str, what: list, folders: list):
        if not files or not os.path.isdir(files):
            raise pj.ProjectError("Não achei a pasta do jogo.")
        if not out:
            raise pj.ProjectError("Escolha a pasta onde gravar.")
        out = os.path.abspath(out)
        if os.path.normcase(out).startswith(os.path.normcase(os.path.abspath(files)).rstrip("\\/") + os.sep):
            raise pj.ProjectError("Grave a extração fora da pasta do jogo.")
        what = [w for w in what if w in ("texturas", "modelos", "cenarios")] or ["texturas"]
        self.config["remaster_out"] = out
        self._save_config()

        def prog(k, n, rel):
            self._progress(f"Extraindo {rel}" if rel else "Terminando", k, n)
        self.start_job("remaster", lambda: exportar.extract(
            files, out, what, folders if folders else None, f"SOAL Tradutor {VERSION}", prog, lambda: self.cancel))

    def remaster_install(self, src: str):
        info = self.remaster_info()
        if not info["recomp"]:
            raise pj.ProjectError("Marque o recomp em Gravar no jogo primeiro (o programa precisa saber a pasta dele).")
        if not src or not os.path.isdir(src):
            raise pj.ProjectError("Escolha a pasta com as texturas melhoradas (a pasta texturas da extração, por exemplo).")

        def fn():
            self._progress("Copiando as texturas", 0, 0)
            r = exportar.install_textures(src, info["recomp"])
            if not r["copiadas"]:
                raise pj.ProjectError("Não achei texturas tex1_….png nem .dds nessa pasta.")
            return r
        self.start_job("remaster", fn)

    def remaster_check(self, out: str) -> dict:
        """Confere os nomes da extracao com as texturas que o recomp despejou jogando
        (GFX.ini DumpTextures = True)."""
        info = self.remaster_info()
        dumped = set(recomp.dumped_textures(info["recomp"])) if info["recomp"] else set()
        mine = set()
        for dp, dn, fn in os.walk(os.path.join(out, "texturas")):
            mine.update(f.rsplit(".", 1)[0] for f in fn if f.lower().startswith("tex1_"))
        both = dumped & mine
        return {"dumped": len(dumped), "extracted": len(mine), "match": len(both),
                "only_dump": sorted(dumped - mine)[:30]}

    # ----------------------------------------------------------------- dublagem
    def dub_info(self) -> dict:
        p = self.need()
        groups = {}
        sdir = ""
        try:
            inv = p._snd_inventory()
            sdir = inv.dir
            for k in inv.keys():
                g = dublagem.group_of(inv.place(k))
                groups[g] = groups.get(g, 0) + 1
        except pj.ProjectError:
            pass
        out = self.config.get("dub_out") or os.path.join(os.path.dirname(os.path.abspath(p.dir).rstrip("\\/")),
                                                         "SOAL sons")
        lst = p.dub_list()
        return {"sound": sdir, "out": out, "src": p.meta.get("dub_src") or out,
                "groups": [{"id": k, "label": v, "files": groups.get(k, 0)} for k, v in dublagem.GROUPS.items()],
                "items": lst["items"], "dir": lst["dir"]}

    def dub_extract(self, out: str, groups: list):
        p = self.need()
        files = p._img_files_dir()
        if not out:
            raise pj.ProjectError("Escolha a pasta onde gravar os sons.")
        out = os.path.abspath(out)
        if os.path.normcase(out).startswith(os.path.normcase(os.path.abspath(files)).rstrip("\\/") + os.sep):
            raise pj.ProjectError("Grave os sons fora da pasta do jogo.")
        groups = [g for g in groups if g in dublagem.GROUPS] or ["personagens"]
        self.config["dub_out"] = out
        self._save_config()
        inv = p._snd_inventory()

        def prog(k, n, name):
            self._progress(f"Extraindo {name}" if name else "Terminando", k, n)

        def run():
            self._progress("Lendo as tabelas de sons", 0, 0)
            _ = inv.ids
            return dublagem.extract(inv, out, groups, prog, lambda: self.cancel, portraits=p.crew_portrait)
        self.start_job("audio", run)

    def dub_import(self, src: str):
        p = self.need()
        if not src or not os.path.isdir(src):
            raise pj.ProjectError("Escolha a pasta com os WAV dublados.")
        self.start_job("audio", lambda: p.dub_import(src, self._progress, lambda: self.cancel))

    # ----------------------------------------------------------------- patch
    def patch_default(self, p: pj.Project) -> str:
        root = os.path.abspath(p.meta.get("game_root") or "").rstrip("\\/")
        return os.path.join(os.path.dirname(root), patch.default_name(p.meta.get("region", "us")))

    def patch_create(self, path: str):
        p = self.need()

        def fn():
            p.save(force=True)
            return {"created": patch.create(p, path or self.patch_default(p), VERSION)}
        self.start_job("patch", fn)

    def patch_apply(self, patch_path: str, target: str, iso_out: str):
        data = patch.read(patch_path)
        region = data["info"].get("regiao", "us")
        want = "GEAP8P" if region == "eu" else "GEAE8P"
        target = os.path.abspath((target or "").strip().strip('"'))
        is_iso = target.lower().endswith((".iso", ".gcm"))
        cur = self.project
        if is_iso:
            if not os.path.isfile(target):
                raise pj.ProjectError("Arquivo ISO não encontrado.")
            out = (iso_out or "").strip().strip('"') or os.path.splitext(target)[0] + " (PT-BR).iso"
            if not out.lower().endswith((".iso", ".gcm")):
                out += ".iso"
            out = os.path.abspath(out)
            if os.path.normcase(out) == os.path.normcase(target):
                raise pj.ProjectError("Escolha outro nome para a ISO traduzida: a original não é alterada.")
            d = os.path.dirname(out)
            os.makedirs(d, exist_ok=True)
            if shutil.disk_usage(d).free < 2 * iso.DISC_SIZE + 128 * 1024 * 1024:
                raise pj.ProjectError("Não há espaço livre suficiente nesse disco: são precisos cerca de 3 GB "
                                      "(a ISO extraída enquanto trabalha e a ISO nova).")
        else:
            if not os.path.isdir(target):
                raise pj.ProjectError("Essa pasta não existe. Escolha a ISO, a pasta do jogo extraído ou a pasta do recomp.")
            root = target
            try:
                pj.find_game(root)
            except pj.ProjectError:
                hit = recomp.find_region(want, target)
                if not hit:
                    raise pj.ProjectError("Não achei o jogo nessa pasta. Escolha a pasta do jogo extraído (com sys/ e files/), "
                                          f"a pasta do recomp com a versão {recomp.REGION_NAMES[want]} importada, ou uma ISO.")
                root = hit["game_root"]
            gid = recomp.game_id(root)
            if gid and gid != want:
                raise pj.ProjectError(f"Esse jogo é da versão {recomp.REGION_NAMES.get(gid, gid)}; o patch é da "
                                      f"versão {recomp.REGION_NAMES[want]}.")
            if cur is not None and os.path.normcase(os.path.abspath(cur.meta.get("game_root") or "")) == os.path.normcase(os.path.abspath(root)):
                raise pj.ProjectError("Esse é o jogo do projeto aberto agora. Para gravar nele, use Gravar no jogo.")

        def fn():
            if is_iso:
                tmp = os.path.join(os.path.dirname(out), ".soal_patch_temporario")
                shutil.rmtree(tmp, ignore_errors=True)
                try:
                    self._progress("Extraindo a ISO", 0, 0)
                    game = os.path.join(tmp, "jogo")
                    iso.extract(target, game)
                    gid = recomp.game_id(game)
                    if gid != want:
                        raise pj.ProjectError(f"Essa ISO é da versão {recomp.REGION_NAMES.get(gid or '', gid)}; o patch é da "
                                              f"versão {recomp.REGION_NAMES[want]}.")
                    q = pj.Project.create_or_open(game, os.path.join(tmp, "projeto"), progress=self._progress)
                    self._progress("Aplicando o patch", 0, 0)
                    r = patch.apply(q, data)
                    b = q.build(progress=self._progress)
                    res = iso.build(game, out, progress=self._progress, cancelled=lambda: self.cancel)
                    return {"patch": r, "build": b, "iso": res, "dest": out}
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
            q = pj.Project.create_or_open(root, progress=self._progress)
            self._progress("Aplicando o patch", 0, 0)
            r = patch.apply(q, data)
            b = q.build(progress=self._progress)
            q.save(force=True)
            # o projeto do destino fica na lista de recentes, para reaplicar ou devolver os originais
            rec = [x for x in self.config.get("recent", []) if x.get("dir") != q.dir]
            rec.insert(1 if self.project is not None else 0,
                       {"dir": q.dir, "game": q.meta.get("game_root", ""), "region": q.meta.get("region", "us")})
            self.config["recent"] = rec[:6]
            self._save_config()
            return {"patch": r, "build": b, "dest": root, "project": q.dir, "recomp": recomp.is_recomp_game(root)}
        self.start_job("patch", fn)

    def make_iso(self, out_path: str, build_first: bool):
        p = self.need()
        root = p.meta.get("game_root") or ""
        if not iso.is_extracted_disc(root):
            raise pj.ProjectError("A pasta do jogo não está no formato extraído (sys/ e files/); "
                                  "não dá para gerar a imagem a partir dela.")
        out_path = (out_path or "").strip().strip('"') or self.iso_default(p)
        if not out_path.lower().endswith((".iso", ".gcm")):
            out_path += ".iso"
        d = os.path.dirname(os.path.abspath(out_path)) or "."
        os.makedirs(d, exist_ok=True)
        old = os.path.getsize(out_path) if os.path.isfile(out_path) else 0
        if shutil.disk_usage(d).free + old < iso.DISC_SIZE + 64 * 1024 * 1024:
            raise pj.ProjectError("Não há espaço livre suficiente nesse disco: a imagem ocupa cerca de 1,4 GB.")

        def fn():
            res = {}
            if build_first:
                res["build"] = p.build(progress=self._progress)
            try:
                res["iso"] = iso.build(root, out_path, progress=self._progress,
                                       cancelled=lambda: self.cancel)
            except iso.IsoError as e:
                raise pj.ProjectError(str(e))
            return res
        self.start_job("iso", fn)

    # ------------------------------------------------------- traducao automatica
    def mt_cfg(self) -> dict:
        c = self.config.get("mt")
        return c if isinstance(c, dict) else {}

    def translator(self) -> "mt.Translator":
        return mt.Translator(mt.effective_config(self.mt_cfg()))

    def mt_file(self, fname: str):
        p = self.need()
        tr = self.translator()
        self.start_job("mt", lambda: p.mt_file(tr, fname, progress=self._progress,
                                               cancelled=lambda: self.cancel))

    def mt_names(self):
        p = self.need()
        tr = self.translator()
        self.start_job("mt", lambda: p.mt_names(tr, progress=self._progress, cancelled=lambda: self.cancel))

    def mt_story(self, first: int, last: int):
        p = self.need()
        tr = self.translator()
        self.start_job("mt", lambda: p.mt_story(tr, first, last, progress=self._progress,
                                                cancelled=lambda: self.cancel))

    def review_translator(self, provider: str) -> "mt.Translator":
        cfg = self.mt_cfg()
        choices = [c["id"] for c in mt.ai_choices(cfg)]
        if not choices:
            raise pj.ProjectError("Para revisar, configure em Ajustes um serviço de IA: Claude, Gemini (chave grátis) "
                                  "ou Ollama/LM Studio/OpenAI. DeepL, Google e LibreTranslate só traduzem.")
        if provider not in choices:
            provider = cfg.get("provider") if cfg.get("provider") in choices else choices[0]
        return mt.Translator(mt.config_for(cfg, provider))

    def review_run(self, provider: str, files: list, again: bool, only: str):
        p = self.need()
        tr = self.review_translator(provider)
        files = [f for f in files if f in p.by_name]
        if not files:
            raise pj.ProjectError("Nada para revisar.")
        self.start_job("mt", lambda: p.ai_review(tr, files, again, only, progress=self._progress,
                                                 cancelled=lambda: self.cancel))

    def need(self) -> pj.Project:
        if self.project is None:
            raise pj.ProjectError("Nenhum projeto aberto.")
        return self.project

    # ------------------------------------------------------------- consultas
    def state(self) -> dict:
        p = self.project
        try:
            found = recomp.find_install(self.config.get("recomp_hint"))
        except OSError:
            found = None
        recent = []
        for r in self.config.get("recent", []):
            r = dict(r)
            if not r.get("region"):
                gid = recomp.game_id(r.get("game") or "") if r.get("game") and os.path.isdir(r["game"]) else None
                r["region"] = pj.REGIONS.get(gid or "", "")
            r["exists"] = pj.is_project_dir(r.get("dir") or "")
            recent.append(r)
        out = {"version": VERSION, "job": dict(self.job), "recent": recent,
               "project": None, "recomp": found}
        if p is not None:
            old = p.meta.get("recomp_root")
            if old and not os.path.isdir(old):
                # a pasta de dados do recomp foi movida: procura de novo (o port deixa um
                # data-folder.txt apontando para o lugar novo)
                p.meta["recomp_root"] = None
                p.touch()
            if found and not p.meta.get("recomp_root"):
                # lembra onde o recomp esta'; gravar nele continua sendo escolha do usuario
                mine = recomp.find_region("GEAP8P" if p.eu else "GEAE8P", self.config.get("recomp_hint"))
                if mine and os.path.normcase(mine["game_root"]) != os.path.normcase(os.path.abspath(p.meta.get("game_root") or "")):
                    p.meta["recomp_root"] = mine["game_root"]
                    p.touch()
            out["project"] = {
                "dir": p.dir, "game_root": p.meta.get("game_root"), "game_field": p.meta.get("game_field"),
                "has_font": bool(p.orig_font), "settings": p.settings,
                "free_slots": pj.FREE_SLOTS, "summary": p.summary(),
                "not_original": p.meta.get("not_original") or [],
                "region": p.meta.get("region", "us"), "game_id": p.meta.get("game_id", ""),
                "is_recomp": recomp.is_recomp_game(p.meta.get("game_root") or ""),
                "recomp_root": p.meta.get("recomp_root"), "use_recomp": bool(p.meta.get("use_recomp")),
                "targets": [{"root": t["root"], "recomp": t["recomp"]} for t in p.targets()],
                "tool_dir_suggestion": os.path.join(pj.tool_dir(), "projetos", os.path.basename(p.dir.rstrip("\\/"))),
                "backup_dir": p.settings.get("backup_dir") or "",
                "iso_default": self.iso_default(p),
                "can_iso": iso.is_extracted_disc(p.meta.get("game_root") or ""),
                "backups": p.backup_list()[:5],
            }
        return out

    def glyphs(self) -> dict:
        """Desenhos da fonte do jogo (12x24, um digito hexadecimal por pixel) para a previa."""
        p = self.need()
        if self._glyph_cache is not None:
            return self._glyph_cache
        out = {"w": fontmod.HALF, "h": fontmod.CELL, "glyphs": {}, "ok": False}
        of = p.orig_font
        if of:
            try:
                with open(of, "rb") as fh:
                    fnt = fontmod.Font(fh.read())

                def pack(g):
                    return "".join("%x" % v for row in g for v in row)
                codes = list(range(0x21, 0x7F))
                if p.eu:
                    codes += [c for c in range(0x80, 0x100) if fnt.has_code(c)]
                for code in codes:
                    ch = chr(code)
                    if code == 0x5B:
                        ch = text.LQUOTE
                    elif code == 0x5D:
                        ch = text.RQUOTE
                    elif code == 0x5C:
                        continue
                    elif code == text.EU_ELLIPSIS:
                        ch = text.ELLIPSIS
                    elif 0x80 <= code < 0xA1:
                        continue
                    try:
                        out["glyphs"][ch] = pack(fnt.glyph(code))
                    except fontmod.FontError:
                        continue
                accents = {}
                for ch in "áàâãäéèêíìîóòôõö" \
                          "úùûüçñÁÀÂÃÉÊÍÓ" \
                          "ÔÕÚÜÇÑ":
                    g = fontmod.accented_glyph(fnt, ch)
                    if g:
                        accents[ch] = pack(g)
                out["accents"] = accents
                out["ok"] = True
            except (fontmod.FontError, OSError):
                pass
        self._glyph_cache = out
        return out


def pick_folder(kind: str = "", title: str = "") -> Optional[str]:
    """Abre a janela de escolher pasta do sistema num processo separado (o tkinter precisa
    da linha principal do programa). No .exe, o proprio executavel faz esse papel."""
    import tempfile
    fd, out = tempfile.mkstemp(prefix="soal_pasta_", suffix=".txt")
    os.close(fd)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
    kind = kind if kind in ("patch", "iso", "") else ""
    title = (title or "")[:120]
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--escolher-pasta", out, kind, title]
    else:
        exe = sys.executable
        if sys.platform.startswith("win"):
            w = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(w):
                exe = w
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cmd = [exe, "-c", "import sys; sys.path.insert(0, sys.argv[1]); from soal import picker; picker.run(*sys.argv[2:])",
               root, out, kind, title]
    try:
        subprocess.run(cmd, timeout=600, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, creationflags=flags)
        with open(out, encoding="utf-8") as fh:
            path = fh.read().strip()
        return os.path.normpath(path) if path else None
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.remove(out)
        except OSError:
            pass


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SOALTradutor/" + VERSION

        def log_message(self, fmt, *args):  # silencioso
            pass

        # ----------------------------------------------------------- respostas
        def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _local(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        # ----------------------------------------------------------------- GET
        def do_GET(self):
            if not self._local():
                return self._send(403, b"forbidden", "text/plain")
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            try:
                if u.path in ("/", "/index.html"):
                    with open(os.path.join(WEB_DIR, "index.html"), "rb") as fh:
                        return self._send(200, fh.read(), "text/html; charset=utf-8")
                if u.path == "/api/state":
                    return self._json(app.state())
                if u.path == "/api/job":
                    return self._json(app.job)
                if u.path == "/api/ping":
                    app.last_ping = time.time()
                    return self._json({"ok": True})
                if u.path == "/api/file":
                    return self._json(app.need().file_entries(q.get("name", [""])[0]))
                if u.path == "/api/search":
                    return self._json({"results": app.need().search(q.get("q", [""])[0])})
                if u.path == "/api/names":
                    return self._json({"names": app.need().name_list()})
                if u.path == "/api/mt":
                    return self._json(mt.public_config(app.mt_cfg()))
                if u.path == "/api/glyphs":
                    return self._json(app.glyphs())
                if u.path == "/api/dub/wav":
                    data = app.need().dub_wav(q.get("key", [""])[0], q.get("v", ["orig"])[0])
                    return self._send(200, data, "audio/wav")
                if u.path == "/api/font":
                    from . import intro as _intro
                    f = _intro.FONTS.get(q.get("n", [""])[0])
                    if not f:
                        return self._send(404, b"not found", "text/plain")
                    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fontes", f[0]), "rb") as fh:
                        return self._send(200, fh.read(), "font/ttf", {"Cache-Control": "max-age=86400"})
                if u.path == "/api/img/catalog":
                    return self._json(app.need().img_catalog())
                if u.path == "/api/img/file":
                    return self._json(app.need().img_file(q.get("id", [""])[0], q.get("ref", [""])[0] or None))
                if u.path == "/api/img/search":
                    return self._json({"results": app.need().img_search(q.get("q", [""])[0])})
                if u.path == "/api/img/png":
                    png = app.need().img_png(q.get("id", [""])[0], int(q.get("n", ["0"])[0]), q.get("v", ["orig"])[0])
                    return self._send(200, png, "image/png", {"Cache-Control": "no-store"})
                if u.path == "/api/intro":
                    n = int(q.get("n", ["0"])[0])
                    t = q.get("t", [""])[0]
                    png = app.need().intro_page(n, t or None, q.get("font", [""])[0] or None)
                    return self._send(200, png, "image/png", {"Cache-Control": "no-store"})
                if u.path == "/api/export_unicas.csv":
                    data = app.need().export_unique_csv()
                    return self._send(200, data, "text/csv; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="soal_textos_para_traduzir.csv"'})
                if u.path == "/api/export.csv":
                    data = app.need().export_csv()
                    return self._send(200, data, "text/csv; charset=utf-8",
                                      {"Content-Disposition": 'attachment; filename="soal_traducao.csv"'})
                return self._send(404, b"not found", "text/plain")
            except pj.ProjectError as exc:
                return self._json({"error": str(exc)}, 400)
            except Exception as exc:
                traceback.print_exc()
                return self._json({"error": f"Erro inesperado: {exc}"}, 500)

        # ---------------------------------------------------------------- POST
        def do_POST(self):
            if not self._local() or self.headers.get("X-SOAL") != "1":
                return self._send(403, b"forbidden", "text/plain")
            u = urllib.parse.urlparse(self.path)
            raw = self._body()
            try:
                if u.path == "/api/import":
                    return self._json(app.need().import_csv(raw))
                data = json.loads(raw.decode("utf-8")) if raw else {}
                if u.path == "/api/pick":
                    return self._json({"path": pick_folder(data.get("kind") or "", data.get("title") or "")})
                if u.path == "/api/open":
                    if data.get("project_dir"):
                        app.open_project(data["project_dir"])
                    else:
                        root = (data.get("game_root") or "").strip().strip('"')
                        if not root or not os.path.isdir(root):
                            raise pj.ProjectError("Essa pasta nao existe. Confira o caminho.")
                        app.open_game(root)
                    return self._json({"ok": True})
                if u.path == "/api/save":
                    r = app.need().set_translation(data["file"], data["k"], data.get("t", ""), data.get("st"))
                    return self._json(r)
                if u.path == "/api/status":
                    app.need().set_status(data["file"], data["k"], data.get("st", ""))
                    return self._json({"ok": True})
                if u.path == "/api/name":
                    app.need().set_name(data["name"], data.get("t", ""))
                    return self._json({"ok": True})
                if u.path == "/api/settings":
                    p = app.need()
                    with p.lock:
                        st = p.settings
                        if "cols" in data:
                            st["cols"] = max(10, min(80, int(data["cols"])))
                        if "lines" in data:
                            st["lines"] = max(1, min(8, int(data["lines"])))
                        if data.get("accents") in ("font", "strip"):
                            st["accents"] = data["accents"]
                        if "autofill" in data:
                            st["autofill"] = bool(data["autofill"])
                        if "keep_states" in data:
                            st["keep_states"] = bool(data["keep_states"])
                        if data.get("eu_slot") in pj.EU_SLOTS:
                            st["eu_slot"] = data["eu_slot"]
                        if data.get("mt_source") in pj.EU_SLOTS:
                            st["mt_source"] = data["mt_source"]
                        if data.get("intro_font") in intro.FONTS:
                            st["intro_font"] = data["intro_font"]
                        if isinstance(data.get("charmap"), dict):
                            cm = {}
                            used = set()
                            for ch, sym in data["charmap"].items():
                                if (isinstance(ch, str) and isinstance(sym, str) and len(ch) == 1
                                        and len(sym) == 1 and sym in pj.FREE_SLOTS and sym not in used):
                                    cm[ch] = sym
                                    used.add(sym)
                            st["charmap"] = cm
                        p.touch()
                    p.save()
                    return self._json({"settings": p.settings})
                if u.path == "/api/mt/config":
                    cur = dict(app.mt_cfg())
                    prov = data.get("provider", "")
                    if prov and prov not in mt.PROVIDERS:
                        raise pj.ProjectError("serviço desconhecido")
                    salvos = cur.get("salvos") if isinstance(cur.get("salvos"), dict) else {}
                    old = cur.get("provider") or ""
                    if prov != old:
                        # guarda chave, endereco e modelo do servico anterior e traz os do novo
                        if old:
                            salvos[old] = {f: cur.get(f) or "" for f in ("key", "url", "model")}
                        back = salvos.get(prov) or {}
                        for f in ("key", "url", "model"):
                            cur[f] = back.get(f) or ""
                    cur["salvos"] = salvos
                    cur["provider"] = prov
                    used = mt.FIELDS.get(prov, ())
                    for k in ("url", "model"):
                        if k in data and k in used:
                            cur[k] = str(data[k]).strip()
                    if data.get("key"):
                        cur["key"] = str(data["key"]).strip()
                    if data.get("clear_key"):
                        cur["key"] = ""
                    app.config["mt"] = cur
                    app._save_config()
                    return self._json(mt.public_config(cur))
                if u.path == "/api/mt/test":
                    t = app.translator().translate("Hey, Fina! How are you feeling?\nLooks like it's going to be a piece of cake.",
                                                   "Vyse", None, False)
                    return self._json({"t": t})
                if u.path == "/api/mt/one":
                    p = app.need()
                    t = p.mt_suggest(app.translator(), data["file"], data["k"])
                    r = p.set_translation(data["file"], data["k"], t, "mt")
                    return self._json({"t": t, "filled": r["filled"]})
                if u.path == "/api/mt/story_info":
                    return self._json({"chapters": app.need().story_info()})
                if u.path == "/api/mt/story":
                    app.mt_story(int(data.get("from", 0)), int(data.get("to", 0)))
                    return self._json({"ok": True})
                if u.path == "/api/img/save":
                    b64 = str(data.get("png") or "")
                    if "," in b64[:80]:
                        b64 = b64.split(",", 1)[1]
                    try:
                        png = base64.b64decode(b64, validate=False)
                    except (ValueError, binascii.Error):
                        raise pj.ProjectError("Imagem inválida.")
                    return self._json(app.need().img_save(data.get("id"), int(data.get("n", 0)), png))
                if u.path == "/api/img/reset":
                    return self._json(app.need().img_reset(data.get("id"), int(data.get("n", 0))))
                if u.path == "/api/img/add":
                    return self._json(app.need().img_add(data.get("id")))
                if u.path == "/api/terms":
                    p = app.need()
                    return self._json({"termos": p.set_terms(data.get("termos"))})
                if u.path == "/api/terms/check":
                    p = app.need()
                    return self._json(p.standardize(bool(data.get("apply"))))
                if u.path == "/api/suggest/apply":
                    p = app.need()
                    return self._json(p.apply_suggestions(data.get("file") or None))
                if u.path == "/api/review/info":
                    p = app.need()
                    return self._json({"choices": mt.ai_choices(app.mt_cfg()),
                                       "chapters": p.review_info(bool(data.get("again")), data.get("only") or "all"),
                                       "pending": len(p.review_list())})
                if u.path == "/api/review/run":
                    p = app.need()
                    if data.get("file"):
                        files = [data["file"]]
                    else:
                        ch = p.story_groups()
                        a, b = int(data.get("from", 0)), int(data.get("to", 0))
                        files = [fn for i in range(max(0, a), min(len(ch) - 1, b) + 1) for fn in ch[i][1]]
                    app.review_run(data.get("provider") or "", files, bool(data.get("again")),
                                   data.get("only") or "all")
                    return self._json({"ok": True})
                if u.path == "/api/review/decide":
                    return self._json(app.need().review_decide(data["file"], data["k"], bool(data.get("accept"))))
                if u.path == "/api/review/accept_all":
                    return self._json(app.need().review_accept_all(data["file"]))
                if u.path == "/api/review/list":
                    return self._json({"list": app.need().review_list()})
                if u.path == "/api/mt/names":
                    app.mt_names()
                    return self._json({"ok": True})
                if u.path == "/api/mt/file":
                    app.mt_file(data["file"])
                    return self._json({"ok": True})
                if u.path == "/api/job/cancel":
                    app.cancel = True
                    return self._json({"ok": True})
                if u.path == "/api/recomp":
                    root = (data.get("root") or "").strip().strip('"')
                    if root:
                        found = recomp.find_install(root)
                        if found:
                            a_, b_ = os.path.normcase(os.path.abspath(root)), os.path.normcase(found["data_dir"])
                            if not (a_.startswith(b_) or b_.startswith(a_)):
                                found = None
                        if not found:
                            raise pj.ProjectError(
                                "Nao achei um jogo importado pelo recomp nessa pasta. Indique a pasta de "
                                "dados do port (a que tem 'games' e 'StateSaves') ou a pasta do programa.")
                        app.config["recomp_hint"] = root
                        app._save_config()
                        root = found["game_root"]
                    app.need().set_recomp(root or None, bool(data.get("use")))
                    return self._json({"ok": True})
                if u.path == "/api/remaster/info":
                    return self._json(app.remaster_info())
                if u.path == "/api/remaster/extract":
                    app.remaster_extract(data.get("files") or "", (data.get("out") or "").strip().strip('"'),
                                         list(data.get("what") or []), list(data.get("folders") or []))
                    return self._json({"ok": True})
                if u.path == "/api/remaster/install":
                    app.remaster_install((data.get("src") or "").strip().strip('"'))
                    return self._json({"ok": True})
                if u.path == "/api/remaster/check":
                    return self._json(app.remaster_check((data.get("out") or "").strip().strip('"')))
                if u.path == "/api/remaster/open":
                    d = (data.get("dir") or "").strip()
                    if d and os.path.isdir(d) and sys.platform.startswith("win"):
                        os.startfile(d)  # noqa: abre a pasta no Explorer
                    return self._json({"ok": bool(d and os.path.isdir(d))})
                if u.path == "/api/dub/info":
                    return self._json(app.dub_info())
                if u.path == "/api/dub/extract":
                    app.dub_extract((data.get("out") or "").strip().strip('"'), list(data.get("groups") or []))
                    return self._json({"ok": True})
                if u.path == "/api/dub/import":
                    app.dub_import((data.get("src") or "").strip().strip('"'))
                    return self._json({"ok": True})
                if u.path == "/api/dub/remove":
                    return self._json(app.need().dub_remove(data.get("key") if not data.get("all") else None))
                if u.path == "/api/patch/create":
                    app.patch_create(data.get("path") or "")
                    return self._json({"ok": True})
                if u.path == "/api/patch/apply":
                    app.patch_apply(data.get("patch") or "", data.get("target") or "", data.get("iso_out") or "")
                    return self._json({"ok": True})
                if u.path == "/api/patch/default":
                    return self._json({"path": app.patch_default(app.need())})
                if u.path == "/api/import_project":
                    pr = app.need()
                    r = pr.import_project(data.get("dir") or "")
                    return self._json({"ok": True, "result": r, "summary": pr.summary()})
                if u.path == "/api/iso":
                    app.make_iso(data.get("path") or "", bool(data.get("build", True)))
                    return self._json({"ok": True})
                if u.path == "/api/build":
                    app.build()
                    return self._json({"ok": True})
                if u.path == "/api/restore":
                    return self._json(app.need().restore_originals())
                if u.path == "/api/project/move":
                    app.move_project(data.get("dir") or "")
                    return self._json({"ok": True})
                if u.path == "/api/backup/dir":
                    pr = app.need()
                    d = (data.get("dir") or "").strip().strip('"')
                    if d:
                        d = os.path.abspath(d)
                        if os.path.normcase(d).startswith(os.path.normcase(pr.dir.rstrip("\\/") + os.sep)) or \
                                os.path.normcase(d) == os.path.normcase(pr.dir):
                            raise pj.ProjectError("A pasta de cópias precisa ficar fora da pasta do projeto.")
                        os.makedirs(d, exist_ok=True)
                    with pr.lock:
                        pr.settings["backup_dir"] = d
                        pr.touch()
                    pr.save()
                    made = pr.backup(force=True) if d else None
                    return self._json({"ok": True, "made": made, "backups": pr.backup_list()[:5]})
                if u.path == "/api/backup/now":
                    pr = app.need()
                    if not pr.backup_root():
                        raise pj.ProjectError("Escolha primeiro a pasta das cópias de segurança.")
                    made = pr.backup(force=True)
                    return self._json({"ok": True, "made": made, "backups": pr.backup_list()[:5]})
                if u.path == "/api/close":
                    if app.project is not None:
                        app.project.save()
                        try:
                            app.project.backup()
                        except OSError:
                            pass
                    app.project = None
                    return self._json({"ok": True})
                return self._send(404, b"not found", "text/plain")
            except (pj.ProjectError, mt.MTError, KeyError, ValueError) as exc:
                msg = str(exc) if isinstance(exc, (pj.ProjectError, mt.MTError)) else f"Pedido invalido ({exc})"
                return self._json({"error": msg}, 400)
            except Exception as exc:
                traceback.print_exc()
                return self._json({"error": f"Erro inesperado: {exc}"}, 500)

    return Handler


class _Server(ThreadingHTTPServer):
    """Servidor que nao divide a porta com outro programa.

    O padrao do Python liga SO_REUSEADDR, e no Windows isso deixa um segundo programa abrir a
    mesma porta de um que ja' esta' rodando: a janela nova acabava falando com a versao antiga
    ainda aberta em segundo plano. Aqui a porta e' exclusiva; se estiver ocupada, usa a seguinte."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        import socket
        excl = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if excl is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, excl, 1)
        super().server_bind()


def serve(port: int = 8787, open_browser: bool = True, reopen_last: bool = True, window: bool = True):
    """window=True abre numa janela propria (Edge/Chrome no modo aplicativo) e encerra quando
    ela fecha. Sem Edge/Chrome, ou com window=False, abre no navegador padrao."""
    app = App()
    httpd = None
    for p in range(port, port + 20):
        try:
            httpd = _Server(("127.0.0.1", p), make_handler(app))
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit("Nao consegui abrir uma porta local para a interface.")
    url = f"http://127.0.0.1:{port}/"
    if reopen_last:
        rec = app.config.get("recent") or []
        if rec and os.path.exists(os.path.join(rec[0].get("dir", ""), pj.PROJECT_FILE)):
            try:
                app.open_project(rec[0]["dir"])
            except pj.ProjectError:
                pass
    print("SOAL Tradutor", VERSION)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    proc = None
    started = time.time()
    if open_browser and window:
        proc = janela.open_window(url)
        if proc is None:
            print("Edge/Chrome nao encontrado: abrindo no navegador padrao.")
    if open_browser and proc is None:
        import webbrowser
        webbrowser.open(url)
    print("Interface em", url)
    try:
        while True:
            time.sleep(1.0)
            if proc is not None and proc.poll() is not None:
                if time.time() - started > 3:
                    break                        # a janela foi fechada
                proc = None                      # o Edge passou a janela para outro processo
            if proc is None and open_browser and window and app.last_ping:
                # sem processo para acompanhar: encerra quando a pagina para de dar sinal
                if time.time() - app.last_ping > 150 and not app.job.get("running"):
                    break
    except KeyboardInterrupt:
        pass
    finally:
        if app.project is not None:
            try:
                app.project.save()
                app.project.backup()
            except OSError:
                pass
        httpd.shutdown()
        httpd.server_close()
