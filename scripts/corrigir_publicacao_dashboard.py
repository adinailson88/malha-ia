#!/usr/bin/env python3
"""
Corrige problemas de publicacao do dashboard Malha IA.

Acoes:
1. Corrige mojibake UTF-8/Latin-1 em dashboard.html, quando detectado.
2. Remove CHAMADOS da lista de abas sempre online, permitindo consumo de dados/chamados.json.
3. Mantem fallback para Apps Script caso o JSON estatico falhe.

Nao altera dados brutos nem remove fallback.
"""
from __future__ import annotations

from pathlib import Path

DASHBOARD = Path("dashboard.html")


def score_mojibake(texto: str) -> int:
    marcadores = ["Ã", "Â", "â€”", "â€“", "â€", "â‰", "â†", "Î", "Å"]
    return sum(texto.count(m) for m in marcadores)


def corrigir_mojibake(texto: str) -> tuple[str, bool]:
    antes = score_mojibake(texto)
    if antes == 0:
        return texto, False

    try:
        candidato = texto.encode("latin1").decode("utf-8")
    except UnicodeError:
        return texto, False

    depois = score_mojibake(candidato)
    if depois < antes:
        return candidato, True
    return texto, False


def corrigir_abas_online(texto: str) -> tuple[str, bool]:
    bloco_antigo = """const ABAS_SEMPRE_ONLINE = new Set([\n  'CHAMADOS',\n  'LOG_CLASSIFICACAO'\n]);"""
    bloco_novo = """const ABAS_SEMPRE_ONLINE = new Set([\n  'LOG_CLASSIFICACAO'\n]);"""

    if bloco_antigo in texto:
        return texto.replace(bloco_antigo, bloco_novo), True

    # fallback para caso o arquivo ja tenha sido parcialmente alterado
    if "const ABAS_SEMPRE_ONLINE = new Set([" in texto and "'CHAMADOS'" in texto:
        return texto.replace("  'CHAMADOS',\n", ""), True

    return texto, False


def main() -> int:
    if not DASHBOARD.exists():
        raise SystemExit("dashboard.html nao encontrado.")

    texto = DASHBOARD.read_text(encoding="utf-8-sig")
    original = texto

    texto, enc_corrigido = corrigir_mojibake(texto)
    texto, abas_corrigidas = corrigir_abas_online(texto)

    if texto != original:
        DASHBOARD.write_text(texto, encoding="utf-8", newline="\n")
        print("dashboard.html atualizado.")
        print(f"Mojibake corrigido: {enc_corrigido}")
        print(f"CHAMADOS removido de ABAS_SEMPRE_ONLINE: {abas_corrigidas}")
    else:
        print("dashboard.html sem alteracoes necessarias.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
