#!/usr/bin/env python3
"""Patch conservador do dashboard para ler JSON estatico antes do Apps Script."""

from __future__ import annotations

import re
from pathlib import Path

ARQUIVO = Path("dashboard_malha_ia_v36.html")

NOVO_BLOCO = '''const DADOS_JSON_BASE = "dados";
const USAR_JSON_ESTATICO = true;
const DADOS_JSON_CACHE_BUSTER = Math.floor(Date.now() / (15 * 60 * 1000));

function slugArquivoDados(nomeAba) {
  return (nomeAba || '')
    .toString()
    .normalize('NFD')
    .replace(/[\\u0300-\\u036f]/g, '')
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase() || 'aba';
}

async function fetchAba(nomeAba) {
  if (USAR_JSON_ESTATICO) {
    const arquivo = `${DADOS_JSON_BASE}/${slugArquivoDados(nomeAba)}.json`;
    try {
      const respJson = await fetch(`${arquivo}?v=${DADOS_JSON_CACHE_BUSTER}`, { cache: 'force-cache' });
      if (respJson.ok) {
        const dataJson = await respJson.json();
        if (Array.isArray(dataJson)) {
          registrarLog(`Aba ${nomeAba}: JSON estático`, 'info');
          return dataJson;
        }
        registrarLog(`Aba ${nomeAba}: JSON inválido; usando Apps Script`, 'warn');
      } else if (respJson.status !== 404) {
        registrarLog(`Aba ${nomeAba}: JSON HTTP ${respJson.status}; usando Apps Script`, 'warn');
      }
    } catch (e) {
      registrarLog(`Aba ${nomeAba}: JSON indisponível (${e.message}); usando Apps Script`, 'warn');
    }
  }

  try {
    const url = `${APPS_SCRIPT_URL}?sheet=${encodeURIComponent(nomeAba)}`;
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.error) {
      registrarLog(`Aba ${nomeAba}: ${data.error}`, 'warn');
      return [];
    }
    return data;
  } catch (e) {
    registrarLog(`Falha ao acessar ${nomeAba}: ${e.message}`, 'err');
    return [];
  }
}'''

PADRAO_FETCH = re.compile(
    r"async function fetchAba\(nomeAba\) \{\n"
    r"  try \{\n"
    r"    const url = `\$\{APPS_SCRIPT_URL\}\?sheet=\$\{encodeURIComponent\(nomeAba\)\}`;\n"
    r"    const resp = await fetch\(url\);\n"
    r"    if \(!resp\.ok\) throw new Error\(`HTTP \$\{resp\.status\}`\);\n"
    r"    const data = await resp\.json\(\);\n"
    r"    if \(data\.error\) \{\n"
    r"      registrarLog\(`Aba \$\{nomeAba\}: \$\{data\.error\}`, 'warn'\);\n"
    r"      return \[\];\n"
    r"    \}\n"
    r"    return data;\n"
    r"  \} catch \(e\) \{\n"
    r"    registrarLog\(`Falha ao acessar \$\{nomeAba\}: \$\{e\.message\}`, 'err'\);\n"
    r"    return \[\];\n"
    r"  \}\n"
    r"\}",
    flags=re.M,
)


def main() -> int:
    raw = ARQUIVO.read_text(encoding="utf-8")
    usa_crlf = "\r\n" in raw
    texto = raw.replace("\r\n", "\n")

    if "function slugArquivoDados(nomeAba)" in texto:
        print("Dashboard ja possui leitura por JSON estatico.")
        return 0

    texto, n = PADRAO_FETCH.subn(NOVO_BLOCO, texto, count=1)
    if n != 1:
        raise SystemExit("ERRO: funcao fetchAba original nao encontrada para substituicao.")

    validacoes = [
        "const DADOS_JSON_BASE = \"dados\";",
        "const USAR_JSON_ESTATICO = true;",
        "function slugArquivoDados(nomeAba)",
        "DADOS_JSON_CACHE_BUSTER",
        "using Apps Script",
    ]
    ausentes = [v for v in validacoes if v not in texto]
    if ausentes:
        raise SystemExit(f"ERRO: validacoes ausentes: {ausentes}")

    saida = texto.replace("\n", "\r\n") if usa_crlf else texto
    ARQUIVO.write_text(saida, encoding="utf-8", newline="")
    print("dashboard_malha_ia_v36.html atualizado para priorizar JSON estatico.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
