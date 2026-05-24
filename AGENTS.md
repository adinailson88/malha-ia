# AGENTS.md — Malha IA

## Regime de trabalho

Operar de forma técnica, objetiva e verificável. Antes de alterar código, ler este arquivo, verificar se existe `contexto_projeto.txt` e analisar o arquivo diretamente afetado.

Preservar a arquitetura existente. Não refatorar sem necessidade. Não remover funcionalidades existentes sem informar impacto. Não resumir código quando for solicitada versão completa.

Quando não houver dados suficientes para confirmar algo, responder: `Informação insuficiente para verificar.` Não inventar arquivos, funções, branches, workflows, resultados de teste, normas, referências, valores ou links.

## Contexto do projeto

Projeto relacionado a dashboard, automações, manutenção predial pública, IA/PLN, séries temporais e governança preditiva.

Referências:

- dashboard principal: `dashboard_malha_ia_v36.html`;
- dados preferenciais: `dados/*.json`;
- fallback obrigatório: Apps Script/Google Sheets;
- scripts auxiliares: diretório `scripts/`;
- workflows: diretório `.github/workflows/`.

## Regras de alteração

Ao modificar o projeto:

1. identificar o arquivo afetado;
2. explicar a causa técnica;
3. aplicar a menor correção funcional necessária;
4. manter fallback existente;
5. evitar dependências desnecessárias;
6. validar sintaxe quando possível;
7. indicar comandos de teste.

## Validação

Python:

```bash
python -m py_compile caminho/do/arquivo.py
```

HTML/JS: verificar fechamento de tags, scripts, funções, referências DOM, chamadas assíncronas e fallback de carregamento.

YAML/GitHub Actions: evitar Python extenso embutido; preferir scripts em `scripts/`; validar indentação, gatilhos, permissões e agendamento.

## Padrão de resposta

Para erro, correção ou commit, usar:

```text
Arquivo afetado:
Causa provável:
Correção aplicada/proposta:
Validação realizada:
Próximo passo:
```

## Estilo

Para código, instalação, planilhas, automação e operação: passo a passo numerado com comandos e validações.

Para textos, e-mails, relatos, pareceres, artigos e projetos: parágrafos contínuos, linguagem natural, técnica e sem aparência de texto gerado por IA.