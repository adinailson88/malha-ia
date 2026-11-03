"""Teste de regressao do parse de datas dos motores (inversao de dia e mes).

Nao importa os motores (que conectam ao Google ao carregar): extrai por AST as funcoes
parse_data_abertura, _verificar_datas_invalidas e as extratoras de serie e as executa em um
espaco de nomes controlado.

Uso (na raiz do repositorio):  python -m unittest tests.test_parse_datas -v
Requer pandas e numpy.
"""

import ast
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import pytz
    FUSO = pytz.timezone("America/Bahia")
except ImportError:  # pytz nao instalado: usa a biblioteca padrao
    pytz = None
    from zoneinfo import ZoneInfo
    FUSO = ZoneInfo("America/Bahia")

RAIZ = Path(__file__).resolve().parents[1]
MOTORES = ["motor_previsao_chamados.py", "motor_previsao_custos.py", "motor_previsao_filtros.py", "motor_ods.py"]


def carregar(arquivo, nomes):
    fonte = (RAIZ / arquivo).read_text(encoding="utf-8-sig")
    arvore = ast.parse(fonte)
    ns = {"pd": pd, "np": np, "datetime": datetime, "pytz": pytz,
          "FUSO_BAHIA": FUSO, "COL_DATA_ABERTURA": 2, "COL_VALOR": 16,
          "MIN_PONTOS_SERIE_CUSTO": 1}
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name in nomes:
            exec(compile(ast.Module([no], []), arquivo, "exec"), ns)
    faltam = [n for n in nomes if n not in ns]
    assert not faltam, f"{arquivo}: funcoes ausentes {faltam}"
    return ns


class ParseDataAbertura(unittest.TestCase):
    def test_todos_os_motores_usam_o_mesmo_parse(self):
        for arq in MOTORES:
            ns = carregar(arq, ["parse_data_abertura"])
            p = ns["parse_data_abertura"]
            self.assertEqual(p("2026-05-06 10:51"), pd.Timestamp("2026-05-06 10:51"), arq)
            self.assertEqual(p("2026-05-29 10:51"), pd.Timestamp("2026-05-29 10:51"), arq)
            self.assertEqual(p("2026-05-06T10:51:00"), pd.Timestamp("2026-05-06 10:51"), arq)
            self.assertEqual(p("06/05/2026 10:51:00"), pd.Timestamp("2026-05-06 10:51"), arq)  # dia primeiro
            self.assertEqual(p("06/05/2026"), pd.Timestamp("2026-05-06"), arq)
            self.assertEqual(p("2018-03-01T03:00:00.000Z"), pd.Timestamp("2018-03-01 00:00"), arq)
            for ruim in ("", "   ", "abc", "2026/05/06", "05-06-2026"):
                self.assertTrue(pd.isna(p(ruim)), f"{arq}: {ruim!r}")

    def test_serie_de_chamados_nao_inverte_dia_e_mes(self):
        ns = carregar("motor_previsao_chamados.py",
                      ["parse_data_abertura", "_verificar_datas_invalidas", "extrair_serie_temporal"])
        linhas = [["1", "t", d] for d in (
            "2020-05-06 10:00", "2020-05-29 10:00", "2020-05-12 08:00",   # tres chamados de maio
            "2020-06-03 09:00", "2020-06-20 09:00")]                      # dois de junho
        df = ns["extrair_serie_temporal"](linhas)
        qtd = dict(zip(df["Mes_Ano_Str"], df["Quantidade"]))
        self.assertEqual(qtd, {"05/2020": 3, "06/2020": 2})

    def test_serie_de_custo_nao_inverte_dia_e_mes(self):
        ns = carregar("motor_previsao_custos.py",
                      ["parse_data_abertura", "_verificar_datas_invalidas", "parse_valor_chamado",
                       "construir_serie_custo"])
        linhas = [["1", "t", "2020-05-06 10:00"] + [""] * 13 + ["100"],
                  ["2", "t", "2020-05-29 10:00"] + [""] * 13 + ["200"],
                  ["3", "t", "2020-06-03 10:00"] + [""] * 13 + ["50"]]
        serie = ns["construir_serie_custo"](linhas)
        self.assertEqual({k.strftime("%Y-%m"): v for k, v in serie.items()}, {"2020-05": 300.0, "2020-06": 50.0})

    def test_datas_invalidas_acima_do_limite_interrompem(self):
        ns = carregar("motor_previsao_chamados.py", ["_verificar_datas_invalidas"])
        v = ns["_verificar_datas_invalidas"]
        v(0, 100)
        v(5, 100)  # 5% = limite, apenas avisa
        with self.assertRaises(ValueError):
            v(6, 100)


if __name__ == "__main__":
    unittest.main()
