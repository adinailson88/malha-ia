# Publicacao e organizacao do repositorio no GitHub

Este documento registra o fluxo recomendado para organizar o repositorio `adinailson88-jpg/malha-ia` no GitHub sem alterar a arquitetura funcional do projeto.

## 1. Perfil do autor

Dados informados e usados na documentacao:

1. Nome: Adinailson Guimaraes de Oliveira.
2. ORCID: https://orcid.org/0009-0004-3941-1648.
3. GitHub: https://github.com/adinailson88-jpg.

O ORCID pode ser vinculado manualmente no GitHub em:

```text
GitHub > Settings > Public profile > Social accounts
```

Adicionar:

```text
https://orcid.org/0009-0004-3941-1648
```

## 2. Dados publicos recomendados para o repositorio

Descricao curta:

```text
Dashboard e motores de governanca preditiva para manutencao predial publica, com IA, series temporais, ODS e GitHub Pages.
```

Website:

```text
https://adinailson88-jpg.github.io/malha-ia/
```

Topicos sugeridos:

```text
governanca-preditiva
manutencao-predial
gestao-publica
inteligencia-artificial
series-temporais
ods
github-pages
python
dashboard
biossistemas-construidos
```

## 3. README

O arquivo `README.md` deve ser mantido como porta de entrada do repositorio, contendo:

1. Objetivo do projeto.
2. Autor e ORCID.
3. Link do dashboard publicado.
4. Estrutura de pastas.
5. Dados consumidos.
6. Workflows.
7. Como executar localmente.
8. Como publicar releases.
9. Estado dos packages.
10. Informacao de citacao.

## 4. Packages

O projeto atual nao esta estruturado como pacote Python instalavel. A presenca de `execucao_offline/requirements.txt` indica dependencias de execucao, nao pacote distribuivel.

Fluxo recomendado:

1. Manter o projeto como aplicacao operacional enquanto os motores forem scripts independentes.
2. Usar GitHub Releases para distribuir snapshots versionados.
3. Criar pacote Python apenas se houver necessidade real de instalacao via `pip`.

Se futuramente houver empacotamento, criar:

```text
pyproject.toml
src/malha_ia/
tests/
```

Essa mudanca deve ser tratada como refatoracao, porque altera a forma de importar e executar os motores.

## 5. Releases

Fluxo manual recomendado:

1. Atualizar `CHANGELOG.md`.
2. Validar os scripts principais com `python -m py_compile`.
3. Validar JSONs em `dados/`.
4. Criar tag anotada.
5. Publicar release no GitHub.

Comandos:

```bash
git status --short
python -m py_compile motor_classificacao_v1.py
python -m py_compile motor_previsao_chamados.py
python -m py_compile motor_previsao_custos.py
python -m py_compile motor_previsao_filtros.py
python -m py_compile motor_ods.py
python -m py_compile scripts/exportar_dados_json.py
python -m py_compile scripts/aplicar_json_dashboard.py
git tag -a v4.0.8 -m "Malha IA v4.0.8"
git push origin v4.0.8
```

## 6. Release notes sugeridas

```text
Malha IA v4.0.8

Esta versao consolida o dashboard de governanca preditiva, dados JSON estaticos, motores Python separados e publicacao via GitHub Pages.

Inclui:
- Dashboard principal.
- Exportacao de dados para JSON.
- Classificacao e reclassificacao de chamados.
- Previsao de chamados.
- Previsao de custos.
- Previsoes por filtros.
- Indicadores ODS.
- Fallback para Apps Script / Google Sheets.
```

## 7. Licenca

Informação insuficiente para verificar.

Antes de adicionar `LICENSE`, definir explicitamente a licenca desejada. Exemplos comuns:

1. MIT: permissiva, adequada para software aberto com baixa restricao.
2. Apache-2.0: permissiva, inclui concessao explicita de patente.
3. GPL-3.0: exige que derivados distribuido mantenham codigo aberto sob a mesma licenca.
4. Proprietaria/sem licenca aberta: manter sem `LICENSE`, com uso reservado.
