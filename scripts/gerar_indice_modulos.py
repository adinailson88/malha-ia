import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TIMEOUT = 25


def carregar_json_local(caminho: Path):
    return json.loads(caminho.read_text(encoding="utf-8"))


def carregar_json_url(url: str):
    req = Request(url, headers={"User-Agent": "malha-ia-portal/1.0"})
    with urlopen(req, timeout=TIMEOUT) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


def carregar_json(ref: str, raiz: Path):
    if ref.startswith("http://") or ref.startswith("https://"):
        return carregar_json_url(ref)
    return carregar_json_local(raiz / ref)


def checar_url(url: str):
    try:
        req = Request(url, method="GET", headers={"User-Agent": "malha-ia-portal/1.0"})
        with urlopen(req, timeout=TIMEOUT) as resposta:
            return {"ok": 200 <= resposta.status < 400, "status_code": resposta.status, "erro": None}
    except HTTPError as exc:
        return {"ok": False, "status_code": exc.code, "erro": str(exc)}
    except URLError as exc:
        return {"ok": False, "status_code": None, "erro": str(exc.reason)}
    except Exception as exc:
        return {"ok": False, "status_code": None, "erro": str(exc)}


def extrair_data_manifest(manifest):
    if not isinstance(manifest, dict):
        return None
    return manifest.get("atualizado_em_utc") or manifest.get("gerado_em_utc")


def resumo_manifest(manifest):
    if not isinstance(manifest, dict):
        return {}
    arquivos = manifest.get("arquivos")
    if isinstance(arquivos, list):
        return {
            "arquivos": len(arquivos),
            "linhas_dados": sum(int(item.get("linhas_dados", 0) or 0) for item in arquivos if isinstance(item, dict)),
        }
    abas = manifest.get("abas")
    if isinstance(abas, dict):
        return {
            "abas_exportadas": manifest.get("total_abas_exportadas", len(abas)),
            "falhas": manifest.get("total_falhas", 0),
            "falhas_criticas": manifest.get("total_falhas_criticas", 0),
        }
    return {}


def obter_commit(repo: str):
    url = f"https://api.github.com/repos/{repo}/commits/main"
    try:
        dados = carregar_json_url(url)
        return {
            "sha": str(dados.get("sha", ""))[:12],
            "html_url": dados.get("html_url"),
            "data": dados.get("commit", {}).get("committer", {}).get("date"),
        }
    except Exception as exc:
        return {"sha": None, "html_url": None, "data": None, "erro": str(exc)}


def consolidar_modulo(item: dict, raiz: Path):
    modulo = dict(item)
    erros = []

    try:
        manifest_modulo = carregar_json(item["module_manifest_url"], raiz)
    except Exception as exc:
        manifest_modulo = None
        erros.append(f"module_manifest: {exc}")

    try:
        manifest_dados = carregar_json(item["manifest_hub_url"], raiz)
    except Exception as exc:
        manifest_dados = None
        erros.append(f"manifest_dados: {exc}")

    dashboard = checar_url(item["dashboard_url"])
    pages = checar_url(item["pages_url"])
    commit = obter_commit(item["repo"])

    online = bool(manifest_modulo) and dashboard["ok"] and pages["ok"]
    status = "online" if online else "indisponivel"
    if not manifest_modulo:
        status = "sem_manifesto"
    elif not dashboard["ok"] or not pages["ok"]:
        status = "dashboard_indisponivel"

    modulo.update(
        {
            "status": status,
            "online": online,
            "module_manifest_ok": bool(manifest_modulo),
            "manifest_dados_ok": bool(manifest_dados),
            "dashboard_http": dashboard,
            "pages_http": pages,
            "commit_main": commit,
            "dados_atualizados_em_utc": extrair_data_manifest(manifest_dados),
            "resumo_dados": resumo_manifest(manifest_dados),
            "manifest_modulo": manifest_modulo,
            "erros": erros,
        }
    )
    return modulo


def main() -> int:
    raiz = Path(__file__).resolve().parents[1]
    catalogo = carregar_json_local(raiz / "dados" / "repositorios_malha.json")
    modulos = [consolidar_modulo(item, raiz) for item in sorted(catalogo, key=lambda x: x.get("ordem", 999))]

    indice = {
        "schema_version": "1.0",
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
        "politica": "portal_central_manifesto_status_sem_orquestracao_pesada",
        "total_modulos": len(modulos),
        "modulos_online": sum(1 for item in modulos if item["online"]),
        "modulos_com_secret": sum(1 for item in modulos if item.get("usa_secret")),
        "modulos_sem_secret": sum(1 for item in modulos if not item.get("usa_secret")),
        "modulos": modulos,
    }

    destino = raiz / "dados" / "indice_modulos.json"
    destino.write_text(json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK {destino.relative_to(raiz)}: {indice['modulos_online']}/{indice['total_modulos']} online")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        raise SystemExit(1)
