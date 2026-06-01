#!/usr/bin/env python3
"""Gera CSVs fixos e enxutos a partir dos JSONs canonicos do Malha IA."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


ARQUIVOS_CANONICOS = [
    "chamados.json",
    "metricas_treino.json",
    "log_classificacao.json",
    "previsao_temporal.json",
    "previsao_validacao.json",
    "previsao_custo_temporal.json",
    "previsao_custo_validacao.json",
    "previsao_por_categoria.json",
    "indicadores_ods.json",
    "filtros_disponiveis.json",
]


def carregar_tabela(caminho: Path) -> tuple[list[str], list[list[object]]]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, list) or not dados:
        raise SystemExit(f"{caminho} nao contem tabela JSON no formato lista de linhas.")
    headers = dados[0]
    rows = dados[1:]
    if not isinstance(headers, list):
        raise SystemExit(f"Cabecalho invalido em {caminho}.")
    return [str(h) for h in headers], rows


def escrever_csv(headers: list[str], rows: list[list[object]], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8-sig", newline="") as arquivo:
        writer = csv.writer(arquivo)
        writer.writerow(headers)
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera CSVs canonicos para analise tabular e auditoria.")
    parser.add_argument("--entrada", default="dados")
    parser.add_argument("--saida", default="dados_csv")
    args = parser.parse_args()

    entrada = Path(args.entrada)
    saida = Path(args.saida)
    gerados = 0

    for nome in ARQUIVOS_CANONICOS:
        origem = entrada / nome
        if not origem.exists():
            print(f"AVISO: {origem} ausente; ignorado.")
            continue
        headers, rows = carregar_tabela(origem)
        destino = saida / (origem.stem + ".csv")
        escrever_csv(headers, rows, destino)
        gerados += 1
        print(f"CSV gerado: {destino} ({len(rows)} linhas, {len(headers)} colunas)")

    if gerados == 0:
        raise SystemExit("Nenhum CSV foi gerado.")
    print(f"Total de CSVs gerados: {gerados}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
