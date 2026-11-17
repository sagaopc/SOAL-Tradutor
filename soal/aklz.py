"""AKLZ: compressao LZSS usada pelos arquivos do Skies of Arcadia Legends.

Formato: 12 bytes de assinatura, tamanho descomprimido (u32 big-endian) e um
fluxo LZSS classico (janela de 4096 bytes, copias de 3 a 18 bytes, escrita da
janela comecando em 0xFEE, bits de controle lidos do menos significativo).
"""

SIGNATURE = b"AKLZ~?Qd=\xcc\xcc\xcd"
_N = 4096
_F = 18
_THRESHOLD = 2


def is_compressed(data: bytes) -> bool:
    return data[:12] == SIGNATURE


def decompress(data: bytes) -> bytes:
    """A janela de 4 KB e' a propria saida (a escrita na janela comeca em 0xFEE e a janela
    comeca zerada): uma copia da posicao `off` da janela le `d` bytes atras na saida."""
    if not is_compressed(data):
        return bytes(data)
    size = int.from_bytes(data[12:16], "big")
    out = bytearray()
    pos = 16
    end = len(data)
    start = _N - _F
    while len(out) < size and pos < end:
        flags = data[pos]
        pos += 1
        if flags == 0xFF and pos + 8 <= end:        # 8 bytes literais
            out += data[pos:pos + 8]
            pos += 8
            continue
        for _ in range(8):
            if len(out) >= size or pos >= end:
                break
            if flags & 1:
                out.append(data[pos])
                pos += 1
            else:
                if pos + 1 >= end:
                    pos = end
                    break
                b1, b2 = data[pos], data[pos + 1]
                pos += 2
                offset = b1 | ((b2 & 0xF0) << 4)
                length = (b2 & 0x0F) + _THRESHOLD + 1
                o = len(out)
                dist = ((start + o) - offset) & (_N - 1) or _N
                src = o - dist
                if src >= 0 and dist >= length:
                    out += out[src:src + length]
                elif src >= 0:                           # copia que se sobrepoe: repete o padrao
                    pat = out[src:o]
                    out += (pat * (length // dist + 1))[:length]
                else:                                    # antes do comeco: janela zerada
                    for k in range(length):
                        i = src + k
                        out.append(out[i] if i >= 0 else 0)
            flags >>= 1
    if len(out) > size:
        del out[size:]
    if len(out) != size:
        raise ValueError(f"AKLZ: esperado {size} bytes, obtido {len(out)}")
    return bytes(out)


def compress(data: bytes) -> bytes:
    """Compressor LZSS guloso com tabela de hash (rapido o bastante em Python)."""
    data = bytes(data)
    n = len(data)
    out = bytearray(SIGNATURE)
    out += n.to_bytes(4, "big")
    table = {}  # prefixo de 3 bytes -> lista de posicoes recentes
    i = 0

    def add(p):
        if p + 3 <= n:
            key = data[p:p + 3]
            lst = table.get(key)
            if lst is None:
                table[key] = [p]
            else:
                lst.append(p)
                if len(lst) > 48:
                    del lst[:16]

    while i < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if i >= n:
                break
            best_len = 0
            best_pos = 0
            if i + 3 <= n:
                cands = table.get(data[i:i + 3])
                if cands:
                    max_len = min(_F, n - i)
                    lo = i - (_N - _F)  # distancia segura dentro da janela
                    for p in reversed(cands):
                        if p < lo:
                            break
                        l = 3
                        while l < max_len and data[p + l] == data[i + l]:
                            l += 1
                        if l > best_len:
                            best_len = l
                            best_pos = p
                            if l == max_len:
                                break
            if best_len >= 3:
                woff = (best_pos + _N - _F) & (_N - 1)
                out.append(woff & 0xFF)
                out.append(((woff >> 4) & 0xF0) | (best_len - 3))
                for p in range(i, i + best_len):
                    add(p)
                i += best_len
            else:
                flags |= 1 << bit
                out.append(data[i])
                add(i)
                i += 1
        out[flag_pos] = flags
    return bytes(out)
