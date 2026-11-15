"""Gera soal/data/vocabulario.json a partir de tools/vocabulario_fonte.txt."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    out = {"nomes": {}, "materiais": [], "adjetivos": {}, "expressoes": {}}
    sec = None
    with open(os.path.join(ROOT, "tools", "vocabulario_fonte.txt"), encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                sec = line[1:-1]
                continue
            if sec == "materiais":
                out["materiais"].append(line.lower())
                continue
            en, _, rest = line.partition("=")
            en = en.strip().lower()
            parts = [x.strip() for x in rest.split("/")] if sec != "expressoes" else [rest.strip()]
            if sec == "nomes":
                out["nomes"][en] = parts
            elif sec == "adjetivos":
                out["adjetivos"][en] = parts
            elif sec == "expressoes":
                out["expressoes"][en] = parts[0]
    with open(os.path.join(ROOT, "soal", "data", "vocabulario.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=0, sort_keys=True)
    print({k: len(v) for k, v in out.items()})


if __name__ == "__main__":
    main()
