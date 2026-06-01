# AGENTS.md - Malha IA

## Regime de trabalho

Atuar no projeto em modo tecnico, objetivo e verificavel. Iniciar diretamente com o conteudo solicitado, sem saudacao, preambulo, conclusao artificial ou comentario sobre o proprio processamento.

Priorizar precisao factual. Quando houver insuficiencia de dados, declarar exatamente: `Informação insuficiente para verificar.`

Nao presumir, estimar ou preencher lacunas. Nao inventar referencias, normas, jurisprudencia, valores, links, autores, arquivos, funcoes, branches, workflows ou resultados de teste.

## Contexto obrigatorio antes de alterar codigo

Antes de alterar qualquer arquivo funcional, ler este arquivo, verificar se existem arquivos de contexto do projeto e inspecionar diretamente os arquivos afetados. Identificar dependencias, fallback, dados consumidos, funcoes chamadas e workflows relacionados.

Preservar a arquitetura existente. Aplicar a menor alteracao necessaria. Nao refatorar sem necessidade. Nao alterar comportamento do dashboard, scripts, dados ou workflows sem informar impacto. Nao remover fallback existente.

Quando for solicitada versao completa de codigo, nao resumir, omitir trechos, substituir blocos por reticencias ou entregar apenas diffs.

## Contexto do Malha IA

Repositorio: `adinailson88/malha-ia`.

Dashboard principal: `dashboard.html`.

Redirecionador historico: `dashboard_malha_ia_v36.html`.

Dados preferenciais: `dados/*.json`.

Fallback obrigatorio: Apps Script/Google Sheets.

Scripts auxiliares: `scripts/`.

Workflows: `.github/workflows/`.

Temas do projeto: manutencao predial publica, gestao publica, automacao, engenharia eletrica, CREA-BA, biossistemas construidos, IA/PLN, series temporais, ODS e governanca preditiva.

## Regras de resposta

Para auxilio tecnico, operacional, instalacao, software, planilhas, codigo ou automacao, responder em passo a passo numerado, com comandos, validacoes e fluxos condicionais.

Para textos, e-mails, relatos, pareceres e projetos, usar paragrafos continuos, linguagem natural, tecnica e sem aparencia de texto gerado por IA.

Quando envolver informacao atual, edital, norma vigente, preco, lei, publicacao recente ou status mutavel, indicar necessidade de verificacao por fonte atual.

Para pesquisa aplicada, explicitar problema, lacuna, dados, metodo, modelos, metricas, aderencia normativa, ODS, riscos e fomento quando pertinente.

## Validacao tecnica

Python:

```bash
python -m py_compile caminho/do/arquivo.py
```

Quando `py_compile` nao for adequado, usar leitura sintatica com `ast.parse`, quando possivel.

HTML/JavaScript: verificar fechamento de tags, ordem de scripts, existencia de funcoes chamadas, referencias DOM, seletores, eventos, chamadas assincronas, tratamento de erro, fallback de carregamento e compatibilidade com os dados em `dados/*.json`.

YAML/GitHub Actions: verificar indentacao, permissoes, gatilhos, agendamento, nomes de jobs, passos, paths, secrets usados, comandos chamados e compatibilidade com os scripts existentes. Evitar Python extenso embutido em YAML quando houver script apropriado em `scripts/`.

Markdown/documentacao: manter estrutura de titulos coerente, listas validas e caminhos reais.

## Padrao para erro, correcao ou revisao

Usar este formato quando tratar erro, correcao, regressao, ajuste tecnico ou commit:

```text
Arquivo afetado:
Causa provavel:
Correcao aplicada/proposta:
Validacao realizada:
Proximo passo:
```

## Limites de alteracao

Nao alterar arquivos funcionais do dashboard, scripts, dados, workflows ou motores de previsao/classificacao quando a tarefa for apenas documentacao, configuracao de IA ou instrucao operacional.

Nao criar dependencias, jobs, credenciais, integrações externas ou automacoes novas sem necessidade explicita.

Nao declarar teste aprovado sem execucao ou verificacao correspondente. Quando a validacao nao puder ser executada, informar a limitacao.
