"""Teste mínimo, somente leitura, da API REST do GLPI.

Valida:
1. formato de GLPI_URL;
2. autenticação com USER_TOKEN + APP_TOKEN;
3. abertura de sessão;
4. leitura de ITILCategory;
5. encerramento da sessão.

Não executa PUT/POST/DELETE e não imprime credenciais.
"""

from __future__ import annotations

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TIMEOUT = 10


def get_json(url: str, headers: dict[str, str]):
    req = Request(url, headers=headers, method="GET")
    try:
        with urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read()
            return json.loads(body) if body else None, resp.status
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"falha de conexão/timeout: {exc}") from None


def main() -> int:
    base = os.getenv("GLPI_URL", "").strip().rstrip("/")
    user_token = os.getenv("GLPI_USER_TOKEN", "").strip()
    app_token = os.getenv("GLPI_APP_TOKEN", "").strip()

    faltantes = [
        nome
        for nome, valor in {
            "GLPI_URL": base,
            "GLPI_USER_TOKEN": user_token,
            "GLPI_APP_TOKEN": app_token,
        }.items()
        if not valor
    ]
    if faltantes:
        print("FALHA: secrets ausentes: " + ", ".join(faltantes))
        return 2

    if not base.startswith("https://") or not base.endswith("/apirest.php"):
        print("FALHA: GLPI_URL deve começar com https:// e terminar em /apirest.php")
        return 3

    print("1/3 Testando initSession...")
    try:
        data, _ = get_json(
            base + "/initSession",
            {
                "Authorization": f"user_token {user_token}",
                "App-Token": app_token,
                "Accept": "application/json",
            },
        )
    except RuntimeError as exc:
        print(f"FALHA no initSession: {exc}")
        return 4

    if not isinstance(data, dict) or not data.get("session_token"):
        print("FALHA: initSession respondeu sem session_token")
        return 5

    session = data["session_token"]
    headers = {
        "Session-Token": session,
        "App-Token": app_token,
        "Accept": "application/json",
    }

    print("2/3 Testando leitura da API...")
    try:
        categorias, _ = get_json(base + "/ITILCategory?range=0-0", headers)
    except RuntimeError as exc:
        print(f"FALHA na leitura ITILCategory: {exc}")
        return 6
    finally:
        try:
            get_json(base + "/killSession", headers)
        except Exception:
            pass

    if not isinstance(categorias, list):
        print("FALHA: resposta de ITILCategory não é uma lista")
        return 7

    print("3/3 OK")
    print("API_GLPI_OK: autenticação e leitura funcionando. Nenhuma alteração foi feita.")
    print(f"Categorias retornadas no teste: {len(categorias)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
