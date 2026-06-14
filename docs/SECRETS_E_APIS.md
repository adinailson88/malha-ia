# Secrets e APIs do ecossistema Malha IA

Este documento define a politica de credenciais para o particionamento do Malha IA em repositorios menores.

## Principio geral

Os repositorios derivados nao precisam de credenciais para exibir dashboards estaticos quando consomem os JSONs publicos do hub `malha-ia`. Credenciais so sao necessarias quando um workflow acessa diretamente Google Sheets, Apps Script ou outro servico privado.

## Secrets principais

| Secret | Uso | Obrigatorio em quais casos | Observacao |
|---|---|---|---|
| `AUTENTICACAO_GOOGLE` | autenticar conta de servico Google | workflows que leem/escrevem planilha Google | mesmo valor pode ser reutilizado nos repositorios que acessam a mesma planilha |
| `APPS_SCRIPT_URL` | consultar Web App Apps Script | rotinas que dependem do endpoint publicado | pode ser compartilhado se todos usam a mesma planilha/endpoint |
| `GCP_SA_KEY` | conta de servico do experimento de classificacao | repo `classificacao-chamados`, quando aplicavel | manter separado se o projeto GCP for diferente |

## Formato esperado de `AUTENTICACAO_GOOGLE`

Nos workflows do Malha IA, o secret `AUTENTICACAO_GOOGLE` e tratado como JSON de conta de servico codificado em Base64.

Fluxo esperado:

```bash
echo "$AUTENTICACAO_GOOGLE" | base64 -d > autenticacao_google.json
```

Portanto, ao cadastrar o secret no GitHub, o valor deve ser o conteudo Base64 do arquivo JSON da conta de servico, nao o caminho do arquivo local.

## Quando nao precisa de secret

Nao precisa de secret quando o repositorio:

1. baixa arquivos publicos de `https://raw.githubusercontent.com/adinailson88/malha-ia/main/dados/`;
2. publica dashboard estatico no GitHub Pages;
3. converte JSON publico para CSV;
4. documenta resultados ja exportados.

Exemplos:

1. `scripts/baixar_dados_hub.py`;
2. `scripts/exportar_dados_csv.py`;
3. dashboards que leem `dados/*.json`;
4. workflows leves de sincronizacao a partir do hub.
5. portal central que le `dados/module_manifest.json` e `dados/manifest_hub.json` dos repositorios filhos.

## Quando precisa de secret

Precisa de secret quando o repositorio:

1. le diretamente uma planilha Google;
2. escreve resultados em abas da planilha;
3. recalcula previsoes usando dados privados;
4. acessa Apps Script nao-publico;
5. executa classificacao/reclassificacao com persistencia em planilha.

## Politica para repositorios derivados

Como todos os repositorios derivados acessam a mesma base principal, o procedimento recomendado e:

1. cadastrar o mesmo `AUTENTICACAO_GOOGLE` nos repositorios que executam workflows pesados;
2. deixar repositorios de dashboard leve sem secret, quando possivel;
3. usar o hub `malha-ia` para publicar JSONs publicos reduzidos;
4. evitar que repositorios filhos acessem a planilha sem necessidade;
5. nunca versionar `autenticacao_google.json`, `credenciais*.json`, chaves privadas ou TXT de preenchimento.

## Portal central

O portal central do `malha-ia` nao usa secrets. Ele le apenas URLs publicas:

1. dashboards publicados no GitHub Pages;
2. `dados/module_manifest.json`;
3. `dados/manifest_hub.json`;
4. metadados publicos do GitHub para commit da branch `main`.

Se um repositorio filho precisar recalcular dados, isso continua sendo responsabilidade do workflow proprio daquele repositorio e do secret correspondente.

## TXT de preenchimento de secrets

Quando for necessario preencher ou reproduzir secrets, o procedimento seguro e criar um TXT local com campos vazios, preencher manualmente e usar o conteudo somente no GitHub Secrets.

Modelo recomendado:

```text
REPOSITORIO:
SECRET:
ORIGEM DO VALOR:
VALOR A COLAR NO GITHUB SECRET:
OBSERVACOES:
```

Um modelo vazio foi salvo em `docs/MODELO_PREENCHER_SECRETS.txt`. Para uso real, fazer uma copia local, preencher fora do versionamento e colar o valor no GitHub Secrets.

O TXT preenchido nao deve ser commitado.

## Onde obter as informacoes

1. `AUTENTICACAO_GOOGLE`: arquivo JSON da conta de servico Google Cloud que tenha acesso de leitura/escrita a planilha.
2. `APPS_SCRIPT_URL`: URL `/exec` do Web App publicado no Apps Script.
3. ID da planilha principal: URL da planilha Google, trecho entre `/d/` e `/edit`.
4. Permissao da conta de servico: compartilhar a planilha com o e-mail `client_email` presente no JSON da conta de servico.

## Validacao minima

Depois de configurar secrets em um repositorio, validar com:

```bash
gh secret list --repo adinailson88/NOME_DO_REPOSITORIO
gh workflow run NOME_DO_WORKFLOW.yml --repo adinailson88/NOME_DO_REPOSITORIO
gh run list --repo adinailson88/NOME_DO_REPOSITORIO --limit 5
```

Nao declarar um workflow como validado sem conferir `status=completed` e `conclusion=success`.
