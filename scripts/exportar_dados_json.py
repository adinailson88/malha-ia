#!/usr/bin/env python3
"""Exporta abas do Malha IA para arquivos JSON estaticos.

O dashboard HTML pode consumir estes arquivos diretamente pelo GitHub Pages,
reduzindo a dependencia de leituras em tempo real via Apps Script.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

APPS_SCRIPT_URL_PADRAO = (
    "https://script.google.com/macros/s/"
    "AKfycbyLQMA7D9sohZ-nqo-Z2ydVuBi-7igmEFPmhYy3gbOLMsawx78E-DyfnvecMSb-00om/exec"
)

# Todas as abas sao exportadas em modo tolerante. Se uma aba nao for gerada,
# o dashboard mantem fallback automatico para o Apps Script apenas naquela aba.
ABAS_CRITICAS: set[str] = set()

LIMITE_LINHAS_JSON = {
    "LOG_CLASSIFICACAO": 1000,
}

ABAS_BASE = [
    "CHAMADOS",
    "PREVISAO_TEMPORAL",
    "PREVISAO_DETALHES",
    "PREVISAO_INCERTEZAS",
    "PREVISAO_DIAGNOSTICO",
    "PREVISAO_RESIDUOS",
    "PREVISAO_QQPLOT",
    "CONTEXTO_SAZONAL",
    "METRICAS_TREINO",
    "LOG_CLASSIFICACAO",
    "PREVISAO_VALIDACAO",
    "PREVISAO_PRESSUPOSTOS",
    "FILTROS_DISPONIVEIS",
    "Área Manutenção",
    "PREVISAO_POR_CATEGORIA",
    "PREVISAO_CUSTO_TEMPORAL",
    "PREVISAO_CUSTO_DETALHES",
    "PREVISAO_CUSTO_INCERTEZAS",
    "PREVISAO_CUSTO_VALIDACAO",
    "PREVISAO_DIEBOLD_MARIANO",
    "PREVISAO_CRPS_MULTICRITERIO",
    "PREVISAO_GRANGER",
    "INDICADORES_ODS",
    "PESOS_ODS",
]

PREFIXOS_FILTRAVEIS = [
    "PREVISAO_TEMPORAL",
    "PREVISAO_DETALHES",
    "PREVISAO_INCERTEZAS",
    "PREVISAO_DIAGNOSTICO",
    "PREVISAO_RESIDUOS",
    "PREVISAO_QQPLOT",
    "PREVISAO_VALIDACAO",
    "PREVISAO_PRESSUPOSTOS",
    "PREVISAO_CUSTO_TEMPORAL",
    "PREVISAO_CUSTO_DETALHES",
    "PREVISAO_CUSTO_INCERTEZAS",
    "PREVISAO_CUSTO_VALIDACAO",
]


def slug_aba(nome: str) -> str:
    """Gera nome de arquivo estavel para uma aba."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", sem_acento).strip("_").lower()
    return slug or "aba"


def url_aba(base_url: str, nome_aba: str) -> str:
    return f"{base_url}?{urlencode({'sheet': nome_aba})}"


def buscar_aba(base_url: str, nome_aba: str, timeout: int = 75, tentativas: int = 2) -> list[list[Any]]:
    """Busca uma aba no Apps Script com tentativas simples."""
    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            req = Request(
                url_aba(base_url, nome_aba),
                headers={"User-Agent": "MalhaIA-JSON-Exporter/1.0"},
            )
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            dados = json.loads(raw)
            if isinstance(dados, dict) and dados.get("error"):
                raise RuntimeError(str(dados.get("error")))
            if not isinstance(dados, list):
                raise RuntimeError(f"Retorno inesperado para {nome_aba}: {type(dados).__name__}")
            return dados
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            ultimo_erro = exc
            if tentativa < tentativas:
                time.sleep(2 * tentativa)
    raise RuntimeError(f"Falha ao buscar aba {nome_aba}: {ultimo_erro}")


def salvar_json(caminho: Path, dados: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":")) + "\n"
    caminho.write_text(texto, encoding="utf-8", newline="\n")


def limitar_linhas_json(nome_aba: str, dados: list[list[Any]]) -> list[list[Any]]:
    """
    Limita linhas exportadas para JSON em abas muito grandes.

    Mantém:
    - cabeçalho;
    - últimas N linhas definidas em LIMITE_LINHAS_JSON.

    A planilha continua com política própria de retenção.
    Este limite afeta apenas o JSON usado pelo dashboard.
    """
    limite = LIMITE_LINHAS_JSON.get(nome_aba)

    if not limite:
        return dados

    if not isinstance(dados, list) or len(dados) <= limite + 1:
        return dados

    cabecalho = dados[:1]
    linhas = dados[1:]

    return cabecalho + linhas[-limite:]


def extrair_sufixos_filtros(filtros: list[list[Any]]) -> list[str]:
    """Extrai sufixos da aba FILTROS_DISPONIVEIS.

    A coluna C, indice 2, e usada pelo dashboard como valor de filtro/sufixo.
    """
    sufixos: set[str] = set()
    for linha in filtros[1:]:
        if len(linha) < 3:
            continue
        valor = str(linha[2] or "").strip()
        if valor:
            sufixos.add(valor)
    return sorted(sufixos)


def montar_lista_abas(base_url: str, incluir_filtradas: bool) -> list[str]:
    abas = list(dict.fromkeys(ABAS_BASE))
    if not incluir_filtradas:
        return abas

    try:
        filtros = buscar_aba(base_url, "FILTROS_DISPONIVEIS")
        sufixos = extrair_sufixos_filtros(filtros)
    except RuntimeError as exc:
        print(f"Aviso: nao foi possivel ler FILTROS_DISPONIVEIS para sufixos: {exc}", file=sys.stderr)
        return abas

    for sufixo in sufixos:
        for prefixo in PREFIXOS_FILTRAVEIS:
            abas.append(f"{prefixo}{sufixo}")
    return list(dict.fromkeys(abas))


def exportar(base_url: str, saida: Path, incluir_filtradas: bool, workers: int) -> dict[str, Any]:
    abas = montar_lista_abas(base_url, incluir_filtradas)
    manifesto: dict[str, Any] = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "fonte": "Apps Script / Google Sheets",
        "total_abas_planejadas": len(abas),
        "abas_criticas": sorted(ABAS_CRITICAS),
        "observacao": "Abas ausentes usam fallback automatico via Apps Script no dashboard.",
        "abas": {},
        "falhas": {},
        "falhas_criticas": {},
        "falhas_opcionais": {},
    }

    def tarefa(nome: str) -> tuple[str, list[list[Any]] | None, str | None]:
        try:
            return nome, buscar_aba(base_url, nome), None
        except RuntimeError as exc:
            return nome, None, str(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futuros = {executor.submit(tarefa, aba): aba for aba in abas}
        for futuro in concurrent.futures.as_completed(futuros):
            nome, dados, erro = futuro.result()
            slug = slug_aba(nome)
            arquivo = f"{slug}.json"
            if erro:
                manifesto["falhas"][nome] = erro
                if nome in ABAS_CRITICAS:
                    manifesto["falhas_criticas"][nome] = erro
                    print(f"ERRO CRITICO {nome}: {erro}", file=sys.stderr)
                else:
                    manifesto["falhas_opcionais"][nome] = erro
                    print(f"AVISO {nome}: {erro}", file=sys.stderr)
                continue
            dados_json = limitar_linhas_json(nome, dados)

            salvar_json(saida / arquivo, dados_json)

            manifesto["abas"][nome] = {
                "arquivo": arquivo,
                "linhas": max(0, len(dados_json) - 1),
                "linhas_origem": max(0, len(dados) - 1),
                "colunas": len(dados_json[0]) if dados_json else 0,
                "limitado_json": len(dados_json) != len(dados),
            }

            print(
                f"OK {nome}: {manifesto['abas'][nome]['linhas']} linhas exportadas "
                f"de {manifesto['abas'][nome]['linhas_origem']} origem -> dados/{arquivo}"
            )

    manifesto["total_abas_exportadas"] = len(manifesto["abas"])
    manifesto["total_falhas"] = len(manifesto["falhas"])
    manifesto["total_falhas_criticas"] = len(manifesto["falhas_criticas"])
    manifesto["total_falhas_opcionais"] = len(manifesto["falhas_opcionais"])
    salvar_json(saida / "manifest.json", manifesto)
    return manifesto


def main() -> int:
    parser = argparse.ArgumentParser(description="Exporta abas do Malha IA para JSON estatico.")
    parser.add_argument("--apps-script-url", default=os.getenv("MALHA_APPS_SCRIPT_URL", APPS_SCRIPT_URL_PADRAO))
    parser.add_argument("--saida", default="dados", help="Diretorio de saida dos arquivos JSON.")
    parser.add_argument("--incluir-filtradas", action="store_true", help="Exporta tambem abas com sufixos de filtros.")
    parser.add_argument("--workers", type=int, default=4, help="Numero de requisicoes paralelas.")
    args = parser.parse_args()

    manifesto = exportar(
        base_url=args.apps_script_url,
        saida=Path(args.saida),
        incluir_filtradas=args.incluir_filtradas,
        workers=max(1, args.workers),
    )

    if manifesto["total_falhas_criticas"]:
        print(f"Concluido com {manifesto['total_falhas_criticas']} falha(s) critica(s).", file=sys.stderr)
        return 1
    print(
        "Exportacao concluida. "
        f"Abas exportadas: {manifesto['total_abas_exportadas']}; "
        f"falhas opcionais: {manifesto['total_falhas_opcionais']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
