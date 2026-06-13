# Inventario do hub Malha IA

Este inventario registra o papel atual do repositorio `malha-ia` apos a separacao dos modulos em repositorios menores.

## Papel do hub

O `malha-ia` deve permanecer como fonte central e camada de interoperabilidade. Ele nao deve ser tratado como deposito de todos os artigos, mas como base comum para que cada artigo/modulo consiga reproduzir seus resultados.

## Arquivos centrais atuais

### Dados JSON

Arquivos em `dados/` identificados nesta rodada:

1. `area_manutencao.json`
2. `chamados.json`
3. `contexto_sazonal.json`
4. `filtros_disponiveis.json`
5. `indicadores_ods.json`
6. `log_classificacao.json`
7. `manifest.json`
8. `metricas_treino.json`
9. `pesos_ods.json`
10. `previsao_crps_multicriterio.json`
11. `previsao_custo_detalhes.json`
12. `previsao_custo_incertezas.json`
13. `previsao_custo_temporal.json`
14. `previsao_custo_validacao.json`
15. `previsao_detalhes.json`
16. `previsao_diagnostico.json`
17. `previsao_diebold_mariano.json`
18. `previsao_granger.json`
19. `previsao_incertezas.json`
20. `previsao_por_categoria.json`
21. `previsao_pressupostos.json`
22. `previsao_qqplot.json`
23. `previsao_residuos.json`
24. `previsao_temporal.json`
25. `previsao_validacao.json`

### Scripts centrais

Arquivos em `scripts/` identificados nesta rodada:

1. `aplicar_json_dashboard.py`
2. `exportar_dados_csv.py`
3. `exportar_dados_json.py`

### Workflows centrais

Arquivos em `.github/workflows/` identificados nesta rodada:

1. `atualizar-dados-json.yml`
2. `classificacao.yml`
3. `ods_indicadores.yml`
4. `pages.yml`
5. `previsao_chamados_global.yml`
6. `previsao_custo_global.yml`
7. `previsao_filtros.yml`
8. `previsao_global.yml`
9. `reclassificacao.yml`

## O que deve continuar no hub

1. `dados/chamados.json`, enquanto for a fonte estatica principal do dashboard geral;
2. `dados/manifest.json`, como registro da exportacao central;
3. arquivos globais de previsao e ODS usados por mais de um painel;
4. workflows centrais que alimentam `dados/*.json`;
5. scripts genericos de exportacao JSON/CSV;
6. `dashboard.html` e `index.html` do painel geral;
7. `CHANGELOG.md`, `CITATION.cff` e documentacao transversal.

## O que deve ficar nos repositorios filhos

1. paines especificos por artigo;
2. README especifico por eixo;
3. contratos de dados especificos;
4. workflows leves de sincronizacao a partir do hub;
5. motores ou scripts quando o repositorio precisar executar seu eixo isoladamente;
6. dados derivados leves importados de `malha-ia/dados`.

## O que nao deve ser commitado

1. credenciais Google;
2. arquivos `autenticacao_google.json`;
3. chaves privadas;
4. TXT preenchido com secrets;
5. artefatos academicos privados que devem ficar no Drive;
6. bases brutas duplicadas sem necessidade tecnica.

## Decisao sobre APIs versus importacao do hub

Repositorios filhos devem preferir importacao dos JSONs publicos do hub quando o objetivo for dashboard, documentacao ou artigo baseado em snapshot ja exportado. Isso reduz duplicacao, evita configurar secrets desnecessariamente e mantem rastreabilidade.

O acesso direto a API/planilha deve ser reservado para workflows que realmente recalculam ou escrevem resultados:

1. classificacao/reclassificacao;
2. previsao global de chamados;
3. previsao global de custos;
4. previsao por filtros;
5. ODS/ESG quando recalcular indicadores.

## Proximo inventario antes do repositorio "Demais"

Antes de criar o repositorio "Demais", revisar:

1. arquivos soltos na pasta local raiz do projeto;
2. `paper/`;
3. `docs/`;
4. dashboards locais nao versionados no hub;
5. materiais exploratorios de energia, praca, edificacoes ou propostas;
6. documentos de artigo que devem ir para Drive em vez de GitHub publico.
