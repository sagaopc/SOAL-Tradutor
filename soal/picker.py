"""Janela de escolher pasta (tkinter), rodada num processo separado."""
import sys


def run(out_path: str, title: str = "Pasta do jogo extraído") -> None:
    path = ""
    try:
        import tkinter
        import tkinter.filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = tkinter.filedialog.askdirectory(title=title) or ""
        root.destroy()
    finally:
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(path)


if __name__ == "__main__":
    run(sys.argv[1])
