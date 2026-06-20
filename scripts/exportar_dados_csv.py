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

# CSV enxuto consumido por CHAMADOS_ESQUELETO_REDUZIDO via IMPORTDATA.
# O chamados.csv completo (30 colunas / ~48 mil linhas) estoura o limite de
# tamanho do IMPORTDATA, que baixa o arquivo inteiro antes de qualquer QUERY.
# Aqui exportamos apenas as colunas e linhas necessarias, ja na ordem da planilha
# de destino (A=ID, B=TITULO, C=CATEGORIA, D=DESCRICAO GLPI, E=TITULO O.S.M.,
# F=DESCRICAO O.S.M.), e descartamos as linhas sem ID.
ESQUELETO_ORIGEM = "chamados.json"
ESQUELETO_DESTINO = "chamados_esqueleto.csv"
# Indices 0-based na aba CHAMADOS: A=0, B=1, M=12, W=22, X=23, Y=24.
ESQUELETO_COLUNAS = [0, 1, 12, 22, 23, 24]
ESQUELETO_COL_ID = 0


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


def gerar_esqueleto(entrada: Path, saida: Path) -> bool:
    """Gera o CSV enxuto (6 colunas, linhas com ID) para CHAMADOS_ESQUELETO_REDUZIDO."""
    origem = entrada / ESQUELETO_ORIGEM
    if not origem.exists():
        print(f"AVISO: {origem} ausente; esqueleto nao gerado.")
        return False

    headers, rows = carregar_tabela(origem)
    max_idx = max(ESQUELETO_COLUNAS)

    def projetar(linha: list[object]) -> list[object]:
        return [linha[i] if i < len(linha) else "" for i in ESQUELETO_COLUNAS]

    novo_header = projetar(headers + [""] * (max_idx + 1 - len(headers)))
    novas_linhas = [
        projetar(linha)
        for linha in rows
        if ESQUELETO_COL_ID < len(linha) and str(linha[ESQUELETO_COL_ID]).strip()
    ]

    destino = saida / ESQUELETO_DESTINO
    escrever_csv([str(h) for h in novo_header], novas_linhas, destino)
    print(f"CSV esqueleto gerado: {destino} ({len(novas_linhas)} linhas, {len(novo_header)} colunas)")
    return True


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

    if gerar_esqueleto(entrada, saida):
        gerados += 1

    if gerados == 0:
        raise SystemExit("Nenhum CSV foi gerado.")
    print(f"Total de CSVs gerados: {gerados}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
