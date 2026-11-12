#!/usr/bin/env python3
"""Confere se o programa consegue ler e reconstruir todos os .sct de uma pasta.

Uso:  python tools/verificar.py "F:\\Downloads\\Skies of arcadia legends"

Para cada arquivo: (1) reconstrui sem mudar nada e compara byte a byte com o
original; (2) aumenta todos os textos, reconstrui, le de novo e confere se cada
referencia do script continua apontando para o mesmo lugar. Nada e' gravado.
"""
import os
import sys
from bisect import bisect_right

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from soal import project, sct, text  # noqa: E402


def where(s, pos):
    starts = [x.start for x in s.sections]
    k = bisect_right(starts, pos) - 1
    while k >= 0 and not (s.sections[k].start <= pos < s.sections[k].end):
        k -= 1
    if k < 0:
        return ("?", pos)
    if k == len(s.sections) - 1 and pos >= s.footer_start:
        nul = s.body.find(b"\0", pos)
        return ("rodape", s.body[pos:nul])
    return (k, pos - s.sections[k].start)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    field, _ = project.find_game(sys.argv[1])
    names = sorted((f for f in os.listdir(field) if f.lower().endswith(".sct")), key=str.lower)
    bad = 0
    texts = links = 0
    enc = text.Encoder()
    for fi, name in enumerate(names):
        try:
            s = sct.load(os.path.join(field, name))
            errs = list(s.problems)
            if s.rebuild(compress=False) != s.raw:
                errs.append("a reconstrucao sem mudancas nao ficou identica")
            new = {}
            for n, sec in enumerate(s.string_sections()):
                raw = s.text_bytes(sec)
                texts += 1
                try:
                    if enc.encode(text.decode(raw)) != raw:
                        errs.append(f"texto {sec.name} nao volta igual")
                except text.TextError as exc:
                    errs.append(f"texto {sec.name}: {exc}")
                new[sec.index] = raw + b"#" * ((n * 7 + fi) % 23)
            s2 = sct.SctFile(s.rebuild(new, compress=False), name)
            errs += s2.problems
            a = sorted(s.links, key=lambda l: l.origin)
            b = sorted(s2.links, key=lambda l: l.origin)
            if len(a) != len(b):
                errs.append("quantidade de referencias mudou")
            else:
                wrong = sum(1 for x, y in zip(a, b)
                            if where(s, x.origin) != where(s2, y.origin) or where(s, x.target) != where(s2, y.target))
                if wrong:
                    errs.append(f"{wrong} referencias apontam para outro lugar")
                links += len(a)
        except Exception as exc:  # qualquer falha conta como problema do arquivo
            errs = [repr(exc)]
        if errs:
            bad += 1
            print(f"PROBLEMA  {name}: {errs[0]}" + (f" (+{len(errs) - 1})" if len(errs) > 1 else ""))
        if (fi + 1) % 25 == 0:
            print(f"  ... {fi + 1} de {len(names)}")
    print(f"\n{len(names)} arquivos, {texts} textos, {links} referencias conferidas.")
    print("Tudo certo." if not bad else f"{bad} arquivos com problema.")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
