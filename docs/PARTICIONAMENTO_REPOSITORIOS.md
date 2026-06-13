# Particionamento dos repositorios Malha IA

Este documento registra a divisao do antigo escopo monolitico do `malha-ia` em repositorios menores, cada um associado a um eixo analitico e a uma etapa/artigo. O `malha-ia` permanece como hub central de dados, contratos e publicacao geral.

## Decisao arquitetural

O repositorio `malha-ia` nao deve concentrar todo o desenvolvimento academico e operacional. Ele passa a funcionar como fonte central para:

1. snapshots publicos em `dados/*.json`;
2. CSVs canonicos em `dados_csv/*.csv`;
3. scripts de exportacao e sincronizacao;
4. contratos de dados;
5. dashboard geral;
6. documentacao mae do ecossistema.

Os repositorios derivados devem conter apenas o necessario para seu eixo: motor, painel, dados leves importados do hub, workflow proprio, documentacao do artigo e requisitos de execucao.

## Mapa dos repositorios e artigos

| Etapa | Prioridade/artigo | Repositorio | Funcao principal | Estado |
|---|---|---|---|---|
| 1 | Chamados/manutencao e classificacao | `classificacao-chamados` / `chamados-manutencao` | experimento de classificacao, reclassificacao e validacao humana | separado antes desta rodada |
| 2 | Previsao de chamados e estatisticas | `malha-previsao-chamados` | previsao temporal de volume de chamados e metricas associadas | separado |
| 3 | Previsao de custos e estatisticas | `malha-previsao-custos` | previsao temporal de custos em R$ e metricas associadas | separado |
| 4 | ODS/ESG | `malha-ods-esg` | classificacao ODS 9, 11, 12 e ESG, indicadores e painel | separado |
| 5 | Estatisticas associadas | `malha-estatisticas-associadas` | estatisticas descritivas, cruzamentos e tabelas de apoio | separado |
| 6 | Previsao por filtros | `malha-previsao-filtros` | catalogo de recortes e execucao pesada por campus, tipo e categoria | separado |
| 7 | Demais | a definir | anexos, estudos transversais e materiais sem artigo proprio | pendente |

## Repositorios verificados nesta rodada

1. `https://github.com/adinailson88/malha-previsao-chamados`
2. `https://github.com/adinailson88/malha-previsao-custos`
3. `https://github.com/adinailson88/malha-ods-esg`
4. `https://github.com/adinailson88/malha-estatisticas-associadas`
5. `https://github.com/adinailson88/malha-previsao-filtros`

Todos foram verificados via GitHub API como repositorios existentes com branch padrao `main`.

## Regra de permanencia no hub

Fica no `malha-ia` quando o arquivo for usado por mais de um eixo ou representar a fonte oficial do ecossistema:

1. `dados/chamados.json`;
2. `dados/manifest.json`;
3. `dados/filtros_disponiveis.json`;
4. `dados/contexto_sazonal.json`;
5. `dados/area_manutencao.json`;
6. snapshots globais de previsao;
7. snapshots globais de ODS;
8. scripts de exportacao;
9. workflows de alimentacao central;
10. README, changelog, citacao e contrato geral.

## Regra de migracao para repositorio especifico

Vai para repositorio especifico quando o arquivo pertencer claramente a um artigo/eixo e puder evoluir sem alterar a fonte central:

1. painel especifico do eixo;
2. documentacao metodologica do artigo;
3. workflow do eixo;
4. script auxiliar exclusivo;
5. dados derivados leves;
6. graficos, tabelas e textos de artigo.

## Regra para o repositorio "Demais"

O repositorio "Demais" so deve ser criado depois de inventario do que sobrar no hub e nos diretorios locais. Ele deve receber apenas materiais que:

1. nao sustentam artigo independente no momento;
2. cruzam mais de um eixo;
3. sao anexos exploratorios;
4. servem como suplemento tecnico;
5. ainda nao tem maturidade para virar repositorio/artigo proprio.

Nao mover para "Demais" arquivos que sejam fonte central, credenciais, dados brutos sensiveis ou artefatos academicos que devem ficar no Drive.

## Ordem operacional recomendada

1. manter o `malha-ia` como hub central;
2. sincronizar os repositorios derivados a partir de `dados/*.json`;
3. evitar duplicar `chamados.json` nos repositorios filhos, salvo justificativa tecnica;
4. manter secrets iguais quando todos acessarem a mesma planilha;
5. criar o repositorio "Demais" somente apos inventario final dos arquivos residuais;
6. registrar no artigo de cada etapa qual repositorio, snapshot e workflow produziram os resultados.
