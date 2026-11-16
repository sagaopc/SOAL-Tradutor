"""Janela de escolher pasta ou arquivo (tkinter), rodada num processo separado."""
import sys

KINDS = {
    "patch": ("Patch de tradução", [("Patch do SOAL Tradutor", "*.soalpatch"), ("Todos os arquivos", "*.*")]),
    "iso": ("Imagem do jogo", [("Imagem de GameCube", "*.iso *.gcm"), ("Todos os arquivos", "*.*")]),
}


def run(out_path: str, kind: str = "", title: str = "") -> None:
    path = ""
    try:
        import tkinter
        import tkinter.filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if kind in KINDS:
            t, types = KINDS[kind]
            path = tkinter.filedialog.askopenfilename(title=title or t, filetypes=types) or ""
        else:
            path = tkinter.filedialog.askdirectory(title=title or "Pasta do jogo extraído") or ""
        root.destroy()
    finally:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(path)


if __name__ == "__main__":
    run(*sys.argv[1:])
