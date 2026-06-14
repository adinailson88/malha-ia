# Portal central de dashboards

O portal central do Malha IA fica em `https://adinailson88.github.io/malha-ia/` e apresenta todos os dashboards do ecossistema em um unico ponto de entrada.

## Arquitetura

O portal usa integracao leve por manifestos publicos:

1. `dados/repositorios_malha.json`: catalogo fixo dos repositorios e dashboards.
2. `dados/module_manifest.json`: manifesto do proprio hub.
3. `dados/indice_modulos.json`: indice consolidado gerado automaticamente.
4. `scripts/gerar_indice_modulos.py`: consolida manifests, URLs e status.
5. `.github/workflows/atualizar-indice-modulos.yml`: atualiza o indice sem usar secrets.

## Politica de comunicacao entre repositorios

A v1 nao dispara workflows pesados entre repositorios. Cada repositorio publica seu proprio dashboard e manifesto; o hub apenas le essas URLs publicas e mostra o status.

Essa decisao evita:

1. dependencia cruzada de secrets;
2. execucoes pesadas acidentais;
3. duplicacao da base bruta;
4. acoplamento forte entre artigos.

## Status exibidos

1. `online`: manifesto, Pages e dashboard responderam.
2. `sem_manifesto`: o dashboard pode existir, mas o manifesto do modulo nao foi lido.
3. `dashboard_indisponivel`: manifesto existe, mas Pages ou dashboard falhou.
4. `indisponivel`: falha geral de leitura.

## Validacao local

```powershell
python -m py_compile scripts\gerar_indice_modulos.py
python scripts\gerar_indice_modulos.py
python -m http.server 8064
```

Depois abrir:

```text
http://127.0.0.1:8064/
```

## Validacao publicada

```powershell
gh workflow run atualizar-indice-modulos.yml --repo adinailson88/malha-ia
gh run list --repo adinailson88/malha-ia --limit 5
```

Validar:

1. `https://adinailson88.github.io/malha-ia/`
2. `https://adinailson88.github.io/malha-ia/dados/indice_modulos.json`
3. todos os dashboards listados no portal.
