---
name: codigo-automacao-malha-ia
description: Use para Python, HTML, JavaScript, Apps Script, GitHub Actions, JSON, Google Sheets e automacoes do projeto Malha IA, preservando arquitetura, aplicando a menor alteracao necessaria, mantendo fallback, validando sintaxe e explicando causa, correcao e validacao.
---

# Codigo Automacao Malha IA

## Finalidade

Usar para Python, HTML, JavaScript, Apps Script, GitHub Actions, JSON, Google Sheets e automacoes do projeto Malha IA.

## Regras de alteracao

Preservar a arquitetura existente, aplicar a menor alteracao necessaria e nao remover fallback, especialmente fallback para Apps Script/Google Sheets.

Antes de editar, ler `AGENTS.md`, identificar o arquivo afetado, verificar funcoes chamadas, dados consumidos, seletores DOM, endpoints, arquivos JSON, workflows relacionados e scripts auxiliares.

Nao refatorar sem necessidade. Nao alterar nomes de arquivos, funcoes, jobs, chaves JSON, ids DOM ou contratos de dados sem informar impacto.

Quando for solicitada versao completa, entregar o codigo completo, sem omissoes, reticencias ou blocos resumidos.

## Validacao

Validar sintaxe sempre que possivel:

```bash
python -m py_compile caminho/do/arquivo.py
```

Quando necessario, usar `ast.parse` para validacao sintatica Python.

Para HTML/JavaScript, verificar tags, scripts, funcoes, referencias DOM, chamadas assincronas, tratamento de erro e fallback.

Para YAML/GitHub Actions, verificar indentacao, permissoes, gatilhos, agendamento, comandos e paths.

Para JSON, verificar sintaxe, chaves esperadas e compatibilidade com o dashboard.

## Padrao de resposta

Ao explicar erro ou correcao, usar:

```text
Arquivo afetado:
Causa provavel:
Correcao aplicada/proposta:
Validacao realizada:
Proximo passo:
```
