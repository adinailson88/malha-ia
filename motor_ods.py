# -*- coding: utf-8 -*-
"""
MOTOR DE GOVERNANÇA PREDITIVA – BIOSSISTEMAS CONSTRUÍDOS
Módulo 4: motor_ods.py
Extraído de motor_v36.py (v4.0.8) — contém APENAS o pipeline de indicadores
ODS (Objetivos de Desenvolvimento Sustentável 9, 11, 12) por campus.
Sem classificação LSTM, sem previsão de chamados, sem previsão de custos,
sem filtros, sem APIs de LLM externas.

Execução:
    python motor_ods.py --apenas-ods

Gera/atualiza as abas na planilha Google Sheets CHAMADOS:
    INDICADORES_ODS — 10 indicadores brutos por campus
    PESOS_ODS       — matriz de pesos ODS 9/11/12 (criada se não existir;
                      preservada se já existir — editável pelo usuário)

Abas geradas (prefixos):
    INDICADORES_ODS : Campus × 10 indicadores (brutos, sem normalização)
    PESOS_ODS       : 10 indicadores × 3 ODS (pesos configuráveis)

Cálculo dos índices compostos ODS: realizado pelo dashboard HTML
(dashboard_malha_ia_v36.html) via leitura de INDICADORES_ODS + PESOS_ODS.
"""



# =====================================================================
# 1. INSTALAÇÃO INTELIGENTE DE DEPENDÊNCIAS COM CACHE PERSISTENTE
# =====================================================================
import os
import sys
import json
import subprocess

try:
    from google.colab import drive
    _EM_COLAB = True
except ImportError:
    _EM_COLAB = False

if _EM_COLAB:
    drive.mount('/content/drive')
    CAMINHO_PASTA = '/content/drive/MyDrive/Malha_IA'
else:
    CAMINHO_PASTA = os.path.dirname(os.path.abspath(__file__))

PASTA_LIBS = f'{CAMINHO_PASTA}/libs'
ARQUIVO_LOCK = f'{PASTA_LIBS}/requirements.lock'

PACOTES_REQUERIDOS = {
    'gspread': '6.1.4',
    'pandas': '2.2.3',
}

def carregar_lock():
    if not os.path.exists(ARQUIVO_LOCK):
        return None
    try:
        with open(ARQUIVO_LOCK, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None

def salvar_lock(pacotes):
    os.makedirs(PASTA_LIBS, exist_ok=True)
    with open(ARQUIVO_LOCK, 'w', encoding='utf-8') as f:
        json.dump(pacotes, f, indent=2, ensure_ascii=False)

def precisa_instalar():
    if not os.path.exists(PASTA_LIBS):
        return True, "pasta libs não existe"
    lock_atual = carregar_lock()
    if lock_atual is None:
        return True, "requirements.lock ausente"
    if lock_atual != PACOTES_REQUERIDOS:
        adicionados = set(PACOTES_REQUERIDOS) - set(lock_atual)
        removidos = set(lock_atual) - set(PACOTES_REQUERIDOS)
        alterados = {k for k in PACOTES_REQUERIDOS
                     if k in lock_atual and PACOTES_REQUERIDOS[k] != lock_atual[k]}
        motivos = []
        if adicionados: motivos.append(f"adicionados: {', '.join(adicionados)}")
        if removidos:   motivos.append(f"removidos: {', '.join(removidos)}")
        if alterados:   motivos.append(f"versão alterada: {', '.join(alterados)}")
        return True, "; ".join(motivos)
    return False, "lock confere"

def instalar_pacotes():
    print(f"[Cache] Instalando pacotes em {PASTA_LIBS}...")
    print("[Cache] Esta operação roda apenas na primeira vez ou quando a lista muda.")
    os.makedirs(PASTA_LIBS, exist_ok=True)
    spec_pacotes = [f"{nome}=={ver}" for nome, ver in PACOTES_REQUERIDOS.items()]
    cmd = ['pip', 'install', '--target', PASTA_LIBS, '--upgrade'] + spec_pacotes
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        print("[Cache] ERRO na instalação:")
        print(resultado.stderr[-2000:])
        raise RuntimeError("Falha ao instalar pacotes — veja stderr acima.")
    salvar_lock(PACOTES_REQUERIDOS)
    print(f"[Cache] {len(PACOTES_REQUERIDOS)} pacotes principais instalados e lock salvo.")

if _EM_COLAB:
    deve_instalar, motivo = precisa_instalar()
    if deve_instalar:
        print(f"[Cache] Reinstalação necessária: {motivo}")
        instalar_pacotes()
        print("\n" + "="*70)
        print("⚠️  PACOTES INSTALADOS PELA PRIMEIRA VEZ (ou após mudança de versão).")
        print("    Reinicie o runtime do Colab agora:")
        print("        Menu superior → Ambiente de execução → Reiniciar sessão")
        print("    Depois execute esta célula novamente — será instantâneo.")
        print("="*70 + "\n")
        try:
            import IPython
            IPython.Application.instance().kernel.do_shutdown(restart=True)
        except Exception:
            pass
        raise SystemExit("Aguardando reinício do runtime.")
    else:
        print(f"[Cache] {len(PACOTES_REQUERIDOS)} pacotes carregados do cache em {PASTA_LIBS}.")

    if PASTA_LIBS not in sys.path:
        sys.path.insert(0, PASTA_LIBS)
else:
    print("[Local] Modo offline — pacotes carregados do ambiente Python local.")



# =====================================================================
# 2. IMPORTAÇÕES
# =====================================================================
import gspread
from gspread.exceptions import WorksheetNotFound, APIError
import pandas as pd
_VERSAO_MOTOR = "v4.0.8-ods"
print(f"[Imports] OK - pandas={pd.__version__} - {_VERSAO_MOTOR}")

# =====================================================================
# 3. CONFIGURAÇÕES INICIAIS
# =====================================================================
ARQUIVO_GOOGLE = f'{CAMINHO_PASTA}/autenticacao_google.json'
gc = gspread.service_account(filename=ARQUIVO_GOOGLE)

NOME_PLANILHA = "CHAMADOS"
ID_PLANILHA = "1VgHY6NmCQLtA3lcfQAzGIRqJFZGHwcGhZ4zaXkqOmz4"
# Mapeamento de colunas usado pelos indicadores ODS
COL_TITULO = 1             # B
COL_DATA_ABERTURA = 2      # C
COL_CAMPUS = 7             # H
COL_VALOR = 16             # Q
COL_CAT_IA = 25            # Z
COL_CRITICIDADE_OUT = 30   # AD

# Colunas opcionais. Atribua o indice zero-based se a planilha passar a te-las.
COL_DATA_CONCLUSAO = None
COL_LOCAL = None

try:
    doc = gc.open_by_key(ID_PLANILHA)
    planilha = doc.worksheet("CHAMADOS")
    print(f"✅ Conectado à planilha: {NOME_PLANILHA}, aba: CHAMADOS")
except Exception as e:
    print(f"❌ Erro crítico: {e}")
    raise



# =====================================================================
# 4. UTILITÁRIO DE ABAS COM CACHE
# =====================================================================
_cache_abas = {}

def obter_aba(nome, linhas=100, colunas=10, cabecalho=None):
    if nome in _cache_abas:
        return _cache_abas[nome]
    try:
        aba = doc.worksheet(nome)
    except WorksheetNotFound:
        aba = doc.add_worksheet(title=nome, rows=linhas, cols=colunas)
    if cabecalho:
        try:
            valores_atuais = aba.get_all_values()
            if not valores_atuais or all(c == "" for c in valores_atuais[0]):
                aba.update(values=[cabecalho], range_name='A1', value_input_option='USER_ENTERED')
        except Exception as e:
            print(f"[Aviso] Não foi possível gravar cabeçalho em {nome}: {e}")
    _cache_abas[nome] = aba
    return aba





# =====================================================================
# 8. PARSER DE VALOR (dependência de calcular_indicadores_ods_por_campus)
# =====================================================================

# =====================================================================
# [v4.0.3 — Fase 4A] Parser e série de custos (Coluna Q)
# =====================================================================
def parse_valor_chamado(valor_raw):
    """Converte valor da coluna Q em float. Retorna None se inválido.

    Tolera: 'R$ 1.234,56', '1234.56', '1234,56', número Sheets nativo, vazio.
    """
    if valor_raw is None or valor_raw == '':
        return None
    if isinstance(valor_raw, (int, float)):
        v = float(valor_raw)
        return v if v >= 0 else None
    s = str(valor_raw).strip()
    if not s:
        return None
    s = s.replace('R$', '').replace(' ', '').strip()
    if ',' in s and '.' in s:
        # Formato '1.234,56' — remove pontos de milhar, troca vírgula por ponto
        s = s.replace('.', '').replace(',', '.')
    elif ',' in s:
        s = s.replace(',', '.')
    try:
        v = float(s)
        return v if v >= 0 else None
    except (ValueError, TypeError):
        return None




# =====================================================================
# 9. INDICADORES ODS POR CAMPUS (ODS 9 / 11 / 12) [v4.0.3 — Fase 4A]
# =====================================================================

# =====================================================================
# [v4.0.3 — Fase 4A] Indicadores ODS brutos por campus
# =====================================================================
def _ler_area_atual_por_campus():
    """Retorna dict {rotulo_campus: area_total_m2} para o ano mais recente
    da aba 'Área Manutenção'. Se a aba não existir, retorna {}."""
    try:
        aba = doc.worksheet("Área Manutenção")
        valores = aba.get_all_values()
    except Exception:
        return {}
    if not valores or len(valores) < 2:
        return {}
    # Estrutura simples: Ano | Área Construída m² | Área Total m²
    # Caso a planilha tenha colunas por campus, é adaptada aqui no futuro.
    # Por enquanto retorna {} (= densidade fica 0 para todos os campi).
    return {}


def calcular_indicadores_ods_por_campus(dados_linhas):
    """[v4.0.3] Calcula indicadores brutos por campus para painel ODS.

    Grava aba INDICADORES_ODS com 10 indicadores por campus. O HTML lê
    estes valores junto com PESOS_ODS para compor os índices ODS 9/11/12.
    Esta função NÃO aplica pesos — só agrega valores brutos.
    """
    if not dados_linhas:
        print("[ODS] Sem dados para calcular indicadores. Pulando.")
        return

    PADROES_INFRA_CRITICA = [
        'eletric', 'elétric', 'hidraulic', 'hidráulic', 'estrutural',
        'incendio', 'incêndio', 'gas', 'gás', 'cobertura', 'telhado',
        'curto', 'vazamento'
    ]
    PADROES_ESPACO_COLETIVO = [
        'sala de aula', 'laboratório', 'laboratorio', 'biblioteca',
        'auditório', 'auditorio', 'banheiro coletivo', 'cantina',
        'estacionamento', 'corredor'
    ]
    SLA_DIAS = {'Alta': 3, 'Média': 7, 'Media': 7, 'Baixa': 15}

    # Agrupa por campus
    campuses = sorted({
        (l[COL_CAMPUS] or '').strip()
        for l in dados_linhas
        if len(l) > COL_CAMPUS and (l[COL_CAMPUS] or '').strip()
    })
    if not campuses:
        print("[ODS] Nenhum campus identificado. Pulando.")
        return

    area_por_campus = _ler_area_atual_por_campus()

    cabecalho = [
        'Campus',
        'N_chamados_total',
        'N_infra_critica',
        'Tempo_medio_resolucao_dias',
        'Taxa_resolucao_no_prazo',
        'N_criticos_alta',
        'N_em_espaco_coletivo',
        'Densidade_chamados_por_1000m2',
        'Razao_preventiva_corretiva',
        'Valor_total_gasto_R$',
        'N_chamados_repetidos'
    ]
    linhas_saida = [cabecalho]

    for campus in campuses:
        chamados_c = [
            l for l in dados_linhas
            if len(l) > COL_CAMPUS and (l[COL_CAMPUS] or '').strip() == campus
        ]
        n_total = len(chamados_c)

        # Infra crítica (heurística textual em COL_CAT_IA)
        n_infra = sum(
            1 for l in chamados_c
            if len(l) > COL_CAT_IA
            and any(p in (l[COL_CAT_IA] or '').lower() for p in PADROES_INFRA_CRITICA)
        )

        # Tempo médio resolução + taxa no prazo (depende de COL_DATA_CONCLUSAO)
        tempo_medio = None
        taxa_prazo = None
        if COL_DATA_CONCLUSAO is not None:
            tempos = []
            no_prazo = 0
            n_concluidos = 0
            for l in chamados_c:
                if len(l) <= max(COL_DATA_ABERTURA, COL_DATA_CONCLUSAO):
                    continue
                try:
                    dt_ab = pd.to_datetime(l[COL_DATA_ABERTURA], dayfirst=True, errors='coerce')
                    dt_cc = pd.to_datetime(l[COL_DATA_CONCLUSAO], dayfirst=True, errors='coerce')
                except Exception:
                    continue
                if pd.isna(dt_ab) or pd.isna(dt_cc) or dt_cc < dt_ab:
                    continue
                dias = (dt_cc - dt_ab).days
                tempos.append(dias)
                n_concluidos += 1
                crit = ''
                if len(l) > COL_CRITICIDADE_OUT:
                    crit = (l[COL_CRITICIDADE_OUT] or '').strip()
                if dias <= SLA_DIAS.get(crit, 7):
                    no_prazo += 1
            if tempos:
                tempo_medio = sum(tempos) / len(tempos)
            if n_concluidos:
                taxa_prazo = no_prazo / n_concluidos

        # Críticos com criticidade Alta
        n_alta = sum(
            1 for l in chamados_c
            if len(l) > COL_CRITICIDADE_OUT
            and (l[COL_CRITICIDADE_OUT] or '').strip().lower() == 'alta'
        )

        # Espaço coletivo (heurística em COL_TITULO)
        n_coletivo = sum(
            1 for l in chamados_c
            if len(l) > COL_TITULO
            and any(p in (l[COL_TITULO] or '').lower() for p in PADROES_ESPACO_COLETIVO)
        )

        # Densidade por 1000 m² (depende da aba Área Manutenção)
        area_m2 = area_por_campus.get(campus, 0)
        densidade = (n_total / area_m2 * 1000) if area_m2 > 0 else 0.0

        # Razão preventiva/corretiva
        n_prev = sum(
            1 for l in chamados_c
            if len(l) > COL_CAT_IA and 'preventiv' in (l[COL_CAT_IA] or '').lower()
        )
        n_corr = sum(
            1 for l in chamados_c
            if len(l) > COL_CAT_IA and 'corretiv' in (l[COL_CAT_IA] or '').lower()
        )
        if n_corr > 0:
            razao_pc = n_prev / n_corr
        elif n_prev > 0:
            razao_pc = float(n_prev)
        else:
            razao_pc = 0.0

        # Valor total gasto (coluna Q)
        valor_total = 0.0
        for l in chamados_c:
            if len(l) > COL_VALOR:
                v = parse_valor_chamado(l[COL_VALOR])
                if v is not None:
                    valor_total += v

        # Chamados repetidos (depende de COL_LOCAL)
        n_repetidos = 0
        if COL_LOCAL is not None:
            contagem_local = {}
            for l in chamados_c:
                if len(l) > COL_LOCAL:
                    loc = (l[COL_LOCAL] or '').strip()
                    if loc:
                        contagem_local[loc] = contagem_local.get(loc, 0) + 1
            n_repetidos = sum(v - 1 for v in contagem_local.values() if v > 1)

        linhas_saida.append([
            campus,
            n_total,
            n_infra,
            round(tempo_medio, 2) if tempo_medio is not None else '',
            round(taxa_prazo, 3) if taxa_prazo is not None else '',
            n_alta,
            n_coletivo,
            round(densidade, 3),
            round(razao_pc, 3),
            round(valor_total, 2),
            n_repetidos
        ])

    # Grava na aba
    try:
        aba = obter_aba('INDICADORES_ODS', linhas=200, colunas=11, cabecalho=cabecalho)
        aba.clear()
        aba.update(values=linhas_saida, range_name='A1',
                   value_input_option='USER_ENTERED')
        print(f"[ODS] INDICADORES_ODS atualizada para {len(campuses)} campi.")
    except Exception as e:
        print(f"[ODS] Falha ao gravar INDICADORES_ODS: {e}")


def garantir_aba_pesos_ods():
    """[v4.0.3] Cria a aba PESOS_ODS com pesos-padrão na primeira execução.
    Se já existe, NÃO sobrescreve (preserva edições do usuário)."""
    try:
        doc.worksheet('PESOS_ODS')
        print("[ODS] Aba PESOS_ODS já existe — preservando edições do usuário.")
        return
    except WorksheetNotFound:
        pass
    except Exception as e:
        print(f"[ODS] Erro ao verificar PESOS_ODS: {e}")
        return

    cabecalho = ['Indicador', 'Sentido',
                 'ODS_9_Infraestrutura',
                 'ODS_11_Cidades_Sustentaveis',
                 'ODS_12_Consumo_Responsavel']
    linhas_padrao = [
        cabecalho,
        ['N_chamados_total',              'minimizar',  0.10, 0.10, 0.05],
        ['N_infra_critica',               'minimizar',  0.30, 0.10, 0.00],
        ['Tempo_medio_resolucao_dias',    'minimizar',  0.20, 0.05, 0.10],
        ['Taxa_resolucao_no_prazo',       'maximizar',  0.20, 0.10, 0.10],
        ['N_criticos_alta',               'minimizar',  0.10, 0.30, 0.05],
        ['N_em_espaco_coletivo',          'contextual', 0.05, 0.25, 0.05],
        ['Densidade_chamados_por_1000m2', 'minimizar',  0.00, 0.05, 0.05],
        ['Razao_preventiva_corretiva',    'maximizar',  0.05, 0.05, 0.30],
        ['Valor_total_gasto_R$',          'minimizar',  0.00, 0.00, 0.20],
        ['N_chamados_repetidos',          'minimizar',  0.00, 0.00, 0.10]
    ]
    try:
        aba = obter_aba('PESOS_ODS', linhas=50, colunas=5, cabecalho=cabecalho)
        aba.clear()
        aba.update(values=linhas_padrao, range_name='A1',
                   value_input_option='USER_ENTERED')
        print("[ODS] Aba PESOS_ODS criada com pesos padrão. Editável pelo usuário.")
    except Exception as e:
        print(f"[ODS] Falha ao criar PESOS_ODS: {e}")


# =====================================================================
# 10. MODO OPERACIONAL ODS
# =====================================================================

def _modo_ods():
    """[v4.0.4] Só indicadores ODS + aba PESOS_ODS."""
    try:
        todas_linhas = planilha.get_all_values()
    except APIError as e:
        print(f"[Modo ods] Falha: {e}"); return
    dados_op = todas_linhas[1:]
    try:
        print("[ODS] Calculando indicadores brutos por campus...")
        calcular_indicadores_ods_por_campus(dados_op)
        garantir_aba_pesos_ods()
    except Exception as e:
        print(f"[Modo ods] Falha: {e}")



# =====================================================================
# ENTRY POINT
# =====================================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Motor Malha IA — módulo ODS (v4.0.8)"
    )
    parser.add_argument(
        "--apenas-ods",
        action="store_true",
        help="Executa APENAS o pipeline de indicadores ODS por campus."
    )
    args = parser.parse_args()

    if args.apenas_ods:
        _modo_ods()
    else:
        print("[motor_ods] Nenhum modo ativo. Use --apenas-ods para executar.")

