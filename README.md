# Malha IA

Dashboard e motores de governanca preditiva aplicados a manutencao predial publica, com classificacao, previsao de chamados, previsao de custos, filtros, indicadores ODS e publicacao via GitHub Pages.

Autor: Adinailson Guimaraes de Oliveira
ORCID: [0009-0004-3941-1648](https://orcid.org/0009-0004-3941-1648)
Repositorio: [adinailson88-jpg/malha-ia](https://github.com/adinailson88-jpg/malha-ia)
Dashboard publicado: [adinailson88-jpg.github.io/malha-ia](https://adinailson88-jpg.github.io/malha-ia/)

## Visao geral

O projeto consolida dados de chamados de manutencao, resultados de classificacao automatizada e previsoes temporais em um dashboard HTML estatico. A arquitetura atual usa arquivos JSON em `dados/` como fonte preferencial para o dashboard e mantem fallback para Apps Script / Google Sheets quando necessario.

Principais componentes:

1. `dashboard_malha_ia_v36.html`: dashboard principal.
2. `index.html`: pagina de entrada publicada no GitHub Pages.
3. `dados/*.json`: dados estaticos exportados para consumo do dashboard.
4. `scripts/exportar_dados_json.py`: exportacao de abas do Apps Script / Google Sheets para JSON.
5. `scripts/aplicar_json_dashboard.py`: aplicacao do consumo de JSON estatico no dashboard.
6. `motor_classificacao_v1.py`: classificacao e reclassificacao de chamados.
7. `motor_previsao_chamados.py`: previsao temporal de chamados.
8. `motor_previsao_custos.py`: previsao temporal de custos.
9. `motor_previsao_filtros.py`: previsoes segmentadas por filtros.
10. `motor_ods.py`: indicadores ODS.

## Escopo tecnico

O Malha IA combina automacao, manutencao predial publica, gestao publica, engenharia eletrica, biossistemas construidos, IA/PLN, series temporais, ODS e governanca preditiva.

O fluxo operacional atual e dividido em:

1. Coleta/exportacao de dados para JSON.
2. Classificacao automatizada dos chamados.
3. Previsao de volume de chamados.
4. Previsao de custos.
5. Previsoes filtradas.
6. Calculo de indicadores ODS.
7. Publicacao do dashboard no GitHub Pages.

## Estrutura do repositorio

```text
.
|-- .github/workflows/           # Automacoes GitHub Actions
|-- dados/                       # JSONs consumidos pelo dashboard
|-- docs/                        # Documentacao auxiliar e instrucoes de IA
|-- execucao_offline/            # Dependencias para execucao local
|-- legado/                      # Arquivos historicos preservados
|-- scripts/                     # Scripts auxiliares
|-- dashboard_malha_ia_v36.html  # Dashboard principal
|-- index.html                   # Entrada do GitHub Pages
|-- motor_*.py                   # Motores Python do projeto
```

## Dados

Os dados preferenciais do dashboard ficam em `dados/*.json`. O arquivo `dados/manifest.json` registra a exportacao, incluindo origem, quantidade de abas planejadas, abas exportadas, falhas e limites aplicados.

Na versao local analisada, o manifest registra:

1. Fonte: Apps Script / Google Sheets.
2. Total de abas planejadas: 24.
3. Total de abas exportadas: 24.
4. Total de falhas: 0.
5. Fallback automatico para Apps Script quando uma aba estiver ausente.

## Workflows

Os workflows em `.github/workflows/` automatizam rotinas do projeto:

1. `atualizar-dados-json.yml`: exporta abas para JSON, valida os arquivos e commita atualizacoes.
2. `classificacao.yml`: executa classificacao periodica.
3. `reclassificacao.yml`: executa reclassificacao.
4. `previsao_chamados_global.yml`: executa previsao de chamados.
5. `previsao_custo_global.yml`: executa previsao de custos.
6. `previsao_filtros.yml`: executa previsoes filtradas.
7. `previsao_global.yml`: workflow manual combinado para chamados e custos.
8. `ods_indicadores.yml`: executa indicadores ODS.
9. `pages.yml`: publica o dashboard no GitHub Pages.

## Execucao local

Requisitos principais:

1. Python 3.11 ou 3.12.
2. Dependencias listadas em `execucao_offline/requirements.txt`.
3. Credenciais Google quando a rotina acessar Google Sheets.

Instalacao:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r execucao_offline/requirements.txt
```

Validacao sintatica dos scripts principais:

```bash
python -m py_compile motor_classificacao_v1.py
python -m py_compile motor_previsao_chamados.py
python -m py_compile motor_previsao_custos.py
python -m py_compile motor_previsao_filtros.py
python -m py_compile motor_ods.py
python -m py_compile scripts/exportar_dados_json.py
python -m py_compile scripts/aplicar_json_dashboard.py
```

Execucoes operacionais:

```bash
python scripts/exportar_dados_json.py --saida dados --workers 6
python scripts/aplicar_json_dashboard.py
python motor_classificacao_v1.py --apenas-classificacao
python motor_previsao_chamados.py --apenas-previsao-chamados
python motor_previsao_custos.py --apenas-previsao-custos
```

## Publicacao

O dashboard e publicado pelo workflow `Deploy GitHub Pages`. A URL base declarada no proprio workflow e:

```text
https://adinailson88-jpg.github.io/malha-ia/
```

## Packages

Este repositorio esta organizado como aplicacao operacional e dashboard estatico, nao como pacote Python instalavel. Portanto, nao ha `pyproject.toml`, `setup.py` ou pacote publicado em GitHub Packages na estrutura atual.

Para publicar artefatos sem alterar a arquitetura, use GitHub Releases anexando:

1. Snapshot do dashboard HTML.
2. Snapshot dos JSONs em `dados/`.
3. Relatorio ou changelog da versao.
4. Tag semantica, por exemplo `v4.0.8`.

## Releases

As mudancas relevantes devem ser registradas em `CHANGELOG.md`. Para criar uma release no GitHub:

```bash
git tag -a v4.0.8 -m "Malha IA v4.0.8"
git push origin v4.0.8
```

Depois, publicar a release pela interface do GitHub usando o formulario configurado em `.github/release.yml`.

## Citacao

Para citacao academica e identificacao autoral, use o arquivo `CITATION.cff` deste repositorio.

## Licenca

Informação insuficiente para verificar.
