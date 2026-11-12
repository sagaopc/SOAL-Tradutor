"""Abre a interface numa janela propria (sem abas nem barra de endereco).

Usa o modo "aplicativo" do Microsoft Edge, que vem instalado no Windows 10 e 11, ou do
Google Chrome/Chromium. A janela roda com um perfil separado (nao mistura com o
navegador do usuario), e quando ela e' fechada o programa termina.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import List, Optional


def _windows_candidates() -> List[str]:
    out = []
    try:
        import winreg  # type: ignore
        for exe in ("msedge.exe", "chrome.exe"):
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + exe) as k:
                        v, _ = winreg.QueryValueEx(k, None)
                        if v:
                            out.append(v)
                except OSError:
                    pass
    except ImportError:
        pass
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        out.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
        out.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    return out


def find_browser() -> Optional[str]:
    """Caminho do Edge ou do Chrome capaz de abrir no modo aplicativo."""
    env = os.environ.get("SOAL_NAVEGADOR")
    if env and os.path.exists(env):
        return env
    if sys.platform.startswith("win"):
        cands = _windows_candidates()
    elif sys.platform == "darwin":
        cands = ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                 "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    else:
        cands = [shutil.which(n) or "" for n in ("microsoft-edge", "microsoft-edge-stable", "google-chrome",
                                                  "google-chrome-stable", "chromium", "chromium-browser")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return None


def profile_dir() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "SOAL Tradutor", "janela")
    return os.path.join(os.path.expanduser("~"), ".soal_tradutor_janela")


def open_window(url: str, width: int = 1400, height: int = 900) -> Optional[subprocess.Popen]:
    """Abre a janela. Devolve o processo (para saber quando ela fecha) ou None."""
    exe = find_browser()
    if not exe:
        return None
    prof = profile_dir()
    os.makedirs(prof, exist_ok=True)
    args = [exe, "--app=" + url, "--user-data-dir=" + prof, f"--window-size={width},{height}",
            "--no-first-run", "--no-default-browser-check", "--disable-sync",
            "--disable-features=Translate,msEdgeTranslate,msUndersideButton,msHubApps",
            "--disable-extensions"]
    extra = os.environ.get("SOAL_JANELA_FLAGS")
    if extra:
        args += extra.split()
    flags = 0
    if sys.platform.startswith("win"):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=flags)
    except OSError:
        return None
