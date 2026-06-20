#!/usr/bin/env python3
"""Importa para o malha-ia o MELHOR modelo de classificacao VALIDADA do repo
classificacao-chamados (bancada de pesquisa do doutorado).

A classificacao deixou de rodar AO VIVO no malha-ia (workflows */15 e de 3h em 3h
foram pausados): a bancada classificacao-chamados ja faz isso, com validacao humana.
Este script so COPIA o melhor resultado para ca, como dado estatico.

Le docs/dados/avaliacao_final.json da bancada e escolhe o modelo de maior
acerto_validado (acerto contra a verdade conferida por humano, M/N/P). E ADAPTATIVO:
se depois da reclassificacao outro modelo passar a liderar, este script passa
automaticamente a copiar o novo melhor — sem alteracao de codigo.

Grava em dados/:
  classificacao_validada.json        -> registros (por linha) do melhor modelo
  classificacao_validada_resumo.json -> metadados (modelo, acerto, IC95, ranking, fonte)

Observacao: a bancada NAO exporta texto de chamado (privacidade), entao o artefato
importado nao tem o texto — apenas categoria original (o), predita (p), confianca (c)
e acerto (v) por id de linha (l). Por isso e um arquivo NOVO, e nao um substituto do
log_classificacao.json (que segue sendo o snapshot da aba do Sheets com texto).

100% dados publicos via raw GitHub; nao usa credenciais.
"""
from __future__ import annotations

import datetime
import json
import sys
import urllib.request
from pathlib import Path

BASE = ("https://raw.githubusercontent.com/adinailson88/"
        "classificacao-chamados/main/docs/dados")
DEST = Path(__file__).resolve().parents[1] / "dados"


def baixar(nome: str):
    url = f"{BASE}/{nome}"
    with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310 (URL fixa/publica)
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    aval = baixar("avaliacao_final.json")
    modelos = aval.get("por_modelo", [])
    if not modelos:
        print(f"avaliacao_final.json sem modelos (status={aval.get('status')}); "
              "nada a importar.")
        return 0

    ordenado = sorted(modelos, key=lambda m: m.get("acerto_validado", -1), reverse=True)
    melhor = ordenado[0]
    nome = melhor["modelo"]
    registros = baixar(f"registros_{nome}.json")

    resumo = {
        "gerado_em_utc": datetime.datetime.utcnow().isoformat() + "Z",
        "fonte": f"{BASE}/registros_{nome}.json",
        "criterio": ("maior acerto_validado em avaliacao_final.json "
                     "(verdade humana M/N/P) — seletor adaptativo"),
        "melhor_modelo": nome,
        "acerto_validado": melhor.get("acerto_validado"),
        "ic95": melhor.get("ic95"),
        "n": melhor.get("n"),
        "validados_na_bancada": aval.get("validados"),
        "ranking": [{"modelo": m["modelo"],
                     "acerto_validado": m.get("acerto_validado"),
                     "ic95": m.get("ic95")} for m in ordenado],
        "n_registros": len(registros),
        "observacao": ("Classificacao validada importada do repo classificacao-chamados; "
                       "sem texto do chamado. NAO substitui log_classificacao.json."),
    }

    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "classificacao_validada.json").write_text(
        json.dumps(registros, ensure_ascii=False), encoding="utf-8")
    (DEST / "classificacao_validada_resumo.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OK: melhor_modelo={nome} | acerto_validado={melhor.get('acerto_validado')} "
          f"| n_registros={len(registros)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
