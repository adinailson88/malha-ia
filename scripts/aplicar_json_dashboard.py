#!/usr/bin/env python3
"""Aplica no dashboard o consumo preferencial de JSON estatico.

O patch e idempotente: se ja estiver aplicado, nao duplica funcoes nem
constantes. A funcao fetchAba passa a tentar dados/*.json antes do Apps
Script, mantendo fallback automatico.

A partir da migracao do GitHub Pages, dashboard_malha_ia_v36.html passou a
ser apenas um redirecionador para dashboard.html. Por isso este script nao
pode mais assumir um unico arquivo fixo: ele localiza automaticamente o HTML
real antes de aplicar/validar o patch.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

CANDIDATOS_HTML = [
    Path("dashboard.html"),
    Path("dashboard_malha_ia_v36.html"),
    Path("index.html"),
]

APPS_SCRIPT_CONST = (
    'const APPS_SCRIPT_URL = "https://script.google.com/macros/s/'
    'AKfycbyLQMA7D9sohZ-nqo-Z2ydVuBi-7igmEFPmhYy3gbOLMsawx78E-DyfnvecMSb-00om/exec";'
)

CONSTANTES_JSON = 'const DADOS_JSON_BASE = "dados";\nconst USAR_JSON_ESTATICO = true;'

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

FUNCOES_JSON = r"""function slugAbaJson(nomeAba) {
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
  const cacheJanela = Math.floor(Date.now() / (15 * 60 * 1000));
  const url = `${DADOS_JSON_BASE}/${slug}.json?v=${cacheJanela}`;
  try {
    const resp = await fetch(url, { cache: 'force-cache' });
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


def normalizar_quebras(texto: str) -> tuple[str, bool]:
    usa_crlf = "\r\n" in texto
    return texto.replace("\r\n", "\n"), usa_crlf


def parece_dashboard_real(texto: str) -> bool:
    return (
        "<script" in texto
        and (
            "APPS_SCRIPT_URL" in texto
            or "fetchAba(nomeAba)" in texto
            or "DADOS_JSON_BASE" in texto
        )
    )


def destino_meta_refresh(texto: str) -> str | None:
    padrao = re.compile(
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+content=["\'][^"\']*url=([^"\'>;]+)[^"\']*["\']',
        flags=re.I,
    )
    achado = padrao.search(texto)
    if not achado:
        return None
    destino = achado.group(1).strip()
    if destino and not destino.startswith(("http://", "https://", "//")):
        return destino
    return None


def escolher_arquivo_html() -> Path:
    existentes = [p for p in CANDIDATOS_HTML if p.exists()]
    for caminho in existentes:
        texto, _ = normalizar_quebras(caminho.read_text(encoding="utf-8"))
        if parece_dashboard_real(texto):
            return caminho

    for caminho in existentes:
        texto, _ = normalizar_quebras(caminho.read_text(encoding="utf-8"))
        destino = destino_meta_refresh(texto)
        if destino:
            destino_path = caminho.parent / destino
            if destino_path.exists():
                destino_texto, _ = normalizar_quebras(destino_path.read_text(encoding="utf-8"))
                if parece_dashboard_real(destino_texto):
                    return destino_path

    nomes = ", ".join(str(p) for p in existentes) or "nenhum arquivo encontrado"
    raise SystemExit(
        "Arquivo HTML real do dashboard nao encontrado. "
        f"Arquivos avaliados: {nomes}."
    )


def inserir_constantes_json(texto: str) -> str:
    if 'const DADOS_JSON_BASE = "dados";' in texto:
        return texto

    if APPS_SCRIPT_CONST in texto:
        return texto.replace(APPS_SCRIPT_CONST, APPS_SCRIPT_CONST + "\n" + CONSTANTES_JSON, 1)

    padrao = re.compile(r'(const\s+APPS_SCRIPT_URL\s*=\s*["\'][^"\']+["\'];)')
    novo_texto, alteracoes = padrao.subn(r"\1\n" + CONSTANTES_JSON, texto, count=1)
    if alteracoes == 1:
        return novo_texto

    raise SystemExit(
        "Marcador APPS_SCRIPT_URL nao encontrado no HTML real do dashboard. "
        "Procure por APPS_SCRIPT_URL, script.google.com ou fetchAba no arquivo-alvo."
    )


def localizar_fim_funcao(texto: str, inicio: int) -> int:
    abertura = texto.find("{", inicio)
    if abertura == -1:
        return -1

    profundidade = 0
    for pos in range(abertura, len(texto)):
        char = texto[pos]
        if char == "{":
            profundidade += 1
        elif char == "}":
            profundidade -= 1
            if profundidade == 0:
                return pos + 1
    return -1


def substituir_funcao_fetch_generica(texto: str) -> str:
    inicio = texto.find("async function fetchAba(nomeAba)")
    if inicio == -1:
        raise SystemExit("Bloco antigo de fetchAba nao encontrado.")

    fim = localizar_fim_funcao(texto, inicio)
    if fim == -1:
        raise SystemExit("Bloco fetchAba encontrado, mas com chaves aparentemente incompletas.")

    while fim < len(texto) and texto[fim] in " \t\r\n":
        fim += 1

    return texto[:inicio] + FETCH_NOVO.rstrip() + "\n" + texto[fim:]


def aplicar_patch_fetch(texto: str) -> str:
    if "function slugAbaJson(nomeAba)" not in texto:
        if FETCH_ANTIGO in texto:
            return texto.replace(FETCH_ANTIGO, FETCH_NOVO, 1)
        return substituir_funcao_fetch_generica(texto)

    if "const jsonEstatico = await fetchAbaJsonEstatico(nomeAba);" not in texto:
        raise SystemExit("slugAbaJson existe, mas fetchAba ainda nao usa JSON estatico.")

    return texto


def validar_scripts_js(texto: str) -> None:
    scripts = re.findall(r"<script>(.*?)</script>", texto, flags=re.S)
    tmp_dir = Path(tempfile.gettempdir())
    for idx, script in enumerate(scripts):
        tmp = tmp_dir / f"malha_dashboard_script_{idx}.js"
        tmp.write_text(script, encoding="utf-8")
        subprocess.run(["node", "--check", str(tmp)], check=True)


def validar_patch(texto: str) -> None:
    if 'const DADOS_JSON_BASE = "dados";' not in texto:
        raise SystemExit("Validacao falhou: DADOS_JSON_BASE ausente.")
    if "function slugAbaJson(nomeAba)" not in texto:
        raise SystemExit("Validacao falhou: slugAbaJson ausente.")
    if "const jsonEstatico = await fetchAbaJsonEstatico(nomeAba);" not in texto:
        raise SystemExit("Validacao falhou: fetchAba nao tenta JSON estatico.")


def main() -> int:
    arquivo_html = escolher_arquivo_html()
    bruto = arquivo_html.read_text(encoding="utf-8")
    texto, usa_crlf = normalizar_quebras(bruto)

    texto = inserir_constantes_json(texto)
    texto = aplicar_patch_fetch(texto)
    validar_patch(texto)
    validar_scripts_js(texto)

    saida = texto.replace("\n", "\r\n") if usa_crlf else texto
    if saida != bruto:
        arquivo_html.write_text(saida, encoding="utf-8", newline="")
        print(f"Dashboard atualizado: {arquivo_html}")
    else:
        print(f"Dashboard ja estava atualizado: {arquivo_html}")

    print("Leitura preferencial de JSON estatico validada com fallback Apps Script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
