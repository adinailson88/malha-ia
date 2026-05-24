#!/usr/bin/env python3
"""Aplica no dashboard o consumo preferencial de JSON estatico.

O patch e idempotente: se ja estiver aplicado, nao duplica funcoes nem
constantes. A funcao fetchAba passa a tentar dados/*.json antes do Apps
Script, mantendo fallback automatico.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

ARQUIVO_HTML = Path("dashboard_malha_ia_v36.html")

APPS_SCRIPT_CONST = (
    'const APPS_SCRIPT_URL = "https://script.google.com/macros/s/'
    'AKfycbyLQMA7D9sohZ-nqo-Z2ydVuBi-7igmEFPmhYy3gbOLMsawx78E-DyfnvecMSb-00om/exec";'
)

FETCH_ANTIGO = """async function fetchAba(nomeAba) {
  try {
    const url = `${APPS_SCRIPT_URL}?sheet=${encodeURIComponent(nomeAba)}`;
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.error) {
      registrarLog(`Aba ${nomeAba}: ${data.error}`, 'warn');
      return [];
    }
    return data;
  } catch (e) {
    registrarLog(`Falha ao acessar ${nomeAba}: ${e.message}`, 'err');
    return [];
  }
}
"""

FUNCOES_JSON = """function slugAbaJson(nomeAba) {
  return (nomeAba || '')
    .toString()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase() || 'aba';
}

async function fetchAbaJsonEstatico(nomeAba) {
  if (!USAR_JSON_ESTATICO) return null;
  const slug = slugAbaJson(nomeAba);
  const url = `${DADOS_JSON_BASE}/${slug}.json?v=${Date.now()}`;
  try {
    const resp = await fetch(url, { cache: 'no-store' });
    if (resp.status === 404) return null;
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    registrarLog(`JSON ${slug}.json: ${Math.max(0, data.length - 1)} linhas`, 'ok');
    return data;
  } catch (e) {
    registrarLog(`JSON indisponivel para ${nomeAba}: ${e.message}. Usando Apps Script.`, 'warn');
    return null;
  }
}

"""

FETCH_NOVO = FUNCOES_JSON + """async function fetchAba(nomeAba) {
  const jsonEstatico = await fetchAbaJsonEstatico(nomeAba);
  if (jsonEstatico) return jsonEstatico;
  try {
    const url = `${APPS_SCRIPT_URL}?sheet=${encodeURIComponent(nomeAba)}`;
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.error) {
      registrarLog(`Aba ${nomeAba}: ${data.error}`, 'warn');
      return [];
    }
    return data;
  } catch (e) {
    registrarLog(`Falha ao acessar ${nomeAba}: ${e.message}`, 'err');
    return [];
  }
}
"""


def validar_scripts_js(texto: str) -> None:
    scripts = re.findall(r"<script>(.*?)</script>", texto, flags=re.S)
    tmp_dir = Path(tempfile.gettempdir())
    for idx, script in enumerate(scripts):
        tmp = tmp_dir / f"malha_dashboard_script_{idx}.js"
        tmp.write_text(script, encoding="utf-8")
        subprocess.run(["node", "--check", str(tmp)], check=True)


def main() -> int:
    bruto = ARQUIVO_HTML.read_text(encoding="utf-8")
    usa_crlf = "\r\n" in bruto
    texto = bruto.replace("\r\n", "\n")

    if 'const DADOS_JSON_BASE = "dados";' not in texto:
        if APPS_SCRIPT_CONST not in texto:
            raise SystemExit("Marcador APPS_SCRIPT_URL nao encontrado.")
        texto = texto.replace(
            APPS_SCRIPT_CONST,
            APPS_SCRIPT_CONST + '\nconst DADOS_JSON_BASE = "dados";\nconst USAR_JSON_ESTATICO = true;',
            1,
        )

    if "function slugAbaJson(nomeAba)" not in texto:
        if FETCH_ANTIGO not in texto:
            raise SystemExit("Bloco antigo de fetchAba nao encontrado.")
        texto = texto.replace(FETCH_ANTIGO, FETCH_NOVO, 1)
    elif "const jsonEstatico = await fetchAbaJsonEstatico(nomeAba);" not in texto:
        raise SystemExit("slugAbaJson existe, mas fetchAba ainda nao usa JSON estatico.")

    if 'const DADOS_JSON_BASE = "dados";' not in texto:
        raise SystemExit("Validacao falhou: DADOS_JSON_BASE ausente.")
    if "function slugAbaJson(nomeAba)" not in texto:
        raise SystemExit("Validacao falhou: slugAbaJson ausente.")
    if "const jsonEstatico = await fetchAbaJsonEstatico(nomeAba);" not in texto:
        raise SystemExit("Validacao falhou: fetchAba nao tenta JSON estatico.")

    validar_scripts_js(texto)
    ARQUIVO_HTML.write_text(texto.replace("\n", "\r\n") if usa_crlf else texto, encoding="utf-8", newline="")
    print("Dashboard atualizado para priorizar JSON estatico com fallback Apps Script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
