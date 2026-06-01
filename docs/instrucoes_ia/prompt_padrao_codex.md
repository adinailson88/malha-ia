# Prompt padrao para Codex

Leia `AGENTS.md` antes de atuar neste repositório. Verifique o contexto do projeto Malha IA, os arquivos diretamente afetados e os contratos existentes entre dashboard, `dados/*.json`, scripts, Apps Script/Google Sheets e workflows.

Preserve a arquitetura existente, aplique a menor alteração necessária e não altere funcionalidades sem informar o impacto. Não remova fallback. Valide alterações sempre que possível, incluindo `python -m py_compile` ou `ast.parse` para Python, verificação estrutural de HTML/JavaScript e revisão de YAML/GitHub Actions.

Responda em modo técnico, objetivo e verificável. Quando faltar dado, declare: `Informação insuficiente para verificar.` Para erro ou correção, use:

```text
Arquivo afetado:
Causa provável:
Correção aplicada/proposta:
Validação realizada:
Próximo passo:
```
