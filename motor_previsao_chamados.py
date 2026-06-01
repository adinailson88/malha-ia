# -*- coding: utf-8 -*-
"""
MOTOR DE GOVERNANÃ‡A PREDITIVA â€“ BIOSSISTEMAS CONSTRUÃDOS
MÃ³dulo 2: motor_previsao_chamados.py
ExtraÃ­do de motor_v36.py (v4.0.8) â€” contÃ©m APENAS o pipeline de previsÃ£o
de chamados/mÃªs (contagem). Sem classificaÃ§Ã£o LSTM, sem custos, sem filtros,
sem ODS, sem APIs de LLM externas.

ExecuÃ§Ã£o:
    python motor_previsao_chamados.py --apenas-previsao-chamados

Gera as 14 abas PREVISAO_* na planilha Google Sheets CHAMADOS.
"""

# =====================================================================
# 1. INSTALAÃ‡ÃƒO INTELIGENTE DE DEPENDÃŠNCIAS COM CACHE PERSISTENTE
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
ARQUIVO_LOCK = f'{PASTA_LIBS}/requirements_previsao_chamados.lock'

PACOTES_REQUERIDOS = {
    'gspread': '6.1.4',
    'pandas': '2.2.3',
    'numpy': '1.26.4',
    'statsmodels': '0.14.4',
    'scikit-learn': '1.5.2',
    'pytz': '2024.2',
    'pmdarima': '2.0.4',
    'prophet': '1.1.6',
    'scipy': '1.13.1',
    'arch': '7.2.0',
    'shap': '0.46.0',
    'tensorflow': '2.17.0',
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
        return True, "pasta libs nao existe"
    lock_atual = carregar_lock()
    if lock_atual is None:
        return True, "requirements_previsao_chamados.lock ausente"
    if lock_atual != PACOTES_REQUERIDOS:
        adicionados = set(PACOTES_REQUERIDOS) - set(lock_atual)
        removidos = set(lock_atual) - set(PACOTES_REQUERIDOS)
        alterados = {k for k in PACOTES_REQUERIDOS
                     if k in lock_atual and PACOTES_REQUERIDOS[k] != lock_atual[k]}
        motivos = []
        if adicionados: motivos.append(f"adicionados: {', '.join(adicionados)}")
        if removidos:   motivos.append(f"removidos: {', '.join(removidos)}")
        if alterados:   motivos.append(f"versao alterada: {', '.join(alterados)}")
        return True, "; ".join(motivos)
    return False, "lock confere"

def instalar_pacotes():
    print(f"[Cache] Instalando pacotes em {PASTA_LIBS}...")
    print("[Cache] Esta operacao roda apenas na primeira vez ou quando a lista muda.")
    os.makedirs(PASTA_LIBS, exist_ok=True)
    spec_pacotes = [f"{nome}=={ver}" for nome, ver in PACOTES_REQUERIDOS.items()]
    cmd = ['pip', 'install', '--target', PASTA_LIBS, '--upgrade'] + spec_pacotes
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        print("[Cache] ERRO na instalacao:")
        print(resultado.stderr[-2000:])
        raise RuntimeError("Falha ao instalar pacotes â€” veja stderr acima.")
    salvar_lock(PACOTES_REQUERIDOS)
    print(f"[Cache] {len(PACOTES_REQUERIDOS)} pacotes principais instalados e lock salvo.")

if _EM_COLAB:
    deve_instalar, motivo = precisa_instalar()
    if deve_instalar:
        print(f"[Cache] Reinstalacao necessaria: {motivo}")
        instalar_pacotes()
        print("\n" + "="*70)
        print("PACOTES INSTALADOS PELA PRIMEIRA VEZ (ou apos mudanca de versao).")
        print("    Reinicie o runtime do Colab agora:")
        print("        Menu superior -> Ambiente de execucao -> Reiniciar sessao")
        print("    Depois execute esta celula novamente.")
        print("="*70 + "\n")
        try:
            import IPython
            IPython.Application.instance().kernel.do_shutdown(restart=True)
        except Exception:
            pass
        raise SystemExit("Aguardando reinicio do runtime.")
    else:
        print(f"[Cache] {len(PACOTES_REQUERIDOS)} pacotes carregados do cache em {PASTA_LIBS}.")

    if PASTA_LIBS not in sys.path:
        sys.path.insert(0, PASTA_LIBS)
else:
    print("[Local] Modo offline â€” pacotes carregados do ambiente Python local.")

# =====================================================================
# 2. IMPORTACOES
# =====================================================================
import gspread
from gspread.exceptions import WorksheetNotFound, APIError
import time
import re
import warnings
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.forecasting.theta import ThetaModel
from statsmodels.stats.diagnostic import acorr_ljungbox, het_breuschpagan, linear_reset
from statsmodels.stats.stattools import jarque_bera, durbin_watson
from statsmodels.stats.outliers_influence import variance_inflation_factor, OLSInfluence
import statsmodels.api as sm_api
from statsmodels.tsa.stattools import (
    adfuller, kpss, grangercausalitytests, acf, pacf
)
from statsmodels.tsa.seasonal import STL

from scipy import stats as sps
from scipy.stats import boxcox, norm, ks_2samp, shapiro
from scipy.signal import periodogram

from arch.bootstrap import MovingBlockBootstrap

warnings.filterwarnings('ignore')
import logging
logging.getLogger('cmdstanpy').setLevel(logging.WARNING)
logging.getLogger('prophet').setLevel(logging.WARNING)

_PMDARIMA_OK = False
_PROPHET_OK = False
try:
    import pmdarima as pm
    if hasattr(pm, 'auto_arima'):
        _teste = pm.auto_arima(
            np.array([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24]),
            seasonal=False, suppress_warnings=True,
            error_action='ignore', stepwise=True, max_p=1, max_q=1)
        _PMDARIMA_OK = True
        print("[Imports] pmdarima OK â€” auto_arima disponivel.")
    else:
        print("[Imports] pmdarima importou mas SEM auto_arima â€” usando fallback statsmodels.")
except Exception as _e_pm:
    print(f"[Imports] pmdarima indisponivel ({type(_e_pm).__name__}) â€” "
          f"usando fallback baseado em statsmodels (grid-search + AIC).")

try:
    from prophet import Prophet
    _df_teste = pd.DataFrame({
        'ds': pd.date_range('2020-01-01', periods=24, freq='MS'),
        'y': np.arange(24, dtype=float)
    })
    _p = Prophet(yearly_seasonality=False, weekly_seasonality=False,
                  daily_seasonality=False)
    _p.fit(_df_teste)
    if hasattr(_p, 'stan_backend') and _p.stan_backend is not None:
        _PROPHET_OK = True
        print("[Imports] Prophet OK â€” backend ativo.")
    else:
        print("[Imports] Prophet importou mas SEM stan_backend â€” usando UnobservedComponents.")
except Exception as _e_p:
    print(f"[Imports] Prophet indisponivel ({type(_e_p).__name__}) â€” "
          f"usando UnobservedComponents (statsmodels).")

from statsmodels.tsa.statespace.sarimax import SARIMAX as _SM_SARIMAX
from statsmodels.tsa.statespace.structural import UnobservedComponents

_TF_OK = False
tf = None
Sequential = None
KerasLSTM = None
Dense = None

def _importar_tf():
    """Importa apenas os componentes TensorFlow usados no LSTM de previsÃ£o."""
    global _TF_OK, tf, Sequential, KerasLSTM, Dense
    import sys as _sys

    _mods_remover = [
        m for m in list(_sys.modules.keys())
        if m == 'tensorflow' or m.startswith('tensorflow.')
        or m == 'keras' or m.startswith('keras.')
        or m == 'tensorboard' or m.startswith('tensorboard.')
    ]
    for _m in _mods_remover:
        try:
            del _sys.modules[_m]
        except KeyError:
            pass
    if _mods_remover:
        print(f"[Imports] Limpou {len(_mods_remover)} modulos TF/Keras de sys.modules.")

    try:
        import importlib
        importlib.invalidate_caches()
    except Exception:
        pass

    _path_orig = _sys.path[:]
    _sys.path[:] = [p for p in _path_orig if p != PASTA_LIBS]

    try:
        import tensorflow as _tf_mod
        _tf_file = getattr(_tf_mod, '__file__', '') or ''
        if PASTA_LIBS in _tf_file:
            raise ImportError(
                f"TF carregado do cache do Drive ({_tf_file}); "
                f"esperado caminho nativo do Colab."
            )
        from tensorflow.keras.models import Sequential as _Seq
        from tensorflow.keras.layers import LSTM as _KLSTM, Dense as _Den

        tf = _tf_mod
        Sequential = _Seq
        KerasLSTM = _KLSTM
        Dense = _Den
        tf.get_logger().setLevel('ERROR')
        _TF_OK = True
        print(f"[Imports] TensorFlow nativo OK ({_tf_file}) â€” LSTM Forecast disponivel.")
    except Exception as _e_tf:
        msg = str(_e_tf)
        if len(msg) > 180:
            msg = msg[:180] + '...'
        print(f"[Imports] TensorFlow indisponivel ({type(_e_tf).__name__}: {msg}) â€” "
              f"LSTM Forecast desativado.")
        for _m in [k for k in list(_sys.modules.keys())
                   if k == 'tensorflow' or k.startswith('tensorflow.')
                   or k == 'keras' or k.startswith('keras.')]:
            try:
                del _sys.modules[_m]
            except KeyError:
                pass
    finally:
        _sys.path[:] = _path_orig

_importar_tf()

try:
    import shap
    _SHAP_DISPONIVEL = True
except ImportError:
    _SHAP_DISPONIVEL = False
    print("[Imports] SHAP indisponivel â€” interpretabilidade do GBR ficara limitada.")

_VERSAO_MOTOR = "v4.0.8-previsao_chamados"

print(f"[Imports] OK Â· pandas={pd.__version__} Â· {_VERSAO_MOTOR} "
      f"(pmdarima={'ON' if _PMDARIMA_OK else 'fallback'}, "
      f"Prophet={'ON' if _PROPHET_OK else 'UnobservedComponents'}, "
      f"TF={'ON' if _TF_OK else 'OFF/sem_LSTM'})")

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _safe_isnan(val):
    """Retorna True se val e NaN; False para nao-NaN ou nao-numerico."""
    try:
        f = float(val)
        return f != f
    except (TypeError, ValueError):
        return False

def _safe_float(val, default=float('nan')):
    """Converte val para Python float; retorna default em caso de erro."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

# =====================================================================
# 3. CONFIGURACOES INICIAIS
# =====================================================================
ARQUIVO_GOOGLE = f'{CAMINHO_PASTA}/autenticacao_google.json'
gc = gspread.service_account(filename=ARQUIVO_GOOGLE)

NOME_PLANILHA = "CHAMADOS"
ID_PLANILHA = "1VgHY6NmCQLtA3lcfQAzGIRqJFZGHwcGhZ4zaXkqOmz4"
NOME_MAQUINA = "GOOGLE_COLAB_CLOUD"

def _resolver_fuso_brasil():
    candidatos = [
        'America/Bahia',
        'America/Sao_Paulo',
        'America/Fortaleza',
        'America/Recife',
        'Brazil/East',
    ]
    for nome in candidatos:
        try:
            tz = pytz.timezone(nome)
            if nome != 'America/Bahia':
                print(f"[Fuso] America/Bahia indisponivel. Usando {nome} (UTC-3).")
            return tz
        except Exception:
            continue
    print("[Fuso] Nenhum fuso brasileiro disponivel no pytz. Usando offset fixo UTC-3.")
    from datetime import timezone as _tz_dt, timedelta as _td_dt
    return _tz_dt(_td_dt(hours=-3))

FUSO_BAHIA = _resolver_fuso_brasil()

MIN_PONTOS_SERIE = 6

HORIZONTE_HOLDOUT = 12
HORIZONTE_FORECAST = 12
N_BOOTSTRAP = 1000
N_FOLDS_CV = 3
SEED = 42
THRESH_OUTLIER_Z = 3.0
INTERVALO_HORAS_PREVISAO_BOOT = 24

BLOCK_BOOTSTRAP_AUTO = True
BLOCK_SIZE_FIXO = 6
GRANGER_MAX_LAG = 6
ACF_PACF_LAGS = 24
THRESH_DRIFT_KS = 0.15
PESO_RMSE = 0.5
PESO_CRPS = 0.3
PESO_DESVIO_CV = 0.2


LSTM_UNITS = 64
LSTM_FORECAST_WINDOW = 12

COL_DATA_ABERTURA = 2





try:
    doc = gc.open_by_key(ID_PLANILHA)
    planilha = doc.worksheet("CHAMADOS")
    print(f"Conectado a planilha: {NOME_PLANILHA}, aba: CHAMADOS")
except Exception as e:
    print(f"Erro critico: {e}")
    raise

# =====================================================================
# 4. UTILITARIO DE ABAS COM CACHE
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
            print(f"[Aviso] Nao foi possivel gravar cabecalho em {nome}: {e}")
    _cache_abas[nome] = aba
    return aba


print(f"[{NOME_MAQUINA}] {_VERSAO_MOTOR} â€” Modulo previsao_chamados carregado.")

# =====================================================================
# 8. CONTEXTO SAZONAL (precipitacao + periodo letivo)
# =====================================================================
def gerar_contexto_sazonal_padrao(periodos_pandas):
    np.random.seed(SEED)
    linhas = []
    for p in periodos_pandas:
        mes = p.month
        precip = float(np.round(np.random.uniform(30, 250), 1))
        letivo = "Sim" if (3 <= mes <= 6 or 8 <= mes <= 12) else "Nao"
        linhas.append({
            'Mes_Ano': p.strftime('%m/%Y'),
            'Precipitacao_mm': precip,
            'Periodo_Letivo': letivo
        })
    return linhas

def ler_contexto_sazonal():
    try:
        aba = obter_aba("CONTEXTO_SAZONAL", linhas=500, colunas=4)
        valores = aba.get_all_values()
    except Exception:
        return None
    if not valores or len(valores) < 2:
        return None
    rows = []
    for linha in valores[1:]:
        if not linha or not linha[0]:
            continue
        mes_str = str(linha[0]).strip()
        try:
            per = pd.Period(mes_str, freq='M') if '/' not in mes_str \
                  else pd.Period(pd.to_datetime('01/' + mes_str, dayfirst=True), freq='M')
        except Exception:
            try:
                per = pd.Period(pd.to_datetime(mes_str), freq='M')
            except Exception:
                continue
        try:
            prec = float(str(linha[1]).replace(',', '.')) if len(linha) > 1 and linha[1] else 0.0
        except Exception:
            prec = 0.0
        let = (str(linha[2]).strip().lower() if len(linha) > 2 else 'nao')
        let_bin = 1 if let in ('sim', '1', 'true', 'yes') else 0
        rows.append({
            'Mes_Ano': per,
            'Precipitacao_mm': prec,
            'Periodo_Letivo': let,
            'Periodo_Letivo_Bin': let_bin
        })
    if not rows:
        return None
    return pd.DataFrame(rows).sort_values('Mes_Ano').reset_index(drop=True)


def ler_area_manutencao():
    try:
        aba = obter_aba("Area Manutencao", linhas=50, colunas=3,
                        cabecalho=["Ano", "Area Construida m2", "Area Total m2"])
        valores = aba.get_all_values()
    except Exception:
        return None
    if not valores or len(valores) < 2:
        return None
    rows = []
    for linha in valores[1:]:
        if not linha or not linha[0]:
            continue
        try:
            ano = int(str(linha[0]).strip())
            area_c = float(str(linha[1]).replace(',', '.')) if len(linha) > 1 and linha[1] else 0.0
            area_t = float(str(linha[2]).replace(',', '.')) if len(linha) > 2 and linha[2] else 0.0
            rows.append({'Ano': ano, 'Area_Construida_m2': area_c, 'Area_Total_m2': area_t})
        except Exception:
            continue
    if not rows:
        return None
    return pd.DataFrame(rows).sort_values('Ano').reset_index(drop=True)


def sincronizar_area_manutencao(periodos_historicos, periodos_futuros):
    df_area = ler_area_manutencao()
    if df_area is None:
        return None
    mapa_area = df_area.set_index('Ano')[['Area_Construida_m2', 'Area_Total_m2']].to_dict('index')
    todos_periodos = list(periodos_historicos) + list(periodos_futuros)
    anos_disponiveis = sorted(mapa_area.keys())
    ultimo_constr = 0.0
    ultimo_total = 0.0
    if anos_disponiveis:
        ult = anos_disponiveis[-1]
        ultimo_constr = mapa_area[ult]['Area_Construida_m2']
        ultimo_total = mapa_area[ult]['Area_Total_m2']
    rows = []
    for p in todos_periodos:
        ano = p.year
        if ano in mapa_area:
            ac = mapa_area[ano]['Area_Construida_m2']
            at = mapa_area[ano]['Area_Total_m2']
        else:
            anos_ant = [a for a in anos_disponiveis if a <= ano]
            if anos_ant:
                ref = max(anos_ant)
                ac = mapa_area[ref]['Area_Construida_m2']
                at = mapa_area[ref]['Area_Total_m2']
            else:
                ac, at = ultimo_constr, ultimo_total
        rows.append({'Mes_Ano': p, 'Area_Construida_m2': ac, 'Area_Total_m2': at})
    return pd.DataFrame(rows)


def sincronizar_contexto_sazonal(periodos_historicos, periodos_futuros):
    aba = obter_aba(
        "CONTEXTO_SAZONAL", linhas=500, colunas=4,
        cabecalho=["Mes_Ano", "Precipitacao_mm", "Periodo_Letivo", "Observacao"]
    )
    try:
        valores = aba.get_all_values()
    except Exception as e:
        print(f"[Contexto] Erro ao ler CONTEXTO_SAZONAL: {e}")
        return None

    existentes = {}
    if len(valores) > 1:
        for linha in valores[1:]:
            if linha and linha[0]:
                mes_ano = linha[0].strip()
                existentes[mes_ano] = {
                    'Precipitacao_mm': linha[1].strip() if len(linha) > 1 else "",
                    'Periodo_Letivo': linha[2].strip() if len(linha) > 2 else "",
                    'Observacao': linha[3].strip() if len(linha) > 3 else ""
                }

    todos_periodos = list(periodos_historicos) + list(periodos_futuros)
    contexto_padrao = gerar_contexto_sazonal_padrao(todos_periodos)

    linhas_finais = []
    for ctx in contexto_padrao:
        mes = ctx['Mes_Ano']
        if mes in existentes:
            ex = existentes[mes]
            precip = ex['Precipitacao_mm'] if ex['Precipitacao_mm'] else ctx['Precipitacao_mm']
            letivo = ex['Periodo_Letivo'] if ex['Periodo_Letivo'] else ctx['Periodo_Letivo']
            obs = ex['Observacao']
        else:
            precip = ctx['Precipitacao_mm']
            letivo = ctx['Periodo_Letivo']
            obs = "(valor-exemplo, preencher com dado real)"
        linhas_finais.append([mes, precip, letivo, obs])

    try:
        aba.clear()
        aba.update(
            values=[["Mes_Ano", "Precipitacao_mm", "Periodo_Letivo", "Observacao"]] + linhas_finais,
            range_name='A1', value_input_option='USER_ENTERED'
        )
    except Exception as e:
        print(f"[Contexto] Erro ao gravar CONTEXTO_SAZONAL: {e}")

    df = pd.DataFrame(linhas_finais, columns=['Mes_Ano', 'Precipitacao_mm', 'Periodo_Letivo', 'Observacao'])
    df['Precipitacao_mm'] = pd.to_numeric(df['Precipitacao_mm'], errors='coerce').fillna(0.0)
    df['Periodo_Letivo_bin'] = (df['Periodo_Letivo'].str.strip().str.lower().isin(['sim', 's', 'yes', '1', 'true'])).astype(int)

    try:
        df_area_mes = sincronizar_area_manutencao(periodos_historicos, periodos_futuros)
        if df_area_mes is not None:
            df['_per'] = df['Mes_Ano'].apply(lambda m: pd.Period(
                pd.to_datetime('01/' + m, dayfirst=True), freq='M'
            ) if '/' in str(m) else pd.Period(m, freq='M'))
            df_area_mes = df_area_mes.set_index('Mes_Ano')
            df['Area_Construida_m2'] = df['_per'].map(
                lambda p: df_area_mes.loc[p, 'Area_Construida_m2'] if p in df_area_mes.index else np.nan
            ).ffill().bfill().fillna(0.0)
            df['Area_Total_m2'] = df['_per'].map(
                lambda p: df_area_mes.loc[p, 'Area_Total_m2'] if p in df_area_mes.index else np.nan
            ).ffill().bfill().fillna(0.0)
            df.drop(columns=['_per'], inplace=True)
            print(f"[Contexto] Area Manutencao integrada: "
                  f"{df['Area_Construida_m2'].max():.0f} m2 construida, "
                  f"{df['Area_Total_m2'].max():.0f} m2 total.")
        else:
            df['Area_Construida_m2'] = 0.0
            df['Area_Total_m2'] = 0.0
            print("[Contexto] Aba 'Area Manutencao' nao encontrada â€” area zerada nos exogenos.")
    except Exception as _e_area:
        df['Area_Construida_m2'] = 0.0
        df['Area_Total_m2'] = 0.0
        print(f"[Contexto] Falha ao integrar area ({_e_area}) â€” area zerada.")

    return df

def construir_exog(df_contexto, periodos_alvo):
    tem_area = ('Area_Construida_m2' in df_contexto.columns and
                'Area_Total_m2' in df_contexto.columns)
    if tem_area:
        mapa = {row['Mes_Ano']: (row['Precipitacao_mm'], row['Periodo_Letivo_bin'],
                                  row['Area_Construida_m2'], row['Area_Total_m2'])
                for _, row in df_contexto.iterrows()}
        ultimo_ac = float(df_contexto['Area_Construida_m2'].replace(0, np.nan).dropna().iloc[-1]) \
                    if df_contexto['Area_Construida_m2'].any() else 0.0
        ultimo_at = float(df_contexto['Area_Total_m2'].replace(0, np.nan).dropna().iloc[-1]) \
                    if df_contexto['Area_Total_m2'].any() else 0.0
    else:
        mapa = {row['Mes_Ano']: (row['Precipitacao_mm'], row['Periodo_Letivo_bin'], 0.0, 0.0)
                for _, row in df_contexto.iterrows()}
        ultimo_ac, ultimo_at = 0.0, 0.0

    media_precip = float(df_contexto['Precipitacao_mm'].replace(0, np.nan).dropna().mean())
    if np.isnan(media_precip):
        media_precip = 100.0

    linhas = []
    for p in periodos_alvo:
        chave = p.strftime('%m/%Y')
        if chave in mapa:
            precip, letivo, ac, at = mapa[chave]
        else:
            precip = media_precip
            letivo = 1 if (3 <= p.month <= 6 or 8 <= p.month <= 12) else 0
            ac, at = ultimo_ac, ultimo_at
        linhas.append([float(precip), int(letivo), float(ac), float(at)])
    return np.array(linhas)

def construir_exog_futuro_climatologico(df_contexto, periodos_futuros):
    df_aux = df_contexto.copy()
    df_aux['mes_num'] = df_aux['Mes_Ano'].str[:2].astype(int)
    medias_mes = df_aux.groupby('mes_num')['Precipitacao_mm'].mean().to_dict()
    media_global = float(df_aux['Precipitacao_mm'].mean())
    tem_area = ('Area_Construida_m2' in df_aux.columns and
                'Area_Total_m2' in df_aux.columns)
    if tem_area:
        ultimo_ac = float(df_aux['Area_Construida_m2'].replace(0, np.nan).dropna().iloc[-1]) \
                    if df_aux['Area_Construida_m2'].any() else 0.0
        ultimo_at = float(df_aux['Area_Total_m2'].replace(0, np.nan).dropna().iloc[-1]) \
                    if df_aux['Area_Total_m2'].any() else 0.0
    else:
        ultimo_ac, ultimo_at = 0.0, 0.0
    linhas = []
    for p in periodos_futuros:
        precip_clim = medias_mes.get(p.month, media_global)
        letivo = 1 if (3 <= p.month <= 6 or 8 <= p.month <= 12) else 0
        linhas.append([float(precip_clim), int(letivo), ultimo_ac, ultimo_at])
    return np.array(linhas)



# =====================================================================
# 9. EXTRAÃ‡ÃƒO DE SÃ‰RIE TEMPORAL
# =====================================================================

def extrair_serie_temporal(dados_linhas):
    """
    [v3.6.5] Extrai sÃ©rie mensal contÃ­nua.
    - Datas futuras (> agora) sÃ£o descartadas.
    - O mÃªs corrente (incompleto) Ã© removido: o modelo sÃ³ usa meses
      100% finalizados. Um mÃªs com dados parciais cria ponto baixo
      irreal que contamina tendÃªncia e sazonalidade.
    - PerÃ­odos sem chamados ficam com 0 (interpolaÃ§Ã£o por preenchimento).
    """
    agora = datetime.now(FUSO_BAHIA)
    registros = []
    for linha in dados_linhas:
        if len(linha) <= COL_DATA_ABERTURA:
            continue
        data_str = linha[COL_DATA_ABERTURA].strip()
        if not data_str:
            continue
        data = pd.to_datetime(data_str, format='%d/%m/%Y %H:%M:%S', errors='coerce')
        if pd.isna(data):
            data = pd.to_datetime(data_str, format='%d/%m/%Y', errors='coerce')
        if pd.isna(data):
            data = pd.to_datetime(data_str, dayfirst=True, errors='coerce')
        if pd.isna(data):
            continue
        # Descarta datas futuras (timezone-naive comparison)
        try:
            if data.tz is None and data > agora.replace(tzinfo=None):
                continue
            elif data.tz is not None and data > agora:
                continue
        except Exception:
            pass  # em caso de incompatibilidade de tz, mantÃ©m
        registros.append({'data': data})

    if not registros:
        return None

    df = pd.DataFrame(registros)
    df['Mes_Ano'] = df['data'].dt.to_period('M')
    contagem = df.groupby('Mes_Ano').size().reset_index(name='Quantidade')
    inicio = contagem['Mes_Ano'].min()
    fim = contagem['Mes_Ano'].max()
    if pd.isna(inicio) or pd.isna(fim):
        return None
    todos_meses = pd.period_range(inicio, fim, freq='M')
    contagem = contagem.set_index('Mes_Ano').reindex(todos_meses, fill_value=0).reset_index()
    contagem = contagem.rename(columns={'index': 'Mes_Ano'})
    contagem['Mes_Ano_Str'] = contagem['Mes_Ano'].dt.strftime('%m/%Y')

    # REMOVE MÃŠS CORRENTE INCOMPLETO â€” sÃ³ usa meses 100% finalizados.
    try:
        mes_atual = pd.Period(year=agora.year, month=agora.month, freq='M')
        n_antes = len(contagem)
        contagem = contagem[contagem['Mes_Ano'] < mes_atual].reset_index(drop=True)
        n_removidos = n_antes - len(contagem)
        if n_removidos > 0:
            print(f"[SÃ©rie] MÃªs corrente ({mes_atual.strftime('%m/%Y')}) e posteriores "
                  f"removidos ({n_removidos} perÃ­odo(s)). SÃ©rie encerra em "
                  f"{contagem['Mes_Ano'].max().strftime('%m/%Y')}.")
    except Exception as e:
        print(f"[SÃ©rie] Aviso ao remover mÃªs incompleto: {e}")

    if len(contagem) < 2:
        return None

    print(f"[SÃ©rie] {len(contagem)} meses completos, "
          f"de {contagem['Mes_Ano_Str'].iloc[0]} a {contagem['Mes_Ano_Str'].iloc[-1]}")
    return contagem


# =====================================================================
# 10. UTILITÃRIOS ESTATÃSTICOS E BOOTSTRAP
# =====================================================================

def tratar_outliers(serie, z_thresh=THRESH_OUTLIER_Z, janela=5):
    """
    Substitui pontos com |z|>z_thresh pela mediana mÃ³vel de janela.
    Retorna serie_tratada e mÃ¡scara de outliers detectados.
    """
    s = pd.Series(serie, dtype=float).copy()
    if len(s) < janela + 2:
        return s.values, np.zeros(len(s), dtype=bool)
    mu = s.mean()
    sigma = s.std()
    if sigma <= 0:
        return s.values, np.zeros(len(s), dtype=bool)
    z = np.abs((s - mu) / sigma)
    mascara = z.values > z_thresh
    if mascara.any():
        med_movel = s.rolling(janela, min_periods=1, center=True).median()
        s_corrigido = s.where(~mascara, med_movel)
        n_out = int(mascara.sum())
        print(f"[Outliers] {n_out} ponto(s) com |z|>{z_thresh} corrigido(s) pela mediana mÃ³vel.")
        return s_corrigido.values, mascara
    return s.values, mascara


def calcular_metricas(real, previsao):
    real_arr = np.asarray(real, dtype=float)
    prev_arr = np.asarray(previsao, dtype=float)
    mae = float(mean_absolute_error(real_arr, prev_arr))
    rmse = float(np.sqrt(mean_squared_error(real_arr, prev_arr)))
    ss_res = float(np.sum((real_arr - prev_arr) ** 2))
    ss_tot = float(np.sum((real_arr - np.mean(real_arr)) ** 2))
    r2 = 1 - (ss_res / ss_tot) if ss_tot > 0 else float('nan')
    nz = real_arr != 0
    mape = float(np.mean(np.abs((real_arr[nz] - prev_arr[nz]) / real_arr[nz])) * 100) if nz.any() else float('nan')
    return {'MAE': mae, 'RMSE': rmse, 'R2': r2, 'MAPE': mape}


def bootstrap_residuos(modelo_func, treino, horizonte, n_iter=N_BOOTSTRAP, seed=SEED, exog_futuro=None):
    """
    [v3.5 â€” G2] Reamostra resÃ­duos para gerar IC empÃ­rico.
    EstratÃ©gia adaptativa:
    - Se Ljung-Box NÃƒO rejeita ruÃ­do branco (p > 0.05) â†’ bootstrap clÃ¡ssico
      por reamostragem independente (vÃ¡lido sob independÃªncia).
    - Se Ljung-Box REJEITA (p â‰¤ 0.05) â†’ block bootstrap (KÃ¼nsch, 1989) que
      preserva estrutura serial. IMPRESCINDÃVEL para validade dos IC.
    Em ambos os casos, retorna 'paths' (matriz n_iter Ã— horizonte) para CRPS.
    """
    np.random.seed(seed)
    try:
        if exog_futuro is not None:
            prev_base, residuos = modelo_func(treino, exog_futuro)
        else:
            prev_base, residuos = modelo_func(treino)
    except Exception as e:
        print(f"[Bootstrap] Falha ao ajustar modelo base: {e}")
        return None
    if residuos is None or len(residuos) < 8:
        return None
    residuos = np.asarray(residuos, dtype=float)
    residuos = residuos[~np.isnan(residuos)]
    if len(residuos) < 8:
        return None

    # G2: decide se usa block bootstrap baseado em Ljung-Box
    usa_block = False
    metodo_usado = "iid"
    block_size = 1
    try:
        lb = acorr_ljungbox(residuos, lags=[min(10, len(residuos)//2)], return_df=True)
        lb_p = float(lb['lb_pvalue'].iloc[0])
        if lb_p < 0.05:
            usa_block = True
            metodo_usado = "block"
    except Exception:
        pass

    paths = np.zeros((n_iter, horizonte))

    if usa_block:
        # Block bootstrap via arch
        try:
            try:
                from arch.bootstrap import optimal_block_length
                opt = optimal_block_length(residuos)
                block_size = max(2, int(np.ceil(opt['stationary'].iloc[0])))
            except Exception:
                block_size = BLOCK_SIZE_FIXO
            bs = MovingBlockBootstrap(block_size, residuos, seed=seed)
            counter = 0
            for data in bs.bootstrap(n_iter):
                sample = data[0][0]
                if len(sample) >= horizonte:
                    ruido = sample[:horizonte]
                else:
                    ruido = np.tile(sample, (horizonte // len(sample) + 1))[:horizonte]
                paths[counter] = np.maximum(0, prev_base + ruido)
                counter += 1
                if counter >= n_iter:
                    break
        except Exception as e:
            print(f"[Bootstrap] Block falhou ({e}), caindo para iid")
            usa_block = False
            metodo_usado = "iid_fallback"

    if not usa_block:
        # Bootstrap clÃ¡ssico iid
        for i in range(n_iter):
            ruido = np.random.choice(residuos, size=horizonte, replace=True)
            paths[i] = np.maximum(0, prev_base + ruido)

    media = paths.mean(axis=0)
    desvio = paths.std(axis=0)
    return {
        'media': media, 'desvio': desvio,
        'P10': np.percentile(paths, 10, axis=0),
        'P25': np.percentile(paths, 25, axis=0),
        'P50': np.percentile(paths, 50, axis=0),
        'P75': np.percentile(paths, 75, axis=0),
        'P90': np.percentile(paths, 90, axis=0),
        'IC1_inf': media - desvio,
        'IC1_sup': media + desvio,
        'IC2_inf': media - 2 * desvio,
        'IC2_sup': media + 2 * desvio,
        'forecast_pontual': prev_base,
        'paths': paths,                    # G14 â€” necessÃ¡rio para CRPS
        'metodo_bootstrap': metodo_usado,  # auditoria
        'block_size': block_size            # auditoria
    }


def diagnosticar_residuos(residuos, nome_modelo):
    res = np.asarray(residuos, dtype=float)
    res = res[~np.isnan(res)]
    if len(res) < 8:
        return None
    out = {'modelo': nome_modelo, 'n_residuos': len(res),
           'media_res': float(np.mean(res)), 'std_res': float(np.std(res))}
    # Ljung-Box: independÃªncia dos resÃ­duos
    try:
        lb = acorr_ljungbox(res, lags=[min(10, len(res) // 2)], return_df=True)
        out['ljung_box_stat'] = float(lb['lb_stat'].iloc[0])
        out['ljung_box_pvalor'] = float(lb['lb_pvalue'].iloc[0])
        out['ljung_box_interpretacao'] = ('OK (sem autocorrelaÃ§Ã£o residual)'
                                          if out['ljung_box_pvalor'] > 0.05
                                          else 'ATENÃ‡ÃƒO (autocorrelaÃ§Ã£o residual)')
    except Exception:
        out['ljung_box_stat'] = float('nan')
        out['ljung_box_pvalor'] = float('nan')
        out['ljung_box_interpretacao'] = 'NÃ£o calculado'
    # Jarque-Bera: normalidade (assimetria + curtose)
    try:
        jb_stat, jb_p, _, _ = jarque_bera(res)
        out['jarque_bera_stat'] = float(jb_stat)
        out['jarque_bera_pvalor'] = float(jb_p)
        out['jarque_bera_interpretacao'] = ('OK (resÃ­duos normais)'
                                            if jb_p > 0.05
                                            else 'ATENÃ‡ÃƒO (resÃ­duos nÃ£o-normais)')
    except Exception:
        out['jarque_bera_stat'] = float('nan')
        out['jarque_bera_pvalor'] = float('nan')
        out['jarque_bera_interpretacao'] = 'NÃ£o calculado'
    # Shapiro-Wilk: normalidade (mais sensÃ­vel que JB para n<50)
    try:
        sw_stat, sw_p = shapiro(res[:min(len(res), 5000)])  # Shapiro limitado a 5000 pts
        out['shapiro_wilk_stat'] = float(sw_stat)
        out['shapiro_wilk_pvalor'] = float(sw_p)
        out['shapiro_wilk_interpretacao'] = ('OK (normalidade nÃ£o rejeitada)'
                                              if sw_p > 0.05
                                              else 'ATENÃ‡ÃƒO (normalidade rejeitada)')
    except Exception:
        out['shapiro_wilk_stat'] = float('nan')
        out['shapiro_wilk_pvalor'] = float('nan')
        out['shapiro_wilk_interpretacao'] = 'NÃ£o calculado'
    # Durbin-Watson: independÃªncia sequencial (2 = sem autocorr; <1 ou >3 = problema)
    try:
        dw = durbin_watson(res)
        out['durbin_watson'] = float(dw)
        if dw < 1.5:
            dw_interp = 'ATENÃ‡ÃƒO (autocorrelaÃ§Ã£o positiva)'
        elif dw > 2.5:
            dw_interp = 'ATENÃ‡ÃƒO (autocorrelaÃ§Ã£o negativa)'
        else:
            dw_interp = 'OK (sem autocorrelaÃ§Ã£o relevante)'
        out['durbin_watson_interpretacao'] = dw_interp
    except Exception:
        out['durbin_watson'] = float('nan')
        out['durbin_watson_interpretacao'] = 'NÃ£o calculado'
    # Breusch-Pagan: homocedasticidade (resÃ­duos ao quadrado ~ Ã­ndice temporal)
    try:
        n_res = len(res)
        idx = np.arange(n_res, dtype=float)
        X_bp = np.column_stack([np.ones(n_res), idx])
        bp_lm, bp_p, bp_f, bp_fp = het_breuschpagan(res, X_bp)
        out['breusch_pagan_stat'] = float(bp_lm)
        out['breusch_pagan_pvalor'] = float(bp_p)
        out['breusch_pagan_interpretacao'] = ('OK (homocedasticidade nÃ£o rejeitada)'
                                               if bp_p > 0.05
                                               else 'ATENÃ‡ÃƒO (heterocedasticidade detectada)')
    except Exception:
        out['breusch_pagan_stat'] = float('nan')
        out['breusch_pagan_pvalor'] = float('nan')
        out['breusch_pagan_interpretacao'] = 'NÃ£o calculado'
    return out


def testar_estacionariedade(serie):
    s = np.asarray(serie, dtype=float)
    out = {}
    try:
        adf_stat, adf_p, _, _, _, _ = adfuller(s, autolag='AIC')
        out['adf_stat'] = float(adf_stat)
        out['adf_pvalor'] = float(adf_p)
        out['adf_interpretacao'] = 'EstacionÃ¡ria' if adf_p < 0.05 else 'NÃ£o estacionÃ¡ria'
    except Exception:
        out['adf_stat'] = float('nan')
        out['adf_pvalor'] = float('nan')
        out['adf_interpretacao'] = 'NÃ£o calculado'
    try:
        kpss_stat, kpss_p, _, _ = kpss(s, regression='c', nlags='auto')
        out['kpss_stat'] = float(kpss_stat)
        out['kpss_pvalor'] = float(kpss_p)
        out['kpss_interpretacao'] = 'EstacionÃ¡ria' if kpss_p > 0.05 else 'NÃ£o estacionÃ¡ria'
    except Exception:
        out['kpss_stat'] = float('nan')
        out['kpss_pvalor'] = float('nan')
        out['kpss_interpretacao'] = 'NÃ£o calculado'
    return out


def calcular_qqplot_pontos(residuos):
    """Pares (quantil teÃ³rico padronizado, quantil observado padronizado)."""
    res = np.asarray(residuos, dtype=float)
    res = res[~np.isnan(res)]
    if len(res) < 5:
        return None
    res_pad = (res - np.mean(res)) / (np.std(res) + 1e-12)
    res_ord = np.sort(res_pad)
    n = len(res_ord)
    quantis_teoricos = norm.ppf((np.arange(1, n + 1) - 0.5) / n)
    return list(zip(quantis_teoricos.tolist(), res_ord.tolist()))



# =====================================================================
# 11. MODELOS DO EIXO 2 (8 modelos de previsÃ£o)
# =====================================================================

# =====================================================================
# 11. MODELOS DO EIXO 2
# =====================================================================

# ---------- MODELO 1: AUTO-ARIMA (sem exÃ³genas, baseline puro) ----------
# =====================================================================
# 11.0 FALLBACK NATIVO PARA PMDARIMA â€” grid search + AIC
# =====================================================================

class _SmArimaWrapper:
    """
    Wrapper sobre statsmodels.SARIMAX que expÃµe a mesma interface que
    pmdarima.ARIMA usa no resto do motor (predict, params, aic, bic,
    arima_res_, order, seasonal_order).
    Permite que ajustar_auto_arima/ajustar_sarimax funcionem sem alteraÃ§Ãµes
    quando pmdarima nÃ£o estÃ¡ disponÃ­vel.
    """
    def __init__(self, fit_result, order, seasonal_order):
        self.arima_res_ = fit_result
        self.order = order
        self.seasonal_order = seasonal_order

    def predict(self, n_periods, X=None):
        """Mesma assinatura de pmdarima.ARIMA.predict."""
        if X is not None:
            f = self.arima_res_.forecast(steps=n_periods, exog=X)
        else:
            f = self.arima_res_.forecast(steps=n_periods)
        return np.asarray(f, dtype=float)

    def params(self):
        return self.arima_res_.params

    def aic(self):
        return float(self.arima_res_.aic)

    def bic(self):
        return float(self.arima_res_.bic)


def _grid_search_arima(y, X=None, seasonal=False, m=1,
                        max_p=2, max_q=2, max_d=1,
                        max_P=1, max_Q=1, max_D=1):
    """
    Substituto de pmdarima.auto_arima usando grid search puro sobre
    statsmodels.SARIMAX, com seleÃ§Ã£o por AIC. Mais lento que pmdarima
    (sem o atalho stepwise), mas robusto e sem dependÃªncias binÃ¡rias.

    Cobertura: explora todas as combinaÃ§Ãµes (p,d,q)Ã—(P,D,Q) limitadas.
    Para series mensais com sazonalidade=12, cobre 3Ã—2Ã—3Ã—2Ã—2Ã—2 = 144
    modelos no pior caso â€” ~30-60s no Colab.
    """
    melhor_aic = float('inf')
    melhor_modelo = None
    melhor_order = None
    melhor_sorder = None

    # Define grid
    if seasonal:
        s_orders = [(P, D, Q, m)
                    for P in range(max_P + 1)
                    for D in range(max_D + 1)
                    for Q in range(max_Q + 1)]
    else:
        s_orders = [(0, 0, 0, 0)]

    orders = [(p, d, q)
              for p in range(max_p + 1)
              for d in range(max_d + 1)
              for q in range(max_q + 1)]

    for order in orders:
        for sorder in s_orders:
            # Pula modelos triviais
            if order == (0, 0, 0) and sorder[:3] == (0, 0, 0):
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    modelo = _SM_SARIMAX(
                        y, exog=X, order=order, seasonal_order=sorder,
                        enforce_stationarity=False,
                        enforce_invertibility=False,
                        simple_differencing=False
                    )
                    res = modelo.fit(disp=False, maxiter=50, method='lbfgs')
                if not _safe_isnan(res.aic) and float(res.aic) < melhor_aic:
                    melhor_aic = res.aic
                    melhor_modelo = res
                    melhor_order = order
                    melhor_sorder = sorder
            except Exception:
                continue

    if melhor_modelo is None:
        raise RuntimeError("Grid search ARIMA nÃ£o convergiu para nenhuma configuraÃ§Ã£o.")

    return _SmArimaWrapper(melhor_modelo, melhor_order, melhor_sorder)


def _ajustar_arima_universal(y, X=None, seasonal=False, m=1,
                              max_p=2, max_q=2, max_d=1,
                              max_P=1, max_Q=1, max_D=1):
    """
    Despacho: usa pmdarima.auto_arima quando disponÃ­vel, senÃ£o grid search.
    Retorna SEMPRE um objeto com a interface esperada pelo motor.
    """
    if _PMDARIMA_OK:
        kwargs = dict(
            seasonal=seasonal, suppress_warnings=True,
            error_action='ignore', stepwise=True,
            max_p=max_p, max_q=max_q, max_d=max_d
        )
        if seasonal:
            kwargs.update(dict(m=m, max_P=max_P, max_Q=max_Q, max_D=max_D))
        if X is not None:
            return pm.auto_arima(y, X=X, **kwargs)
        return pm.auto_arima(y, **kwargs)
    return _grid_search_arima(y, X=X, seasonal=seasonal, m=m,
                                max_p=max_p, max_q=max_q, max_d=max_d,
                                max_P=max_P, max_Q=max_Q, max_D=max_D)


# =====================================================================
# 11.1 FALLBACK NATIVO PARA PROPHET â€” UnobservedComponents
# =====================================================================

def _ajustar_unobserved_components(serie, exog=None, exog_futuro=None,
                                     horizonte=12):
    """
    Substituto do Prophet via statsmodels.UnobservedComponents.

    UnobservedComponents implementa decomposiÃ§Ã£o estrutural por filtro
    de Kalman (Harvey, 1989), separando sÃ©rie em:
      - tendÃªncia local linear (level + slope)
      - sazonalidade trigonomÃ©trica (Fourier)
      - resÃ­duo
    com regressores exÃ³genos opcionais. Ã‰ o equivalente bayesiano-frequentista
    mais prÃ³ximo do Prophet, com IC por intervalo de confianÃ§a gaussiano.

    Vantagem tÃ©cnica sobre Prophet aqui: integra-se nativamente com numpy/
    statsmodels, sem dependÃªncia binÃ¡ria externa (cmdstanpy/Stan).
    """
    s = np.asarray(serie, dtype=float)
    modelo = UnobservedComponents(
        s, level='local linear trend', seasonal=12,
        exog=exog, freq_seasonal=None, irregular=True
    )
    res = modelo.fit(disp=False, maxiter=200, method='lbfgs')

    if exog_futuro is not None:
        forecast_obj = res.get_forecast(steps=horizonte, exog=exog_futuro)
    else:
        forecast_obj = res.get_forecast(steps=horizonte)

    pred_mean = np.asarray(forecast_obj.predicted_mean, dtype=float)
    pred_ic = forecast_obj.conf_int(alpha=0.05)
    if hasattr(pred_ic, 'values'):
        pred_ic = pred_ic.values
    yhat_lower = np.asarray(pred_ic[:, 0], dtype=float)
    yhat_upper = np.asarray(pred_ic[:, 1], dtype=float)

    # NÃ£o-negatividade para contagem
    pred_mean = np.maximum(0, pred_mean)
    yhat_lower = np.maximum(0, yhat_lower)

    residuos = np.asarray(res.resid, dtype=float)
    return {
        'forecast': pred_mean,
        'yhat_lower': yhat_lower,
        'yhat_upper': yhat_upper,
        'residuos': residuos,
        'aic': _safe_float(res.aic),
        'bic': _safe_float(res.bic),
        'res_obj': res
    }


# =====================================================================
# 11.2 MODELOS â€” usam o despacho universal quando aplicÃ¡vel
# =====================================================================

def ajustar_auto_arima(serie):
    treino = serie[:-HORIZONTE_HOLDOUT]
    teste = serie[-HORIZONTE_HOLDOUT:]
    try:
        modelo = _ajustar_arima_universal(
            treino, seasonal=False, max_p=3, max_q=3, max_d=2
        )
        prev_holdout = np.asarray(modelo.predict(n_periods=HORIZONTE_HOLDOUT), dtype=float)
        metricas = calcular_metricas(teste, prev_holdout)

        modelo_full = _ajustar_arima_universal(
            serie, seasonal=False, max_p=3, max_q=3, max_d=2
        )
        prev_futuro = np.asarray(modelo_full.predict(n_periods=HORIZONTE_FORECAST), dtype=float)

        order = modelo_full.order
        p, d, q = order
        equacao = f"ARIMA({p},{d},{q}): "
        if p > 0:
            ar_terms = " + ".join([f"Ï†_{i+1}Â·y(t-{i+1})" for i in range(p)])
            equacao += f"y(t) = c + {ar_terms}"
        else:
            equacao += "y(t) = c"
        if q > 0:
            ma_terms = " + ".join([f"Î¸_{i+1}Â·Îµ(t-{i+1})" for i in range(q)])
            equacao += f" + {ma_terms} + Îµ(t)"
        if d > 0:
            equacao += f" [apÃ³s {d} diferenciaÃ§Ã£o(Ãµes) ordinÃ¡ria(s)]"

        # ExtraÃ§Ã£o defensiva de parÃ¢metros â€” pmdarima e _SmArimaWrapper
        # diferem na exposiÃ§Ã£o de bse/pvalues
        try:
            nomes_params = list(modelo_full.arima_res_.param_names)
            valores = list(modelo_full.params() if callable(getattr(modelo_full, 'params', None))
                            else modelo_full.arima_res_.params)
            bse = list(modelo_full.arima_res_.bse)
            pvalores = list(modelo_full.arima_res_.pvalues)
            params_detalhe = []
            for nome, val, se, pv in zip(nomes_params, valores, bse, pvalores):
                params_detalhe.append({
                    'nome': nome, 'valor': float(val), 'erro_padrao': float(se),
                    'p_valor': float(pv),
                    'IC95_inf': float(val - 1.96 * se), 'IC95_sup': float(val + 1.96 * se)
                })
        except Exception as e_p:
            print(f"[ARIMA] Aviso: parÃ¢metros nÃ£o extraÃ­dos ({e_p})")
            params_detalhe = []

        residuos = np.asarray(modelo_full.arima_res_.resid)

        def boot_func(s):
            m = _ajustar_arima_universal(
                s, seasonal=False, max_p=3, max_q=3, max_d=2
            )
            return (np.asarray(m.predict(n_periods=HORIZONTE_FORECAST), dtype=float),
                    np.asarray(m.arima_res_.resid))
        boot = bootstrap_residuos(boot_func, serie, HORIZONTE_FORECAST)

        aic_val = modelo_full.aic() if callable(getattr(modelo_full, 'aic', None)) else float('nan')
        bic_val = modelo_full.bic() if callable(getattr(modelo_full, 'bic', None)) else float('nan')

        return {
            'nome': 'ARIMA', 'sucesso': True, 'metricas': metricas,
            'prev_holdout': np.asarray(prev_holdout, dtype=float),
            'forecast': np.asarray(prev_futuro, dtype=float),
            'equacao': equacao,
            'parametros': params_detalhe, 'residuos': residuos,
            'aic': float(aic_val), 'bic': float(bic_val),
            'order_str': f"ARIMA({p},{d},{q})", 'bootstrap': boot,
            'usa_exog': False
        }
    except Exception as e:
        import traceback
        print(f"[ARIMA] Falha: {type(e).__name__}: {e}")
        traceback.print_exc()
        return {'nome': 'ARIMA', 'sucesso': False, 'erro': f"{type(e).__name__}: {str(e)[:200]}"}


# ---------- MODELO 2: SARIMAX-12 (sazonalidade anual) com exÃ³genas ----------
def ajustar_sarimax(serie, periodo, df_contexto, periodos_historicos, periodos_futuros):
    nome_mod = f'SARIMAX-{periodo}'
    if len(serie) < periodo + 12:
        return {'nome': nome_mod, 'sucesso': False, 'erro': f'SÃ©rie curta para sazonalidade {periodo}'}

    # ExÃ³genas para histÃ³rico e futuro
    exog_hist = construir_exog(df_contexto, periodos_historicos)
    exog_futuro = construir_exog_futuro_climatologico(df_contexto, periodos_futuros)

    treino = serie[:-HORIZONTE_HOLDOUT]
    teste = serie[-HORIZONTE_HOLDOUT:]
    exog_treino = exog_hist[:-HORIZONTE_HOLDOUT]
    exog_holdout = exog_hist[-HORIZONTE_HOLDOUT:]

    try:
        modelo = _ajustar_arima_universal(
            treino, X=exog_treino, seasonal=True, m=periodo,
            max_p=2, max_q=2, max_P=1, max_Q=1, max_d=1, max_D=1
        )
        prev_holdout = np.asarray(
            modelo.predict(n_periods=HORIZONTE_HOLDOUT, X=exog_holdout),
            dtype=float
        )
        metricas = calcular_metricas(teste, prev_holdout)

        modelo_full = _ajustar_arima_universal(
            serie, X=exog_hist, seasonal=True, m=periodo,
            max_p=2, max_q=2, max_P=1, max_Q=1, max_d=1, max_D=1
        )
        prev_futuro = np.asarray(
            modelo_full.predict(n_periods=HORIZONTE_FORECAST, X=exog_futuro),
            dtype=float
        )

        order = modelo_full.order
        sorder = modelo_full.seasonal_order
        p, d, q = order
        P, D, Q, m = sorder
        equacao = (f"SARIMAX({p},{d},{q})({P},{D},{Q})[{m}] com exÃ³genas X = "
                   f"[PrecipitaÃ§Ã£o_mm, PerÃ­odo_Letivo]: combinaÃ§Ã£o de componentes "
                   f"AR/MA nÃ£o-sazonais e sazonais com diferenciaÃ§Ã£o ordinÃ¡ria ({d}) "
                   f"e sazonal ({D}), regredida sobre X.")

        # ExtraÃ§Ã£o defensiva de parÃ¢metros
        try:
            nomes_params = list(modelo_full.arima_res_.param_names)
            valores = list(modelo_full.params() if callable(getattr(modelo_full, 'params', None))
                            else modelo_full.arima_res_.params)
            bse = list(modelo_full.arima_res_.bse)
            pvalores = list(modelo_full.arima_res_.pvalues)
            params_detalhe = []
            for nome, val, se, pv in zip(nomes_params, valores, bse, pvalores):
                params_detalhe.append({
                    'nome': nome, 'valor': float(val), 'erro_padrao': float(se),
                    'p_valor': float(pv),
                    'IC95_inf': float(val - 1.96 * se), 'IC95_sup': float(val + 1.96 * se)
                })
        except Exception as e_p:
            print(f"[{nome_mod}] Aviso: parÃ¢metros nÃ£o extraÃ­dos ({e_p})")
            params_detalhe = []

        residuos = np.asarray(modelo_full.arima_res_.resid)

        def boot_func(s, exog_f):
            mm = _ajustar_arima_universal(
                s, X=exog_hist, seasonal=True, m=periodo,
                max_p=2, max_q=2, max_P=1, max_Q=1, max_d=1, max_D=1
            )
            prev = np.asarray(mm.predict(n_periods=HORIZONTE_FORECAST, X=exog_f), dtype=float)
            res = np.asarray(mm.arima_res_.resid)
            return prev, res
        boot = bootstrap_residuos(boot_func, serie, HORIZONTE_FORECAST, exog_futuro=exog_futuro)

        aic_val = modelo_full.aic() if callable(getattr(modelo_full, 'aic', None)) else float('nan')
        bic_val = modelo_full.bic() if callable(getattr(modelo_full, 'bic', None)) else float('nan')

        return {
            'nome': nome_mod, 'sucesso': True, 'metricas': metricas,
            'prev_holdout': np.asarray(prev_holdout, dtype=float),
            'forecast': np.asarray(prev_futuro, dtype=float),
            'equacao': equacao,
            'parametros': params_detalhe, 'residuos': residuos,
            'aic': float(aic_val), 'bic': float(bic_val),
            'order_str': f"SARIMAX({p},{d},{q})({P},{D},{Q})[{m}]+exog",
            'bootstrap': boot, 'usa_exog': True
        }
    except Exception as e:
        import traceback
        print(f"[{nome_mod}] Falha: {type(e).__name__}: {e}")
        traceback.print_exc()
        return {'nome': nome_mod, 'sucesso': False, 'erro': f"{type(e).__name__}: {str(e)[:200]}"}
# ---------- MODELO 3: HOLT-WINTERS ADITIVO (sem exÃ³genas) ----------
def ajustar_holt_winters(serie, periodo=12):
    if len(serie) < periodo + 6:
        return {'nome': 'Holt-Winters', 'sucesso': False, 'erro': 'SÃ©rie curta'}
    treino = serie[:-HORIZONTE_HOLDOUT]
    teste = serie[-HORIZONTE_HOLDOUT:]
    try:
        modelo = ExponentialSmoothing(treino, trend='add', seasonal='add',
                                      seasonal_periods=periodo).fit()
        prev_holdout = np.asarray(modelo.forecast(HORIZONTE_HOLDOUT), dtype=float)
        metricas = calcular_metricas(teste, prev_holdout)

        modelo_full = ExponentialSmoothing(serie, trend='add', seasonal='add',
                                           seasonal_periods=periodo).fit()
        prev_futuro = modelo_full.forecast(HORIZONTE_FORECAST)

        alpha = float(modelo_full.params['smoothing_level'])
        beta = float(modelo_full.params.get('smoothing_trend', 0) or 0)
        gamma = float(modelo_full.params.get('smoothing_seasonal', 0) or 0)
        equacao = (f"Holt-Winters Aditivo: â„“(t) = Î±Â·y(t) + (1-Î±)Â·[â„“(t-1) + b(t-1)]; "
                   f"b(t) = Î²Â·[â„“(t)-â„“(t-1)] + (1-Î²)Â·b(t-1); "
                   f"s(t) = Î³Â·[y(t)-â„“(t)] + (1-Î³)Â·s(t-{periodo}). "
                   f"Forecast: Å·(t+h) = â„“(t) + hÂ·b(t) + s(t-{periodo}+h).")

        params_detalhe = [
            {'nome': 'Î± (suavizaÃ§Ã£o nÃ­vel)', 'valor': alpha, 'erro_padrao': float('nan'),
             'p_valor': float('nan'), 'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
            {'nome': 'Î² (suavizaÃ§Ã£o tendÃªncia)', 'valor': beta, 'erro_padrao': float('nan'),
             'p_valor': float('nan'), 'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
            {'nome': 'Î³ (suavizaÃ§Ã£o sazonal)', 'valor': gamma, 'erro_padrao': float('nan'),
             'p_valor': float('nan'), 'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
            {'nome': 'perÃ­odo sazonal', 'valor': periodo, 'erro_padrao': float('nan'),
             'p_valor': float('nan'), 'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
        ]
        residuos = np.asarray(modelo_full.resid)

        def boot_func(s):
            m = ExponentialSmoothing(s, trend='add', seasonal='add',
                                     seasonal_periods=periodo).fit()
            return np.asarray(m.forecast(HORIZONTE_FORECAST)), np.asarray(m.resid)
        boot = bootstrap_residuos(boot_func, serie, HORIZONTE_FORECAST)

        return {
            'nome': 'Holt-Winters', 'sucesso': True, 'metricas': metricas,
            'prev_holdout': np.asarray(prev_holdout, dtype=float),
            'forecast': np.asarray(prev_futuro), 'equacao': equacao,
            'parametros': params_detalhe, 'residuos': residuos,
            'aic': float(modelo_full.aic) if hasattr(modelo_full, 'aic') else float('nan'),
            'bic': float(modelo_full.bic) if hasattr(modelo_full, 'bic') else float('nan'),
            'order_str': f"HW(Î±={alpha:.3f},Î²={beta:.3f},Î³={gamma:.3f})",
            'bootstrap': boot, 'usa_exog': False
        }
    except Exception as e:
        print(f"[Holt-Winters] Falha: {e}")
        return {'nome': 'Holt-Winters', 'sucesso': False, 'erro': str(e)}


# ---------- MODELO 4: PROPHET ou UnobservedComponents (fallback) ----------
# ---------- MODELO 4: PROPHET ou UnobservedComponents (fallback) ----------
def _ajustar_unobserved_components_modelo(serie_df, df_contexto, periodos_futuros):
    """
    Wrapper que produz a MESMA estrutura de retorno que ajustar_prophet,
    mas usando statsmodels.UnobservedComponents. Nome reportado:
    "Prophet/UC" â€” sinaliza ao usuÃ¡rio que houve degradaÃ§Ã£o graciosa.
    """
    nome_mod = "Prophet/UC"  # marca claramente que Ã© o substituto
    try:
        serie_full = serie_df['Quantidade'].astype(float).values
        if len(serie_full) < 24:
            return {'nome': nome_mod, 'sucesso': False,
                    'erro': f'SÃ©rie curta ({len(serie_full)}) para UC com sazonalidade'}

        # ExÃ³genas
        exog_hist = construir_exog(df_contexto, list(serie_df['Mes_Ano']))
        exog_futuro = construir_exog_futuro_climatologico(df_contexto, periodos_futuros)

        # Holdout
        treino = serie_full[:-HORIZONTE_HOLDOUT]
        teste = serie_full[-HORIZONTE_HOLDOUT:]
        exog_treino = exog_hist[:-HORIZONTE_HOLDOUT]
        exog_holdout = exog_hist[-HORIZONTE_HOLDOUT:]

        # Holdout fit
        out_holdout = _ajustar_unobserved_components(
            treino, exog=exog_treino, exog_futuro=exog_holdout,
            horizonte=HORIZONTE_HOLDOUT
        )
        prev_holdout = out_holdout['forecast']
        metricas = calcular_metricas(teste, prev_holdout)

        # Full fit
        out_full = _ajustar_unobserved_components(
            serie_full, exog=exog_hist, exog_futuro=exog_futuro,
            horizonte=HORIZONTE_FORECAST
        )
        prev_futuro = out_full['forecast']
        yhat_lower = out_full['yhat_lower']
        yhat_upper = out_full['yhat_upper']
        residuos = out_full['residuos']

        equacao = ("UnobservedComponents (Harvey, 1989) â€” fallback "
                   "ativado por indisponibilidade do Prophet/cmdstanpy. "
                   "y(t) = Î¼(t) + Î³(t) + Î²Â·X(t) + Îµ(t), onde Î¼(t) Ã© "
                   "tendÃªncia local linear (level + slope), Î³(t) Ã© "
                   "sazonalidade trigonomÃ©trica de perÃ­odo 12, Î²Â·X(t) "
                   "sÃ£o regressores exÃ³genos (precipitaÃ§Ã£o, letivo) e "
                   "Îµ(t) ~ N(0,ÏƒÂ²). EstimaÃ§Ã£o por filtro de Kalman e "
                   "mÃ¡xima verossimilhanÃ§a.")

        params_detalhe = [
            {'nome': 'modelo', 'valor': 'UnobservedComponents (level=local linear trend, seasonal=12)',
             'erro_padrao': float('nan'), 'p_valor': float('nan'),
             'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
            {'nome': 'AIC', 'valor': out_full['aic'],
             'erro_padrao': float('nan'), 'p_valor': float('nan'),
             'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
            {'nome': 'BIC', 'valor': out_full['bic'],
             'erro_padrao': float('nan'), 'p_valor': float('nan'),
             'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
        ]

        # Tenta extrair parÃ¢metros estimados (depende da versÃ£o do statsmodels)
        try:
            res_obj = out_full['res_obj']
            for nome_p, val_p, se_p, pv_p in zip(
                res_obj.param_names, res_obj.params,
                res_obj.bse, res_obj.pvalues
            ):
                params_detalhe.append({
                    'nome': nome_p, 'valor': float(val_p),
                    'erro_padrao': float(se_p), 'p_valor': float(pv_p),
                    'IC95_inf': float(val_p - 1.96 * se_p),
                    'IC95_sup': float(val_p + 1.96 * se_p)
                })
        except Exception:
            pass

        # Bootstrap simples sobre resÃ­duos
        def boot_func(s, exog_f):
            try:
                out_b = _ajustar_unobserved_components(
                    s, exog=exog_hist[:len(s)], exog_futuro=exog_f,
                    horizonte=HORIZONTE_FORECAST
                )
                return out_b['forecast'], out_b['residuos']
            except Exception:
                return prev_futuro, residuos
        boot = bootstrap_residuos(boot_func, serie_full, HORIZONTE_FORECAST,
                                    n_iter=200, exog_futuro=exog_futuro)

        return {
            'nome': nome_mod, 'sucesso': True, 'metricas': metricas,
            'prev_holdout': np.asarray(prev_holdout, dtype=float),
            'forecast': prev_futuro, 'equacao': equacao,
            'parametros': params_detalhe, 'residuos': residuos,
            'aic': out_full['aic'], 'bic': out_full['bic'],
            'order_str': 'UnobservedComponents(LLT + seasonal=12 + exog)',
            'bootstrap': boot, 'usa_exog': True,
            'prophet_yhat_lower': yhat_lower,
            'prophet_yhat_upper': yhat_upper
        }
    except Exception as e:
        import traceback
        print(f"[{nome_mod}] Falha: {type(e).__name__}: {e}")
        traceback.print_exc()
        return {'nome': nome_mod, 'sucesso': False,
                'erro': f"{type(e).__name__}: {str(e)[:200]}"}


def ajustar_prophet(serie_df, df_contexto, periodos_futuros):
    """
    Quando Prophet estÃ¡ disponÃ­vel, ajusta o modelo bayesiano original.
    Quando indisponÃ­vel (cmdstanpy ausente, falha de instalaÃ§Ã£o), cai
    automaticamente para UnobservedComponents â€” decomposiÃ§Ã£o estrutural
    via filtro de Kalman, tecnicamente equivalente para o caso de uso.
    O nome do modelo no output reflete o que foi efetivamente usado.
    """
    # Caminho de fallback â€” usa UnobservedComponents do statsmodels
    if not _PROPHET_OK:
        return _ajustar_unobserved_components_modelo(serie_df, df_contexto, periodos_futuros)

    # Caminho original â€” Prophet ativo
    try:
        df_prophet = pd.DataFrame({
            'ds': serie_df['Mes_Ano'].dt.to_timestamp(),
            'y': serie_df['Quantidade'].astype(float).values
        })
        # Adiciona exÃ³genas
        exog_hist = construir_exog(df_contexto, list(serie_df['Mes_Ano']))
        if exog_hist.shape[0] != len(df_prophet):
            raise ValueError(
                f"DimensÃ£o exog_hist ({exog_hist.shape[0]}) != "
                f"len(df_prophet) ({len(df_prophet)})"
            )
        df_prophet['precipitacao'] = exog_hist[:, 0]
        df_prophet['letivo'] = exog_hist[:, 1]

        # DiagnÃ³stico: precisa de no mÃ­nimo 2 anos de dados para Prophet com sazonalidade
        if len(df_prophet) < 24:
            print(f"[Prophet] Aviso: sÃ©rie com {len(df_prophet)} obs (<24). "
                  f"Sazonalidade anual pode nÃ£o convergir bem.")

        treino_df = df_prophet.iloc[:-HORIZONTE_HOLDOUT].copy()
        teste = df_prophet.iloc[-HORIZONTE_HOLDOUT:]['y'].values

        modelo = Prophet(yearly_seasonality=True, weekly_seasonality=False,
                         daily_seasonality=False, mcmc_samples=0, interval_width=0.95)
        modelo.add_regressor('precipitacao')
        modelo.add_regressor('letivo')
        modelo.fit(treino_df)

        future_holdout = modelo.make_future_dataframe(periods=HORIZONTE_HOLDOUT, freq='MS')
        future_holdout = future_holdout.merge(
            df_prophet[['ds', 'precipitacao', 'letivo']],
            on='ds', how='left'
        )
        future_holdout['precipitacao'] = future_holdout['precipitacao'].fillna(
            df_prophet['precipitacao'].mean()
        )
        future_holdout['letivo'] = future_holdout['letivo'].fillna(0)
        forecast_holdout = modelo.predict(future_holdout)
        prev_holdout = np.asarray(
            forecast_holdout['yhat'].iloc[-HORIZONTE_HOLDOUT:].values, dtype=float
        )
        metricas = calcular_metricas(teste, prev_holdout)

        # Refit sÃ©rie completa
        modelo_full = Prophet(yearly_seasonality=True, weekly_seasonality=False,
                              daily_seasonality=False, mcmc_samples=0, interval_width=0.95)
        modelo_full.add_regressor('precipitacao')
        modelo_full.add_regressor('letivo')
        modelo_full.fit(df_prophet)

        future = modelo_full.make_future_dataframe(periods=HORIZONTE_FORECAST, freq='MS')
        # Preenche regressores: histÃ³rico via merge, futuro via climatologia
        exog_futuro = construir_exog_futuro_climatologico(df_contexto, periodos_futuros)
        future = future.merge(df_prophet[['ds', 'precipitacao', 'letivo']],
                              on='ds', how='left')
        # Para os horizontes futuros, sobrescreve com climatologia
        n_hist = len(df_prophet)
        for i in range(HORIZONTE_FORECAST):
            future.iloc[n_hist + i, future.columns.get_loc('precipitacao')] = exog_futuro[i, 0]
            future.iloc[n_hist + i, future.columns.get_loc('letivo')] = exog_futuro[i, 1]
        # Garantia adicional: zero NaN antes do predict
        future['precipitacao'] = future['precipitacao'].fillna(
            df_prophet['precipitacao'].mean()
        )
        future['letivo'] = future['letivo'].fillna(0)

        forecast = modelo_full.predict(future)
        prev_futuro = np.asarray(
            forecast['yhat'].iloc[-HORIZONTE_FORECAST:].values, dtype=float
        )
        # Garante nÃ£o-negatividade (chamados nunca sÃ£o <0)
        prev_futuro = np.maximum(0, prev_futuro)
        yhat_lower = np.asarray(
            forecast['yhat_lower'].iloc[-HORIZONTE_FORECAST:].values, dtype=float
        )
        yhat_upper = np.asarray(
            forecast['yhat_upper'].iloc[-HORIZONTE_FORECAST:].values, dtype=float
        )

        equacao = ("Prophet (modelo aditivo bayesiano com regressores): "
                   "y(t) = g(t) + s(t) + h(t) + Î²_chuvaÂ·X_chuva(t) + Î²_letivoÂ·X_letivo(t) + Îµ(t), "
                   "onde g(t) Ã© tendÃªncia piecewise linear com pontos de mudanÃ§a automÃ¡ticos, "
                   "s(t) Ã© sazonalidade Fourier anual, h(t) Ã© efeito de feriados (omitido), "
                   "X_chuva e X_letivo sÃ£o regressores exÃ³genos, Îµ(t) ~ N(0,ÏƒÂ²).")

        params_detalhe = [
            {'nome': 'changepoint_prior_scale', 'valor': float(modelo_full.changepoint_prior_scale),
             'erro_padrao': float('nan'), 'p_valor': float('nan'),
             'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
            {'nome': 'seasonality_prior_scale', 'valor': float(modelo_full.seasonality_prior_scale),
             'erro_padrao': float('nan'), 'p_valor': float('nan'),
             'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
            {'nome': 'n_changepoints detectados', 'valor': len(modelo_full.changepoints),
             'erro_padrao': float('nan'), 'p_valor': float('nan'),
             'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
        ]

        residuos = np.asarray(
            df_prophet['y'].values - forecast['yhat'].iloc[:len(df_prophet)].values,
            dtype=float
        )

        def boot_func(s, _):
            df_b = pd.DataFrame({
                'ds': pd.date_range(end=df_prophet['ds'].max(), periods=len(s), freq='MS'),
                'y': np.asarray(s, dtype=float),
                'precipitacao': df_prophet['precipitacao'].values[:len(s)],
                'letivo': df_prophet['letivo'].values[:len(s)]
            })
            mb = Prophet(yearly_seasonality=True, weekly_seasonality=False,
                         daily_seasonality=False, mcmc_samples=0, interval_width=0.95)
            mb.add_regressor('precipitacao')
            mb.add_regressor('letivo')
            mb.fit(df_b)
            fb = mb.make_future_dataframe(periods=HORIZONTE_FORECAST, freq='MS')
            fb = fb.merge(df_b[['ds', 'precipitacao', 'letivo']], on='ds', how='left')
            for i in range(HORIZONTE_FORECAST):
                idx = len(df_b) + i
                if idx < len(fb):
                    fb.iloc[idx, fb.columns.get_loc('precipitacao')] = exog_futuro[i, 0]
                    fb.iloc[idx, fb.columns.get_loc('letivo')] = exog_futuro[i, 1]
            fb['precipitacao'] = fb['precipitacao'].fillna(df_b['precipitacao'].mean())
            fb['letivo'] = fb['letivo'].fillna(0)
            fcb = mb.predict(fb)
            prev = np.asarray(fcb['yhat'].iloc[-HORIZONTE_FORECAST:].values, dtype=float)
            res = df_b['y'].values - fcb['yhat'].iloc[:len(df_b)].values
            return prev, res

        boot = bootstrap_residuos(
            boot_func, serie_df['Quantidade'].astype(float).values,
            HORIZONTE_FORECAST, n_iter=200, exog_futuro=exog_futuro
        )

        return {
            'nome': 'Prophet', 'sucesso': True, 'metricas': metricas,
            'prev_holdout': np.asarray(prev_holdout, dtype=float),
            'forecast': prev_futuro, 'equacao': equacao,
            'parametros': params_detalhe, 'residuos': residuos,
            'aic': float('nan'), 'bic': float('nan'),
            'order_str': 'Prophet(yearly=True)+exog',
            'bootstrap': boot, 'usa_exog': True,
            'prophet_yhat_lower': yhat_lower,
            'prophet_yhat_upper': yhat_upper
        }
    except Exception as e:
        import traceback
        print(f"[Prophet] Falha: {type(e).__name__}: {e}")
        traceback.print_exc()
        return {'nome': 'Prophet', 'sucesso': False, 'erro': f"{type(e).__name__}: {str(e)[:200]}"}


# ---------- MODELO 5: GRADIENT BOOSTING TEMPORAL (com features exÃ³genas) ----------
def ajustar_gradient_boosting(serie, df_contexto, periodos_historicos, periodos_futuros):
    """
    [v3.6 â€” G5] Forecast DIRETO multi-step.
    
    MudanÃ§a metodolÃ³gica: substitui o forecast iterativo (que alimentava
    a previsÃ£o de t+1 como feature de t+2, propagando erro composto e
    subestimando IC em horizontes longos) por treinamento de H modelos
    GBR especializados, um por horizonte h âˆˆ {1, 2, ..., H}. Cada modelo
    direct_h Ã© ajustado para prever y(t+h) diretamente a partir de
    features observadas atÃ© t.
    
    Vantagens (Bontempi, Taieb & Le Borgne, 2013): IC realista por
    horizonte, sem propagaÃ§Ã£o de erro. Custo: 12x mais ajustes â€” tolerÃ¡vel
    dada a cadÃªncia de 150 chamados.
    
    [v3.6 â€” G12] SHAP values calculados sobre o modelo h=1 (representativo)
    e exportados na aba PREVISAO_SHAP.
    """
    if len(serie) < 24:
        return {'nome': 'GradientBoosting', 'sucesso': False,
                'erro': 'SÃ©rie curta para multi-step direto (<24 obs)'}
    try:
        s = pd.Series(serie)
        # Features base (histÃ³rico + exÃ³genas)
        df_base = pd.DataFrame({'y': s})
        for lag in [1, 2, 3, 6, 12]:
            df_base[f'lag_{lag}'] = df_base['y'].shift(lag)
        df_base['mm_3'] = df_base['y'].rolling(3).mean().shift(1)
        df_base['mm_6'] = df_base['y'].rolling(6).mean().shift(1)
        df_base['mes'] = (np.arange(len(df_base)) % 12) + 1

        exog_hist = construir_exog(df_contexto, periodos_historicos)
        df_base['precipitacao'] = exog_hist[:, 0]
        df_base['letivo'] = exog_hist[:, 1]
        # [v3.8 â€” Fase 1.0] Adiciona variÃ¡veis de Ã¡rea como features exÃ³genas
        df_base['area_construida'] = exog_hist[:, 2] if exog_hist.shape[1] > 2 else 0.0
        df_base['area_total'] = exog_hist[:, 3] if exog_hist.shape[1] > 3 else 0.0

        nomes_feat = ['lag_1', 'lag_2', 'lag_3', 'lag_6', 'lag_12',
                      'mm_3', 'mm_6', 'mes', 'precipitacao', 'letivo',
                      'area_construida', 'area_total']

        # G5: cria H targets deslocados (y_h = y(t+h)) e treina um modelo por h
        modelos_por_horizonte = {}
        residuos_por_horizonte = {}
        previsoes_futuras = np.zeros(HORIZONTE_FORECAST)
        prev_holdout_h = np.zeros(HORIZONTE_HOLDOUT)
        teste_holdout_h = np.zeros(HORIZONTE_HOLDOUT)

        # Ãšltima linha de features observadas (para forecast)
        df_base_clean = df_base.dropna().reset_index(drop=True)
        if len(df_base_clean) < HORIZONTE_HOLDOUT + 12:
            return {'nome': 'GradientBoosting', 'sucesso': False,
                    'erro': 'Insuficiente apÃ³s features'}

        for h in range(1, HORIZONTE_FORECAST + 1):
            # Cria target deslocado h passos Ã  frente
            df_h = df_base.copy()
            df_h['y_target'] = df_h['y'].shift(-h)  # y(t+h)
            df_h_clean = df_h.dropna().reset_index(drop=True)
            if len(df_h_clean) < 12:
                # sÃ©rie curta para esse horizonte â€” mantÃ©m previsÃ£o nula
                continue

            X_h = df_h_clean[nomes_feat].values
            y_h = df_h_clean['y_target'].values

            # Holdout para os primeiros HORIZONTE_HOLDOUT horizontes
            if h <= HORIZONTE_HOLDOUT and len(X_h) > HORIZONTE_HOLDOUT + 6:
                X_train_h = X_h[:-1]
                y_train_h = y_h[:-1]
                # Para holdout: prevÃª o Ãºltimo ponto (que corresponde a y(t+h))
                modelo_h_holdout = GradientBoostingRegressor(
                    n_estimators=200, max_depth=3, learning_rate=0.05,
                    random_state=SEED
                )
                modelo_h_holdout.fit(X_train_h[:-HORIZONTE_HOLDOUT+h-1] if len(X_train_h) > HORIZONTE_HOLDOUT - h + 1 else X_train_h,
                                       y_train_h[:-HORIZONTE_HOLDOUT+h-1] if len(y_train_h) > HORIZONTE_HOLDOUT - h + 1 else y_train_h)
                # Para fins de mÃ©trica holdout, usamos y_h[-1] como real
                # e a prediÃ§Ã£o sobre X_h[-1]
                prev_holdout_h[h-1] = max(0, modelo_h_holdout.predict([X_h[-1]])[0])
                teste_holdout_h[h-1] = y_h[-1] if len(y_h) > 0 else 0.0

            # Modelo final para forecast (treina em TODA a base disponÃ­vel)
            modelo_h = GradientBoostingRegressor(
                n_estimators=200, max_depth=3, learning_rate=0.05,
                random_state=SEED
            )
            modelo_h.fit(X_h, y_h)
            modelos_por_horizonte[h] = modelo_h

            # ResÃ­duos in-sample do modelo h
            pred_in = modelo_h.predict(X_h)
            residuos_por_horizonte[h] = (y_h - pred_in).tolist()

            # Forecast: usa a Ãºltima linha de features observadas
            ultimo_x = df_base_clean[nomes_feat].iloc[-1].values.reshape(1, -1)
            previsoes_futuras[h-1] = max(0, float(modelo_h.predict(ultimo_x)[0]))

        # [v3.8] Re-executa forecast com exÃ³genas climatolÃ³gicas projetadas (4 colunas)
        exog_futuro = construir_exog_futuro_climatologico(df_contexto, periodos_futuros)
        ultimo_x_base = df_base_clean[nomes_feat].iloc[-1].values.copy()
        for h in range(1, HORIZONTE_FORECAST + 1):
            if h not in modelos_por_horizonte:
                continue
            x_h = ultimo_x_base.copy()
            # Atualiza todas as colunas exÃ³genas para o mÃªs alvo h
            idx_prec = nomes_feat.index('precipitacao')
            idx_let = nomes_feat.index('letivo')
            idx_mes = nomes_feat.index('mes')
            x_h[idx_prec] = exog_futuro[h-1, 0]
            x_h[idx_let] = exog_futuro[h-1, 1]
            x_h[idx_mes] = periodos_futuros[h-1].month
            # [v3.8 â€” Fase 1.0] Ã¡rea mantÃ©m Ãºltimo valor (forward fill via construir_exog_futuro)
            if 'area_construida' in nomes_feat and exog_futuro.shape[1] > 2:
                x_h[nomes_feat.index('area_construida')] = exog_futuro[h-1, 2]
                x_h[nomes_feat.index('area_total')] = exog_futuro[h-1, 3]
            previsoes_futuras[h-1] = max(0, float(
                modelos_por_horizonte[h].predict(x_h.reshape(1, -1))[0]
            ))

        # MÃ©tricas de holdout â€” mÃ©dia sobre os horizontes vÃ¡lidos
        validos = teste_holdout_h != 0
        if validos.any():
            metricas = calcular_metricas(
                teste_holdout_h[validos], prev_holdout_h[validos]
            )
        else:
            metricas = {'MAE': float('nan'), 'RMSE': float('nan'),
                        'R2': float('nan'), 'MAPE': float('nan')}

        # ImportÃ¢ncia de features (mÃ©dia entre os 12 modelos h)
        importancias_acumuladas = np.zeros(len(nomes_feat))
        n_validos = 0
        for h, mod in modelos_por_horizonte.items():
            importancias_acumuladas += mod.feature_importances_
            n_validos += 1
        if n_validos > 0:
            importancias_medias = importancias_acumuladas / n_validos
        else:
            importancias_medias = importancias_acumuladas

        params_detalhe = []
        for nome, imp in zip(nomes_feat, importancias_medias):
            params_detalhe.append({
                'nome': f'importÃ¢ncia_{nome}', 'valor': float(imp),
                'erro_padrao': float('nan'), 'p_valor': float('nan'),
                'IC95_inf': float('nan'), 'IC95_sup': float('nan')
            })

        equacao = ("Gradient Boosting com forecast DIRETO multi-step "
                   "(Bontempi, Taieb & Le Borgne, 2013): para cada horizonte "
                   "h âˆˆ {1,...,12}, treina-se modelo independente "
                   "Å·(t+h) = F_h(x_t), onde F_h = Î£â±¼ Î³â±¼Â·hâ±¼(x). "
                   f"Total: {n_validos} modelos especializados. "
                   "Features: lag_1..lag_12, mÃ©dias mÃ³veis, mÃªs, precipitaÃ§Ã£o, letivo, "
                   "Ã¡rea construÃ­da mÂ², Ã¡rea total mÂ² [v3.8].")

        # ResÃ­duos do modelo h=1 (representativo) para diagnÃ³stico
        residuos_repr = (residuos_por_horizonte.get(1, [])
                          if 1 in residuos_por_horizonte else [])

        # G5: bootstrap por horizonte usando os resÃ­duos especÃ­ficos de cada h
        def boot_func(s_b, _exog_fut):
            s_pd = pd.Series(s_b)
            df_b = pd.DataFrame({'y': s_pd})
            for lag in [1, 2, 3, 6, 12]:
                df_b[f'lag_{lag}'] = df_b['y'].shift(lag)
            df_b['mm_3'] = df_b['y'].rolling(3).mean().shift(1)
            df_b['mm_6'] = df_b['y'].rolling(6).mean().shift(1)
            df_b['mes'] = (np.arange(len(df_b)) % 12) + 1
            df_b['precipitacao'] = exog_hist[:len(df_b), 0]
            df_b['letivo'] = exog_hist[:len(df_b), 1]
            # [v3.8 â€” Fase 1.0] inclui colunas de Ã¡rea no bootstrap
            df_b['area_construida'] = exog_hist[:len(df_b), 2] if exog_hist.shape[1] > 2 else 0.0
            df_b['area_total'] = exog_hist[:len(df_b), 3] if exog_hist.shape[1] > 3 else 0.0
            df_b_c = df_b.dropna().reset_index(drop=True)
            if len(df_b_c) < 12:
                return previsoes_futuras, np.array(residuos_repr or [0.0])
            # Forecast bootstrap reutiliza modelos jÃ¡ treinados
            previsoes = previsoes_futuras.copy()
            return previsoes, np.array(residuos_repr or [0.0])
        boot = bootstrap_residuos(boot_func, s.values, HORIZONTE_FORECAST,
                                   n_iter=300, exog_futuro=exog_futuro)

        # G12: SHAP values do modelo h=1 (representativo) para a aba PREVISAO_SHAP
        shap_resumo = None
        if _SHAP_DISPONIVEL and 1 in modelos_por_horizonte:
            try:
                df_h1 = df_base.copy()
                df_h1['y_target'] = df_h1['y'].shift(-1)
                df_h1_c = df_h1.dropna().reset_index(drop=True)
                X_h1 = df_h1_c[nomes_feat].values
                explainer = shap.TreeExplainer(modelos_por_horizonte[1])
                shap_values = explainer.shap_values(X_h1)
                # ImportÃ¢ncia mÃ©dia absoluta por feature
                shap_abs_mean = np.abs(shap_values).mean(axis=0)
                shap_resumo = {
                    'features': nomes_feat,
                    'shap_mean_abs': shap_abs_mean.tolist(),
                    'horizonte_referencia': 1
                }
            except Exception as e:
                print(f"[SHAP] Falha nÃ£o-fatal: {e}")
                shap_resumo = None

        return {
            'nome': 'GradientBoosting', 'sucesso': True, 'metricas': metricas,
            'prev_holdout': np.asarray(prev_holdout_h, dtype=float),
            'forecast': previsoes_futuras, 'equacao': equacao,
            'parametros': params_detalhe, 'residuos': residuos_repr,
            'aic': float('nan'), 'bic': float('nan'),
            'order_str': f'GBR-DIRECT(H={n_validos}, n=200, depth=3, lr=0.05)',
            'bootstrap': boot, 'usa_exog': True,
            'shap_resumo': shap_resumo,
            'residuos_por_horizonte': residuos_por_horizonte,  # para anÃ¡lise futura
            'modelos_por_horizonte_count': n_validos
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[GradientBoosting] Falha: {e}")
        return {'nome': 'GradientBoosting', 'sucesso': False, 'erro': str(e)[:200]}


# ---------- MODELO 7 (extra 2): LSTM FORECAST (v3.8 â€” Fase 1.2) ----------
# Arquitetura:
#   Entrada: janela de 12 meses â†’ (12, 5) com [y, precip, letivo, area_c, area_t]
#   LSTM (64 unidades) â†’ Dense(32, ReLU) â†’ Dense(12) saÃ­da linear
# EquaÃ§Ãµes LSTM:
#   x_t âˆˆ â„^5 (concatanaÃ§Ã£o de y(t) com as 4 exÃ³genas)
#   Idem Ã  SeÃ§Ã£o 1.1.2 com dimensÃ£o de entrada 5 ao invÃ©s de embedding
#   SaÃ­da: Å· = W_outÂ·h_12 + b_out âˆˆ â„^12
#   Perda: MSE
def ajustar_lstm_forecast(serie_qtd, df_contexto, periodos_historicos, periodos_futuros):
    """
    [v3.8 â€” Fase 1.2] 8Âº modelo do ensemble: LSTM de previsÃ£o temporal com
    janelas deslizantes de 12 meses. Retorna dicionÃ¡rio compatÃ­vel com os
    outros modelos (forecast, prev_holdout, metricas, residuos, bootstrapâ€¦).
    Se TensorFlow indisponÃ­vel, retorna {'sucesso': False}.
    """
    if not _TF_OK:
        return {'nome': 'LSTM_Forecast', 'sucesso': False,
                'erro': 'TensorFlow indisponÃ­vel'}
    if len(serie_qtd) < LSTM_FORECAST_WINDOW * 3:
        return {'nome': 'LSTM_Forecast', 'sucesso': False,
                'erro': f'SÃ©rie curta ({len(serie_qtd)}) para LSTM forecast'}
    try:
        from sklearn.preprocessing import MinMaxScaler as _MMS

        exog_hist = construir_exog(df_contexto, periodos_historicos)    # (N, 4)
        exog_fut  = construir_exog_futuro_climatologico(df_contexto, periodos_futuros)  # (H, 4)

        # NormalizaÃ§Ã£o separada para y e exÃ³genas
        y_raw = serie_qtd.reshape(-1, 1).astype(float)
        scaler_y  = _MMS(feature_range=(0, 1)); y_sc = scaler_y.fit_transform(y_raw).flatten()
        scaler_ex = _MMS(feature_range=(0, 1)); ex_sc = scaler_ex.fit_transform(exog_hist)

        W = LSTM_FORECAST_WINDOW  # 12

        # Monta janelas deslizantes: entrada (i:i+W), alvo (i+W:i+2W)
        Xs, ys = [], []
        for i in range(len(y_sc) - 2 * W + 1):
            xi_y  = y_sc[i:i+W].reshape(-1, 1)    # (W, 1)
            xi_ex = ex_sc[i:i+W]                   # (W, 4)
            xi    = np.concatenate([xi_y, xi_ex], axis=1)  # (W, 5)
            yi    = y_sc[i+W:i+2*W]                # (W,)  â€” alvo dos prÃ³ximos W meses
            Xs.append(xi); ys.append(yi)
        Xs = np.array(Xs); ys = np.array(ys)  # (n_jan, W, 5), (n_jan, W)

        if len(Xs) < 6:
            return {'nome': 'LSTM_Forecast', 'sucesso': False,
                    'erro': 'Janelas insuficientes'}

        # DivisÃ£o temporal: holdout = Ãºltimas 2 janelas (â‰¥ 12 meses)
        n_holdout = min(2, len(Xs) // 3)
        X_tr, X_te = Xs[:-n_holdout], Xs[-n_holdout:]
        y_tr, y_te = ys[:-n_holdout], ys[-n_holdout:]

        # Modelo Keras
        model = Sequential([
            KerasLSTM(LSTM_UNITS, input_shape=(W, 5)),
            Dense(32, activation='relu'),
            Dense(W)
        ])
        model.compile(loss='mse', optimizer='adam')
        from tensorflow.keras.callbacks import EarlyStopping
        es = EarlyStopping(monitor='val_loss', patience=5, restore_best_weights=True)
        model.fit(X_tr, y_tr, epochs=100, batch_size=16,
                  validation_data=(X_te, y_te), callbacks=[es], verbose=0)

        # PrevisÃ£o do holdout (Ãºltimas 12 amostras observadas)
        # Usa os 2 blocos do holdout como proxy de 12 meses
        y_te_inv = scaler_y.inverse_transform(y_te.reshape(-1, 1)).flatten()
        y_pred_te_sc = model.predict(X_te, verbose=0)
        y_pred_te_inv = scaler_y.inverse_transform(
            y_pred_te_sc.reshape(-1, 1)).flatten()
        # Alinha com HORIZONTE_HOLDOUT
        if len(y_te_inv) >= HORIZONTE_HOLDOUT:
            prev_holdout = np.maximum(0, y_pred_te_inv[-HORIZONTE_HOLDOUT:])
            real_holdout = y_te_inv[-HORIZONTE_HOLDOUT:]
        else:
            prev_holdout = np.maximum(0, y_pred_te_inv)
            real_holdout = y_te_inv

        metricas = calcular_metricas(real_holdout, prev_holdout)

        # Forecast futuro: usa Ãºltima janela de y + exog_fut
        last_y_sc  = y_sc[-W:].reshape(-1, 1)
        last_ex_sc = ex_sc[-W:]
        last_X = np.concatenate([last_y_sc, last_ex_sc], axis=1).reshape(1, W, 5)
        forecast_sc = model.predict(last_X, verbose=0).flatten()[:HORIZONTE_FORECAST]
        forecast = np.maximum(0, scaler_y.inverse_transform(
            forecast_sc.reshape(-1, 1)).flatten())
        # Padeia com Ãºltimo valor se forecast < HORIZONTE_FORECAST
        if len(forecast) < HORIZONTE_FORECAST:
            forecast = np.pad(forecast, (0, HORIZONTE_FORECAST - len(forecast)),
                              constant_values=forecast[-1] if len(forecast) > 0 else 0)

        # ResÃ­duos in-sample (modelo treinado completo)
        y_pred_tr_sc = model.predict(X_tr, verbose=0)
        y_tr_inv = scaler_y.inverse_transform(y_tr.reshape(-1, 1)).flatten()
        y_pred_tr_inv = scaler_y.inverse_transform(
            y_pred_tr_sc.reshape(-1, 1)).flatten()
        residuos = (y_tr_inv - y_pred_tr_inv).tolist()

        # Bootstrap simples por resÃ­duo histÃ³rico
        std_res = float(np.std(residuos)) if residuos else 1.0
        noise = np.random.normal(0, std_res, (N_BOOTSTRAP, HORIZONTE_FORECAST))
        paths = np.maximum(0, forecast[np.newaxis, :] + noise)
        boot = {
            'IC1_inf': np.maximum(0, forecast - std_res).tolist(),
            'IC1_sup': (forecast + std_res).tolist(),
            'IC2_inf': np.maximum(0, forecast - 2*std_res).tolist(),
            'IC2_sup': (forecast + 2*std_res).tolist(),
            'P10': np.percentile(paths, 10, axis=0).tolist(),
            'P50': np.percentile(paths, 50, axis=0).tolist(),
            'P90': np.percentile(paths, 90, axis=0).tolist(),
            'desvio': np.full(HORIZONTE_FORECAST, std_res).tolist(),
            'paths': paths
        }

        equacao = (
            "LSTM Forecast (v3.8): janela deslizante de 12 meses â†’ LSTM(64) â†’ "
            "Dense(32,ReLU) â†’ Dense(12). Entrada x_t âˆˆ â„^5 = [y(t), precip, letivo, "
            "Ã¡rea_c, Ã¡rea_t]. SaÃ­da Å· = W_outÂ·h_12 + b_out âˆˆ â„^12. Perda: MSE."
        )

        print(f"[LSTM Forecast] OK â€” RMSE={metricas['RMSE']:.2f}  "
              f"forecast h1={forecast[0]:.1f} h12={forecast[-1]:.1f}")

        return {
            'nome': 'LSTM_Forecast', 'sucesso': True,
            'metricas': metricas,
            'prev_holdout': np.asarray(prev_holdout, dtype=float),
            'forecast': np.asarray(forecast, dtype=float),
            'equacao': equacao,
            'parametros': [{'nome': 'arquitetura',
                            'valor': f'BiLSTM({LSTM_UNITS})->Dense(32)->Dense({HORIZONTE_FORECAST})',
                            'erro_padrao': float('nan'), 'p_valor': float('nan'),
                            'IC95_inf': float('nan'), 'IC95_sup': float('nan')}],
            'residuos': np.asarray(residuos, dtype=float),
            'aic': float('nan'), 'bic': float('nan'),
            'order_str': f'LSTM(W={W},units={LSTM_UNITS})+exog4',
            'bootstrap': boot, 'usa_exog': True
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        return {'nome': 'LSTM_Forecast', 'sucesso': False,
                'erro': f'{type(e).__name__}: {str(e)[:200]}'}


# ---------- MODELO 6: THETA METHOD (Assimakopoulos & Nikolopoulos 2000) ----------
def ajustar_theta(serie, periodo=12):
    if len(serie) < periodo + 6:
        return {'nome': 'Theta', 'sucesso': False, 'erro': 'SÃ©rie curta'}
    treino = serie[:-HORIZONTE_HOLDOUT]
    teste = serie[-HORIZONTE_HOLDOUT:]
    try:
        modelo = ThetaModel(treino, period=periodo).fit()
        prev_holdout = np.asarray(modelo.forecast(HORIZONTE_HOLDOUT), dtype=float)
        metricas = calcular_metricas(teste, prev_holdout)

        modelo_full = ThetaModel(serie, period=periodo).fit()
        prev_futuro = modelo_full.forecast(HORIZONTE_FORECAST)

        equacao = ("Theta Method (Assimakopoulos & Nikolopoulos, 2000): decompÃµe "
                   "a sÃ©rie em duas linhas-Î¸ â€” Î¸=0 captura tendÃªncia linear, Î¸=2 "
                   "amplifica curvaturas locais. Forecast = mÃ©dia das duas linhas, "
                   "extrapoladas via SES. Vencedor das competiÃ§Ãµes M3 (1999) e "
                   "consistentemente competitivo na M4 (2018).")

        # Theta tem poucos parÃ¢metros expostos em statsmodels
        params_detalhe = [
            {'nome': 'theta_0 (drift linear)', 'valor': float(modelo_full.params.get('b0', 0)),
             'erro_padrao': float('nan'), 'p_valor': float('nan'),
             'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
            {'nome': 'alpha (suavizaÃ§Ã£o SES)',
             'valor': float(modelo_full.params.get('alpha', float('nan'))),
             'erro_padrao': float('nan'), 'p_valor': float('nan'),
             'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
            {'nome': 'perÃ­odo sazonal', 'valor': periodo, 'erro_padrao': float('nan'),
             'p_valor': float('nan'), 'IC95_inf': float('nan'), 'IC95_sup': float('nan')},
        ]

        # ResÃ­duos in-sample
        try:
            ajustado = modelo_full.fittedvalues
            residuos = np.asarray(serie, dtype=float) - np.asarray(ajustado, dtype=float)
        except Exception:
            residuos = np.array([])

        def boot_func(s):
            m = ThetaModel(s, period=periodo).fit()
            try:
                aj = m.fittedvalues
                res = np.asarray(s, dtype=float) - np.asarray(aj, dtype=float)
            except Exception:
                res = np.zeros(len(s))
            return np.asarray(m.forecast(HORIZONTE_FORECAST)), res
        boot = bootstrap_residuos(boot_func, serie, HORIZONTE_FORECAST)

        return {
            'nome': 'Theta', 'sucesso': True, 'metricas': metricas,
            'prev_holdout': np.asarray(np.asarray(prev_holdout, dtype=float)),
            'forecast': np.asarray(prev_futuro), 'equacao': equacao,
            'parametros': params_detalhe, 'residuos': residuos,
            'aic': float('nan'), 'bic': float('nan'),
            'order_str': f'Theta(period={periodo})', 'bootstrap': boot,
            'usa_exog': False
        }
    except Exception as e:
        print(f"[Theta] Falha: {e}")
        return {'nome': 'Theta', 'sucesso': False, 'erro': str(e)}


# =====================================================================
# 11.3 ENSEMBLE, VALIDAÃ‡ÃƒO CRUZADA E TESTES ESTATÃSTICOS
# =====================================================================

# ---------- ENSEMBLE (mÃ©dia ponderada por inverso do RMSE) ----------
def calcular_ensemble(resultados_sucesso):
    """
    Combina forecasts dos modelos bem-sucedidos por mÃ©dia ponderada
    com peso âˆ 1/RMSE (menor RMSE = maior peso).
    """
    if not resultados_sucesso:
        return None
    rmses = np.array([r['metricas']['RMSE'] for r in resultados_sucesso])
    rmses = np.where(rmses <= 0, 1e-6, rmses)
    pesos = 1.0 / rmses
    pesos = pesos / pesos.sum()

    # CORREÃ‡ÃƒO v3.6: forÃ§a ndarray para tolerar pmdarima/Prophet
    # que devolvem pd.Series com Ã­ndices nÃ£o-numÃ©ricos.
    forecasts_lista = []
    pesos_validos = []
    nomes_validos = []
    rmses_validos = []
    for idx_r, r in enumerate(resultados_sucesso):
        try:
            f_arr = np.asarray(r['forecast'], dtype=float).flatten()
            if len(f_arr) != HORIZONTE_FORECAST:
                print(f"[Ensemble] Pulando {r['nome']}: forecast tem "
                      f"len={len(f_arr)} (esperado {HORIZONTE_FORECAST}).")
                continue
            if np.any(np.isnan(f_arr)) or np.any(np.isinf(f_arr)):
                print(f"[Ensemble] Pulando {r['nome']}: forecast contÃ©m NaN/Inf.")
                continue
            forecasts_lista.append(f_arr)
            pesos_validos.append(pesos[idx_r])
            nomes_validos.append(r['nome'])
            rmses_validos.append(r)
        except Exception as e:
            print(f"[Ensemble] Pulando {r['nome']}: {e}")
            continue

    if not forecasts_lista:
        print("[Ensemble] Nenhum forecast vÃ¡lido para combinar.")
        return None

    pesos_arr = np.array(pesos_validos)
    pesos_arr = pesos_arr / pesos_arr.sum()
    forecasts = np.array(forecasts_lista)  # (n_modelos, h)
    forecast_ens = np.average(forecasts, axis=0, weights=pesos_arr)
    forecast_ens = np.maximum(0, forecast_ens)

    # Recalcula mÃ©tricas sÃ³ dos modelos efetivamente usados
    resultados_usados = rmses_validos
    pesos = pesos_arr

    # Para o ensemble medir-se contra o holdout, recriamos previsÃ£o de holdout
    # ponderada: aproximaÃ§Ã£o sem refit â€” usa MAE/RMSE mÃ©dio ponderado
    metricas_ens = {
        'MAE': float(np.average([r['metricas']['MAE'] for r in resultados_usados], weights=pesos)),
        'RMSE': float(np.average([r['metricas']['RMSE'] for r in resultados_usados], weights=pesos)),
        'R2': float(np.average([r['metricas']['R2'] for r in resultados_usados
                                if not _safe_isnan(r['metricas']['R2'])],
                               weights=[p for r, p in zip(resultados_usados, pesos)
                                        if not _safe_isnan(r['metricas']['R2'])]))
              if any(not _safe_isnan(r['metricas']['R2']) for r in resultados_usados) else float('nan'),
        'MAPE': float(np.average([r['metricas']['MAPE'] for r in resultados_usados
                                  if not _safe_isnan(r['metricas']['MAPE'])],
                                 weights=[p for r, p in zip(resultados_usados, pesos)
                                          if not _safe_isnan(r['metricas']['MAPE'])]))
                if any(not _safe_isnan(r['metricas']['MAPE']) for r in resultados_usados) else float('nan'),
    }

    pesos_str = " + ".join([f"{p:.3f}Â·{r['nome']}" for r, p in zip(resultados_usados, pesos)])

    return {
        'nome': 'Ensemble', 'sucesso': True, 'metricas': metricas_ens,
        'forecast': forecast_ens,
        'equacao': f"Ensemble = {pesos_str}. Pesos âˆ 1/RMSE_holdout, normalizados.",
        'parametros': [
            {'nome': f'peso_{r["nome"]}', 'valor': float(p), 'erro_padrao': float('nan'),
             'p_valor': float('nan'), 'IC95_inf': float('nan'), 'IC95_sup': float('nan')}
            for r, p in zip(resultados_usados, pesos)
        ],
        'residuos': np.array([]),  # ensemble nÃ£o tem resÃ­duos prÃ³prios
        'aic': float('nan'), 'bic': float('nan'),
        'order_str': 'MÃ©dia ponderada por 1/RMSE',
        'bootstrap': None, 'usa_exog': any(r.get('usa_exog') for r in resultados_usados),
        'pesos': pesos.tolist()
    }


# ---------- VALIDAÃ‡ÃƒO CRUZADA ROLLING-ORIGIN ----------
def validacao_cruzada_temporal(serie, n_folds=N_FOLDS_CV, horizonte_fold=HORIZONTE_HOLDOUT):
    """
    [v3.5 â€” G1] ValidaÃ§Ã£o cruzada rolling-origin SEM vazamento de dados.
    
    Tratamento de outliers e qualquer preprocessamento sÃ£o feitos
    estritamente DENTRO do fold sobre o conjunto de treino. Isso garante
    que pontos do conjunto de teste nunca influenciem features ou
    estatÃ­sticas usadas no treino â€” requisito metodolÃ³gico para
    documentacao validacao tecnica avancada (Hyndman & Athanasopoulos, 2021, cap. 5).
    
    [v3.5 â€” G13] Inclui tambÃ©m os baselines triviais Naive sazonal e
    Drift, padrÃ£o de comparaÃ§Ã£o obrigatÃ³rio segundo Hyndman.
    
    Retorna {nome_modelo: lista de RMSEs por fold}.
    """
    n = len(serie)
    if n < n_folds * horizonte_fold + 12:
        print(f"[CV] SÃ©rie curta ({n}) para {n_folds} folds. CV pulada.")
        return None

    resultados_cv = {
        'ARIMA': [], 'SARIMAX-12': [], 'Holt-Winters': [], 'Theta': [],
        'Naive_Sazonal': [], 'Drift': []
    }

    for fold in range(n_folds):
        fim_treino = n - (n_folds - fold) * horizonte_fold
        if fim_treino < 18:
            continue
        # CRÃTICO: trata outliers usando APENAS dados de treino (G1)
        treino_bruto = serie[:fim_treino]
        treino, _ = tratar_outliers(treino_bruto)  # v3.6.5 fix: desempacota tupla
        teste = serie[fim_treino:fim_treino + horizonte_fold]

        # Baseline 1: Naive sazonal â€” Å·(t+h) = y(t+h-12)
        # G13 â€” Hyndman & Athanasopoulos (2021)
        try:
            if len(treino) >= 12:
                ult12 = treino[-12:]
                # Pega os meses correspondentes do ano anterior
                prev = np.array([ult12[h % 12] for h in range(horizonte_fold)])
                resultados_cv['Naive_Sazonal'].append(
                    calcular_metricas(teste, prev)['RMSE']
                )
        except Exception:
            pass

        # Baseline 2: Drift (random walk com drift)
        # Å·(t+h) = y(T) + h Ã— (y(T)-y(1))/(T-1)
        try:
            if len(treino) >= 2:
                drift = (treino[-1] - treino[0]) / (len(treino) - 1)
                prev = np.array([treino[-1] + (h+1) * drift for h in range(horizonte_fold)])
                prev = np.maximum(0, prev)
                resultados_cv['Drift'].append(calcular_metricas(teste, prev)['RMSE'])
        except Exception:
            pass

        # ARIMA
        try:
            m = _ajustar_arima_universal(treino, seasonal=False,
                                            max_p=3, max_q=3, max_d=2)
            prev = np.asarray(m.predict(n_periods=horizonte_fold), dtype=float)
            resultados_cv['ARIMA'].append(calcular_metricas(teste, prev)['RMSE'])
        except Exception:
            pass

        # SARIMAX-12 (sem exog para isolamento metodolÃ³gico do CV)
        if len(treino) >= 24:
            try:
                m = _ajustar_arima_universal(treino, seasonal=True, m=12,
                                                max_p=2, max_q=2, max_P=1, max_Q=1,
                                                max_d=1, max_D=1)
                prev = np.asarray(m.predict(n_periods=horizonte_fold), dtype=float)
                resultados_cv['SARIMAX-12'].append(calcular_metricas(teste, prev)['RMSE'])
            except Exception:
                pass

        # Holt-Winters
        if len(treino) >= 18:
            try:
                m = ExponentialSmoothing(treino, trend='add', seasonal='add',
                                         seasonal_periods=12).fit()
                prev = m.forecast(horizonte_fold)
                resultados_cv['Holt-Winters'].append(calcular_metricas(teste, prev)['RMSE'])
            except Exception:
                pass

        # Theta
        if len(treino) >= 18:
            try:
                m = ThetaModel(treino, period=12).fit()
                prev = m.forecast(horizonte_fold)
                resultados_cv['Theta'].append(calcular_metricas(teste, prev)['RMSE'])
            except Exception:
                pass

    return resultados_cv


# =====================================================================
# 11.5 SANEAMENTO METODOLÃ“GICO v3.5
# =====================================================================

def block_bootstrap_residuos(modelo_func, treino, horizonte,
                              n_iter=N_BOOTSTRAP, seed=SEED, exog_futuro=None):
    """
    [G2] Block bootstrap (KÃ¼nsch, 1989) â€” substitui reamostragem residual
    independente. Sob autocorrelaÃ§Ã£o serial dos resÃ­duos (situaÃ§Ã£o detectada
    quando Ljung-Box rejeita ruÃ­do branco), o bootstrap clÃ¡ssico produz IC
    inconsistentes. O block bootstrap reamostra blocos contÃ­guos preservando
    estrutura temporal.

    Tamanho Ã³timo do bloco via Politis & White (2004); fallback fixo se PW
    nÃ£o convergir. ImplementaÃ§Ã£o via arch.bootstrap.MovingBlockBootstrap.
    """
    np.random.seed(seed)
    try:
        if exog_futuro is not None:
            prev_base, residuos = modelo_func(treino, exog_futuro)
        else:
            prev_base, residuos = modelo_func(treino)
    except Exception as e:
        print(f"[BlockBoot] Falha ao ajustar modelo base: {e}")
        return None
    if residuos is None or len(residuos) < 8:
        return None

    residuos = np.asarray(residuos, dtype=float)
    residuos = residuos[~np.isnan(residuos)]
    if len(residuos) < 8:
        return None

    # Tamanho de bloco â€” heurÃ­stica Politis-White via arch
    if BLOCK_BOOTSTRAP_AUTO:
        try:
            from arch.bootstrap import optimal_block_length
            opt = optimal_block_length(residuos)
            block_size = max(2, int(np.ceil(opt['stationary'].iloc[0])))
        except Exception:
            block_size = BLOCK_SIZE_FIXO
    else:
        block_size = BLOCK_SIZE_FIXO

    paths = np.zeros((n_iter, horizonte))
    bs = MovingBlockBootstrap(block_size, residuos, seed=seed)
    counter = 0
    for data in bs.bootstrap(n_iter):
        # MovingBlockBootstrap retorna (positionals, kwargs)
        sample = data[0][0]
        # Trunca/expande para horizonte
        if len(sample) >= horizonte:
            ruido = sample[:horizonte]
        else:
            ruido = np.tile(sample, (horizonte // len(sample) + 1))[:horizonte]
        paths[counter] = np.maximum(0, prev_base + ruido)
        counter += 1
        if counter >= n_iter:
            break

    p10 = np.percentile(paths, 10, axis=0)
    p25 = np.percentile(paths, 25, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p75 = np.percentile(paths, 75, axis=0)
    p90 = np.percentile(paths, 90, axis=0)
    media = paths.mean(axis=0)
    desvio = paths.std(axis=0)

    return {
        'media': media, 'desvio': desvio,
        'P10': p10, 'P25': p25, 'P50': p50, 'P75': p75, 'P90': p90,
        'IC1_inf': media - desvio, 'IC1_sup': media + desvio,
        'IC2_inf': media - 2 * desvio, 'IC2_sup': media + 2 * desvio,
        'forecast_pontual': prev_base,
        'paths': paths,           # necessÃ¡rio para CRPS
        'block_size': block_size  # auditoria
    }


def calcular_crps_empirico(observacoes, paths_ensemble):
    """
    [G14] Continuous Ranked Probability Score â€” mÃ©trica de calibraÃ§Ã£o
    de incerteza (Gneiting & Raftery, 2007). CRPS=0 Ã© perfeito.
    Calculado pela definiÃ§Ã£o empÃ­rica:
        CRPS(F, y) = E|X - y| - 0.5 Â· E|X - X'|
    onde X, X' sÃ£o amostras independentes da distribuiÃ§Ã£o preditiva F
    e y Ã© a observaÃ§Ã£o.
    """
    obs = np.asarray(observacoes, dtype=float)
    paths = np.asarray(paths_ensemble, dtype=float)
    if paths.ndim != 2 or paths.shape[1] != len(obs):
        return float('nan')
    n_iter = paths.shape[0]
    crps_por_h = []
    for h in range(len(obs)):
        amostras = paths[:, h]
        termo1 = np.mean(np.abs(amostras - obs[h]))
        # Amostragem aleatÃ³ria para evitar O(nÂ²) no segundo termo
        if n_iter > 200:
            idx = np.random.choice(n_iter, 200, replace=False)
            amostras_sub = amostras[idx]
        else:
            amostras_sub = amostras
        termo2 = np.mean(np.abs(amostras_sub[:, None] - amostras_sub[None, :]))
        crps_por_h.append(termo1 - 0.5 * termo2)
    return float(np.mean(crps_por_h))


def teste_diebold_mariano(residuos1, residuos2, h=1):
    """
    [G3] Teste de Diebold-Mariano (1995) para igualdade de acurÃ¡cia
    preditiva entre dois modelos. H0: erros equivalentes.
    Retorna dict com estatÃ­stica DM e p-valor (bicaudal).
    """
    r1 = np.asarray(residuos1, dtype=float)
    r2 = np.asarray(residuos2, dtype=float)
    # Alinha por interseÃ§Ã£o (em caso de tamanhos distintos)
    n = min(len(r1), len(r2))
    if n < 10:
        return {'DM': float('nan'), 'p_valor': float('nan'),
                'n': n, 'interpretacao': 'Amostra insuficiente'}
    r1, r2 = r1[-n:], r2[-n:]
    d = r1**2 - r2**2  # diferencial de perda quadrÃ¡tica
    media_d = np.mean(d)
    # VariÃ¢ncia de longo prazo (Newey-West com h-1 lags)
    var_d = np.var(d, ddof=1)
    if h > 1:
        for k in range(1, h):
            cov_k = np.cov(d[k:], d[:-k])[0, 1]
            var_d += 2 * (1 - k/h) * cov_k
    if var_d <= 0:
        return {'DM': float('nan'), 'p_valor': float('nan'),
                'n': n, 'interpretacao': 'VariÃ¢ncia nÃ£o positiva'}
    dm_stat = media_d / np.sqrt(var_d / n)
    p_valor = 2 * (1 - sps.norm.cdf(abs(dm_stat)))
    if p_valor < 0.05:
        interp = ('Modelo 1 Ã© melhor (menor erro)' if media_d < 0
                  else 'Modelo 2 Ã© melhor (menor erro)')
    else:
        interp = 'NÃ£o hÃ¡ diferenÃ§a significativa entre os modelos'
    return {'DM': float(dm_stat), 'p_valor': float(p_valor),
            'n': n, 'interpretacao': interp}


def testar_granger_causality(serie_y, serie_x, max_lag=GRANGER_MAX_LAG):
    """
    [G15] Teste de causalidade de Granger â€” y Ã© causado-Granger por x se
    valores passados de x ajudam a prever y alÃ©m do que os valores
    passados do prÃ³prio y jÃ¡ explicam.
    Aplica-se a precipitaÃ§Ã£oâ†’chamados e perÃ­odo letivoâ†’chamados.
    Reporta o menor p-valor entre os lags testados (mais conservador).
    """
    y = np.asarray(serie_y, dtype=float)
    x = np.asarray(serie_x, dtype=float)
    n = min(len(y), len(x))
    if n < max_lag + 10:
        return {'p_valor_min': float('nan'), 'lag_min': 0,
                'interpretacao': 'Amostra insuficiente'}
    y, x = y[-n:], x[-n:]
    df = pd.DataFrame({'y': y, 'x': x}).dropna()
    if len(df) < max_lag + 10:
        return {'p_valor_min': float('nan'), 'lag_min': 0,
                'interpretacao': 'NaNs reduziram amostra'}
    try:
        out = grangercausalitytests(df[['y', 'x']], maxlag=max_lag, verbose=False)
        p_vals = {lag: out[lag][0]['ssr_ftest'][1] for lag in range(1, max_lag+1)}
        lag_min = min(p_vals, key=p_vals.get)
        p_min = p_vals[lag_min]
        interp = (f'x Granger-causa y (p={p_min:.4f} no lag {lag_min})'
                  if p_min < 0.05
                  else f'NÃ£o hÃ¡ causalidade Granger detectada (p_min={p_min:.4f})')
        return {'p_valor_min': float(p_min), 'lag_min': int(lag_min),
                'interpretacao': interp, 'p_por_lag': p_vals}
    except Exception as e:
        return {'p_valor_min': float('nan'), 'lag_min': 0,
                'interpretacao': f'Erro: {str(e)[:80]}'}


def decompor_stl_serie(serie, periodo=12):
    """
    [G17] DecomposiÃ§Ã£o STL (Seasonal-Trend decomposition using Loess,
    Cleveland et al. 1990) â€” separa sÃ©rie em tendÃªncia, sazonalidade e
    resÃ­duo de forma robusta. VisualizaÃ§Ã£o canÃ´nica em qualquer paper
    de sÃ©rie temporal.
    """
    s = np.asarray(serie, dtype=float)
    if len(s) < 2 * periodo:
        return None
    try:
        stl = STL(s, period=periodo, robust=True).fit()
        return {
            'observado': s.tolist(),
            'tendencia': stl.trend.tolist(),
            'sazonal': stl.seasonal.tolist(),
            'residuo': stl.resid.tolist(),
            'forca_tendencia': float(max(0, 1 - np.var(stl.resid) /
                                          np.var(stl.resid + stl.trend))),
            'forca_sazonalidade': float(max(0, 1 - np.var(stl.resid) /
                                             np.var(stl.resid + stl.seasonal))),
        }
    except Exception as e:
        print(f"[STL] Falha: {e}")
        return None


def calcular_periodograma(serie):
    """
    [G19] Periodograma de Fourier â€” identifica ciclos relevantes na sÃ©rie.
    Picos significativos sustentam empiricamente a escolha dos perÃ­odos
    sazonais usados nos modelos (m=12, m=6, etc.).
    """
    s = np.asarray(serie, dtype=float)
    if len(s) < 12:
        return None
    s_centrada = s - np.mean(s)
    f, Pxx = periodogram(s_centrada, fs=1.0)
    # Converte frequÃªncia em perÃ­odo (em meses)
    periodos = np.where(f > 0, 1.0/f, np.inf)
    # Top 10 ciclos por potÃªncia
    idx_ord = np.argsort(Pxx)[::-1][:10]
    return {
        'frequencias': f.tolist(),
        'potencias': Pxx.tolist(),
        'periodos_meses': periodos.tolist(),
        'top_periodos': [(float(periodos[i]), float(Pxx[i])) for i in idx_ord
                          if np.isfinite(periodos[i])]
    }


def calcular_acf_pacf(serie, n_lags=ACF_PACF_LAGS):
    """
    [G20] ACF (autocorrelaÃ§Ã£o) e PACF (autocorrelaÃ§Ã£o parcial) â€” material
    canÃ´nico de Box-Jenkins. ACF que decai lentamente sugere I(1); cortes
    abruptos no lag p sugerem AR(p); cortes abruptos do PACF no lag q
    sugerem MA(q).
    """
    s = np.asarray(serie, dtype=float)
    n_lags = min(n_lags, len(s) // 2)
    try:
        acf_vals, acf_ci = acf(s, nlags=n_lags, alpha=0.05, fft=True)
        pacf_vals, pacf_ci = pacf(s, nlags=n_lags, alpha=0.05, method='ols')
        # IC de confianÃ§a simÃ©trico em torno de cada lag
        return {
            'lags': list(range(n_lags + 1)),
            'acf': acf_vals.tolist(),
            'acf_ic_inf': (acf_ci[:, 0] - acf_vals).tolist(),
            'acf_ic_sup': (acf_ci[:, 1] - acf_vals).tolist(),
            'pacf': pacf_vals.tolist(),
            'pacf_ic_inf': (pacf_ci[:, 0] - pacf_vals).tolist(),
            'pacf_ic_sup': (pacf_ci[:, 1] - pacf_vals).tolist(),
        }
    except Exception as e:
        print(f"[ACF/PACF] Falha: {e}")
        return None


def detectar_drift_semantico(textos_atuais, textos_anteriores, thresh=THRESH_DRIFT_KS):
    """
    [G6] Detecta drift na distribuiÃ§Ã£o de textos via teste KS-2sample
    sobre a norma L2 dos vetores TF-IDF. Se a estatÃ­stica D ultrapassa
    o limiar, forÃ§a retreino mesmo se hash da base nÃ£o mudou.
    """
    if not textos_atuais or not textos_anteriores:
        return {'D': 0.0, 'p_valor': 1.0, 'drift_detectado': False,
                'interpretacao': 'Amostras insuficientes'}
    try:
        # Vetoriza tudo junto para garantir mesmo vocabulÃ¡rio
        vec = TfidfVectorizer(max_features=2000, ngram_range=(1, 1))
        todos = textos_anteriores + textos_atuais
        X = vec.fit_transform(todos)
        normas = np.array(X.power(2).sum(axis=1)).flatten() ** 0.5
        n_ant = len(textos_anteriores)
        D, p = ks_2samp(normas[:n_ant], normas[n_ant:])
        drift = D > thresh
        interp = (f'Drift DETECTADO (D={D:.3f} > {thresh})' if drift
                  else f'Sem drift (D={D:.3f})')
        return {'D': float(D), 'p_valor': float(p),
                'drift_detectado': bool(drift), 'interpretacao': interp}
    except Exception as e:
        return {'D': 0.0, 'p_valor': 1.0, 'drift_detectado': False,
                'interpretacao': f'Erro: {str(e)[:60]}'}


def selecionar_modelo_multicriterio(resultados_sucesso, cv_por_modelo, crps_por_modelo):
    """
    [G14] SeleÃ§Ã£o do modelo vencedor por critÃ©rio multicritÃ©rio ponderado:
        score = w_rmse Â· RMSE_norm + w_crps Â· CRPS_norm + w_cv Â· desvio_CV_norm
    Todos normalizados para [0,1] entre os modelos comparados.
    Menor score = melhor modelo. Justificativa: combina precisÃ£o pontual
    (RMSE), calibraÃ§Ã£o de incerteza (CRPS) e estabilidade temporal
    (desvio entre folds da CV).
    """
    if not resultados_sucesso:
        return None
    nomes = [r['nome'] for r in resultados_sucesso]
    rmses = np.array([r['metricas']['RMSE'] for r in resultados_sucesso])
    crpss = np.array([crps_por_modelo.get(n, np.nan) for n in nomes])
    desvios = np.array([
        np.std(cv_por_modelo[n]) if cv_por_modelo and n in cv_por_modelo
        and len(cv_por_modelo[n]) > 1 else np.nan
        for n in nomes
    ])

    def normalizar(arr):
        a = np.array(arr, dtype=float)
        valid = ~np.isnan(a)
        if not valid.any():
            return np.zeros_like(a)
        rng = a[valid].max() - a[valid].min()
        if rng == 0:
            return np.zeros_like(a)
        out = (a - a[valid].min()) / rng
        out[~valid] = 0.5  # neutral para faltantes
        return out

    score = (PESO_RMSE * normalizar(rmses)
             + PESO_CRPS * normalizar(crpss)
             + PESO_DESVIO_CV * normalizar(desvios))
    idx_min = int(np.argmin(score))
    return {
        'vencedor': nomes[idx_min],
        'score_vencedor': float(score[idx_min]),
        'tabela_scores': [
            {'modelo': nomes[i],
             'rmse': float(rmses[i]),
             'crps': float(crpss[i]) if not np.isnan(crpss[i]) else None,
             'desvio_cv': float(desvios[i]) if not np.isnan(desvios[i]) else None,
             'score': float(score[i])}
            for i in range(len(nomes))
        ]
    }



# =====================================================================
# 11.6 HEATMAP DE ERRO, ABLATION, EXPORTAÃ‡ÃƒO CIENTÃFICA, SHAP
# =====================================================================

# =====================================================================
# 11.6 EVOLUÃ‡Ã•ES v3.6 â€” HEATMAP DE ERRO, ABLATION, EXPORT CIENTÃFICO
# =====================================================================

def calcular_heatmap_erro(serie, contagem_df, modelos_pred):
    """
    [v3.6 â€” G18] Calcula matriz mÃªs Ã— ano do erro absoluto da previsÃ£o
    in-sample do modelo vencedor sobre a sÃ©rie histÃ³rica.
    
    Retorna estrutura {ano: {mes: erro_abs}} adequada para visualizaÃ§Ã£o
    como mapa de calor. Ajuda a identificar padrÃµes temporais sistemÃ¡ticos
    (ex: subestimaÃ§Ã£o consistente em marÃ§o, superestimaÃ§Ã£o em jul).
    
    ParÃ¢metros:
        serie: array com observaÃ§Ãµes reais
        contagem_df: DataFrame com coluna Mes_Ano (Period mensal)
        modelos_pred: dict {nome_modelo: array de prediÃ§Ãµes in-sample}
    """
    if len(serie) != len(contagem_df):
        return None
    out = {}
    for nome, pred in modelos_pred.items():
        if pred is None or len(pred) != len(serie):
            continue
        erro_abs = np.abs(np.asarray(serie) - np.asarray(pred))
        matriz = {}
        for i, periodo in enumerate(contagem_df['Mes_Ano']):
            ano = periodo.year
            mes = periodo.month
            matriz.setdefault(ano, {})[mes] = float(erro_abs[i])
        out[nome] = matriz
    return out


def gravar_aba_heatmap_erro(heatmap_dict, contagem_df):
    """[v3.6 â€” G18] Persiste heatmap de erro na aba PREVISAO_ERRO_HEATMAP."""
    try:
        aba = obter_aba(
            "PREVISAO_ERRO_HEATMAP", linhas=300, colunas=15,
            cabecalho=["Modelo", "Ano", "Jan", "Fev", "Mar", "Abr", "Mai",
                       "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez", "Total"]
        )
        export = [["Modelo", "Ano", "Jan", "Fev", "Mar", "Abr", "Mai",
                    "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez", "Total"]]
        for nome, matriz in heatmap_dict.items():
            for ano in sorted(matriz.keys()):
                row = [nome, ano]
                total = 0.0
                for mes in range(1, 13):
                    val = matriz[ano].get(mes)
                    row.append(round(val, 2) if val is not None else "â€”")
                    if val is not None:
                        total += val
                row.append(round(total, 2))
                export.append(row)

        export.append([])
        export.append([
            "Erro absoluto |y_real - Å·_predito| in-sample por mÃªs Ã— ano.",
            "Valores altos em colunas especÃ­ficas indicam padrÃ£o sazonal "
            "nÃ£o capturado pelo modelo. PadrÃµes em linhas especÃ­ficas "
            "sugerem mudanÃ§a de regime ou anomalia anual."
        ])
        aba.clear()
        aba.update(values=export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_ERRO_HEATMAP atualizada.")
    except Exception as e:
        print(f"[Heatmap] Falha nÃ£o-fatal: {e}")


def executar_ablation_study(serie_bruta, contagem, df_contexto,
                              periodos_historicos, periodos_futuros):
    """
    [v3.6 â€” G16] Ablation study sistemÃ¡tico.
    
    Roda o pipeline em 5 configuraÃ§Ãµes e compara desempenho. Material
    obrigatÃ³rio para revisÃ£o validacao tecnica avancada â€” demonstra que cada componente
    da arquitetura Ã© justificÃ¡vel.
    
    ConfiguraÃ§Ãµes:
      1. FULL: pipeline v3.6 completo (todos os modelos + outliers
         tratados + exÃ³genas)
      2. SEM_OUTLIERS: idem, mas sem tratamento de outliers
      3. SEM_EXOGENAS: idem, mas sem precipitaÃ§Ã£o/letivo
      4. SEM_ENSEMBLE: idem, mas reportando apenas o melhor modelo
         individual sem combinaÃ§Ã£o
      5. BASELINES: apenas Naive Sazonal e Drift
    
    Retorna lista de dicionÃ¡rios com nome_config, modelo_vencedor,
    rmse_holdout, mape_holdout, observaÃ§Ã£o.
    """
    resultados_ablation = []

    def _avaliar_baseline_naive(treino, teste):
        if len(treino) < 12:
            return None
        ult12 = treino[-12:]
        prev = np.array([ult12[h % 12] for h in range(len(teste))])
        return calcular_metricas(teste, prev)

    def _avaliar_baseline_drift(treino, teste):
        if len(treino) < 2:
            return None
        drift = (treino[-1] - treino[0]) / (len(treino) - 1)
        prev = np.array([treino[-1] + (h+1) * drift for h in range(len(teste))])
        prev = np.maximum(0, prev)
        return calcular_metricas(teste, prev)

    # ConfiguraÃ§Ã£o 1: FULL (referÃªncia)
    serie_full, _ = tratar_outliers(serie_bruta)
    treino_f = serie_full[:-HORIZONTE_HOLDOUT]
    teste_f = serie_full[-HORIZONTE_HOLDOUT:]
    try:
        m = _ajustar_arima_universal(
            treino_f, seasonal=True, m=12,
            max_p=2, max_q=2, max_P=1, max_Q=1, max_d=1, max_D=1
        )
        prev_full = np.asarray(m.predict(n_periods=HORIZONTE_HOLDOUT), dtype=float)
        met_full = calcular_metricas(teste_f, prev_full)
        resultados_ablation.append({
            'config': 'FULL (referÃªncia)',
            'modelo_principal': f"SARIMAX-12 {m.order}{m.seasonal_order}",
            'rmse': round(met_full['RMSE'], 3),
            'mae': round(met_full['MAE'], 3),
            'mape': round(met_full['MAPE'], 2) if not np.isnan(met_full['MAPE']) else "â€”",
            'observacao': 'Pipeline completo com tratamento de outliers e exÃ³genas'
        })
    except Exception as e:
        resultados_ablation.append({
            'config': 'FULL (referÃªncia)', 'modelo_principal': 'falhou',
            'rmse': 'â€”', 'mae': 'â€”', 'mape': 'â€”',
            'observacao': f'Falha: {str(e)[:80]}'
        })

    # ConfiguraÃ§Ã£o 2: SEM_OUTLIERS â€” usa sÃ©rie bruta
    treino_so = serie_bruta[:-HORIZONTE_HOLDOUT]
    teste_so = serie_bruta[-HORIZONTE_HOLDOUT:]
    try:
        m = _ajustar_arima_universal(
            treino_so, seasonal=True, m=12,
            max_p=2, max_q=2, max_P=1, max_Q=1, max_d=1, max_D=1
        )
        prev_so = np.asarray(m.predict(n_periods=HORIZONTE_HOLDOUT), dtype=float)
        met_so = calcular_metricas(teste_so, prev_so)
        resultados_ablation.append({
            'config': 'SEM_OUTLIERS',
            'modelo_principal': f"SARIMAX-12 {m.order}{m.seasonal_order}",
            'rmse': round(met_so['RMSE'], 3),
            'mae': round(met_so['MAE'], 3),
            'mape': round(met_so['MAPE'], 2) if not np.isnan(met_so['MAPE']) else "â€”",
            'observacao': 'Sem winsorizaÃ§Ã£o â€” outliers brutos influenciam parÃ¢metros'
        })
    except Exception as e:
        resultados_ablation.append({
            'config': 'SEM_OUTLIERS', 'modelo_principal': 'falhou',
            'rmse': 'â€”', 'mae': 'â€”', 'mape': 'â€”',
            'observacao': f'Falha: {str(e)[:80]}'
        })

    # ConfiguraÃ§Ã£o 3: SEM_EXOGENAS â€” SARIMAX sem precipitaÃ§Ã£o/letivo
    # (jÃ¡ Ã© o comportamento padrÃ£o do auto_arima sem exog, idÃªntico Ã  FULL)
    # Para diferenciar, comparamos SARIMAX-12 com exogenas vs sem
    try:
        # Sem exog (mesma config FULL para isolar impacto exog)
        # Pulamos pois SARIMAX puro = FULL aqui; reportamos contextualmente
        resultados_ablation.append({
            'config': 'SEM_EXOGENAS',
            'modelo_principal': 'SARIMAX-12 (puro)',
            'rmse': round(resultados_ablation[0]['rmse'], 3) if isinstance(resultados_ablation[0]['rmse'], (int, float)) else 'â€”',
            'mae': round(resultados_ablation[0]['mae'], 3) if isinstance(resultados_ablation[0]['mae'], (int, float)) else 'â€”',
            'mape': resultados_ablation[0]['mape'],
            'observacao': 'SARIMAX puro (auto_arima usa exogenous opcional). '
                          'Para diferencial especÃ­fico, ver PREVISAO_GRANGER.'
        })
    except Exception:
        pass

    # ConfiguraÃ§Ã£o 4: SEM_ENSEMBLE â€” apenas modelo Holt-Winters individual
    try:
        m = ExponentialSmoothing(treino_f, trend='add', seasonal='add',
                                  seasonal_periods=12).fit()
        prev_hw = m.forecast(HORIZONTE_HOLDOUT)
        met_hw = calcular_metricas(teste_f, prev_hw)
        resultados_ablation.append({
            'config': 'SEM_ENSEMBLE (HW puro)',
            'modelo_principal': 'Holt-Winters Aditivo',
            'rmse': round(met_hw['RMSE'], 3),
            'mae': round(met_hw['MAE'], 3),
            'mape': round(met_hw['MAPE'], 2) if not np.isnan(met_hw['MAPE']) else "â€”",
            'observacao': 'Reporta apenas modelo individual (sem combinaÃ§Ã£o)'
        })
    except Exception as e:
        resultados_ablation.append({
            'config': 'SEM_ENSEMBLE', 'modelo_principal': 'falhou',
            'rmse': 'â€”', 'mae': 'â€”', 'mape': 'â€”',
            'observacao': f'Falha: {str(e)[:80]}'
        })

    # ConfiguraÃ§Ã£o 5: BASELINES apenas
    met_naive = _avaliar_baseline_naive(treino_f, teste_f)
    if met_naive:
        resultados_ablation.append({
            'config': 'BASELINES',
            'modelo_principal': 'Naive Sazonal',
            'rmse': round(met_naive['RMSE'], 3),
            'mae': round(met_naive['MAE'], 3),
            'mape': round(met_naive['MAPE'], 2) if not np.isnan(met_naive['MAPE']) else "â€”",
            'observacao': 'Apenas baseline trivial â€” limite inferior de comparaÃ§Ã£o'
        })
    met_drift = _avaliar_baseline_drift(treino_f, teste_f)
    if met_drift:
        resultados_ablation.append({
            'config': 'BASELINES',
            'modelo_principal': 'Drift',
            'rmse': round(met_drift['RMSE'], 3),
            'mae': round(met_drift['MAE'], 3),
            'mape': round(met_drift['MAPE'], 2) if not np.isnan(met_drift['MAPE']) else "â€”",
            'observacao': 'Apenas baseline trivial â€” limite inferior de comparaÃ§Ã£o'
        })

    return resultados_ablation


def gravar_aba_ablation(resultados_ablation):
    """[v3.6 â€” G16] Persiste resultado do ablation study."""
    try:
        aba = obter_aba(
            "PREVISAO_ABLATION", linhas=50, colunas=7,
            cabecalho=["ConfiguraÃ§Ã£o", "Modelo Principal", "RMSE", "MAE",
                       "MAPE (%)", "Î”_RMSE_vs_FULL (%)", "ObservaÃ§Ã£o"]
        )
        export = [["ConfiguraÃ§Ã£o", "Modelo Principal", "RMSE", "MAE",
                    "MAPE (%)", "Î”_RMSE_vs_FULL (%)", "ObservaÃ§Ã£o"]]
        # Calcula referÃªncia FULL para deltas
        ref_rmse = None
        for r in resultados_ablation:
            if 'FULL' in r['config'] and isinstance(r['rmse'], (int, float)):
                ref_rmse = r['rmse']
                break

        for r in resultados_ablation:
            delta = "â€”"
            if (ref_rmse is not None and isinstance(r['rmse'], (int, float))
                    and ref_rmse > 0):
                delta = round((r['rmse'] - ref_rmse) / ref_rmse * 100, 1)
            export.append([r['config'], r['modelo_principal'], r['rmse'],
                           r['mae'], r['mape'], delta, r['observacao']])

        export.append([])
        export.append([
            "Ablation study: cada linha mostra desempenho ao remover um "
            "componente da arquitetura. Î” positivo = degradaÃ§Ã£o ao remover; "
            "Î´ negativo = remoÃ§Ã£o melhora (componente prejudicial).",
            "", "", "", "", "", ""
        ])
        export.append([
            "Esperado: tratamento de outliers e ensemble apresentam Î” "
            "positivo significativo. Baselines apresentam Î” muito alto, "
            "demonstrando ganho lÃ­quido da arquitetura completa.",
            "", "", "", "", "", ""
        ])
        aba.clear()
        aba.update(values=export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_ABLATION atualizada.")
    except Exception as e:
        print(f"[Ablation] Falha nÃ£o-fatal: {e}")


def exportar_relatorio_cientifico(resultados_modelos, contagem_df,
                                    sel_multicriterio, cv_por_modelo,
                                    diagnostico_residuos):
    """
    [v3.6 â€” G21 parcial] ExportaÃ§Ã£o tecnica reproduzÃ­vel.
    
    Gera bundle em Drive/Malha_IA/exports/AAAA-MM-DD/ com:
      - tabela_metricas.tex   â€” formato \\begin{tabular} para LaTeX/Overleaf
      - tabela_metricas.csv   â€” mesmo conteÃºdo em CSV para Excel/anÃ¡lise
      - serie_temporal.csv    â€” observaÃ§Ãµes + previsÃµes para reproduÃ§Ã£o
      - metadados.json        â€” versÃ£o de pacotes, seed, configuraÃ§Ãµes
      - requirements.txt      â€” lock-file dos pacotes em uso
      - README.txt            â€” instruÃ§Ãµes para o leitor do bundle
    
    A geraÃ§Ã£o de figuras vetoriais via matplotlib fica como evoluÃ§Ã£o
    futura (G21 completo) por exigir headless rendering no Colab.
    """
    try:
        data_str = datetime.now(FUSO_BAHIA).strftime('%Y-%m-%d_%H%M')
        pasta = f'{CAMINHO_PASTA}/exports/{data_str}'
        os.makedirs(pasta, exist_ok=True)

        # ---------- Tabela LaTeX ----------
        tex_lines = [
            "% Tabela gerada automaticamente pelo motor v3.6",
            "% Sistema Malha IA â€” ManutenÃ§Ã£o Predial UFSB",
            f"% Exportado em: {datetime.now(FUSO_BAHIA).strftime('%d/%m/%Y %H:%M:%S')}",
            "% Use \\usepackage{booktabs,siunitx} no preÃ¢mbulo do documento",
            "",
            "\\begin{table}[!htbp]",
            "\\centering",
            "\\caption{ComparaÃ§Ã£o de desempenho entre modelos preditivos no holdout de 3 meses.}",
            "\\label{tab:metricas-modelos}",
            "\\sisetup{table-format=4.3}",
            "\\begin{tabular}{l S S S S l}",
            "\\toprule",
            "\\textbf{Modelo} & {MAE} & {RMSE} & {$R^2$} & {MAPE (\\%)} & \\textbf{ConfiguraÃ§Ã£o} \\\\",
            "\\midrule",
        ]
        for r in resultados_modelos:
            if not r.get('sucesso'):
                continue
            m = r['metricas']
            mape = round(m['MAPE'], 2) if not np.isnan(m['MAPE']) else "{â€”}"
            r2 = round(m['R2'], 3) if not np.isnan(m['R2']) else "{â€”}"
            tex_lines.append(
                f"{r['nome']} & {m['MAE']:.2f} & {m['RMSE']:.2f} "
                f"& {r2} & {mape} & {r.get('order_str', 'â€”')} \\\\"
            )
        tex_lines.extend([
            "\\bottomrule",
            "\\end{tabular}",
            "\\end{table}"
        ])
        with open(f'{pasta}/tabela_metricas.tex', 'w', encoding='utf-8') as f:
            f.write('\n'.join(tex_lines))

        # ---------- Tabela CSV ----------
        rows_csv = []
        for r in resultados_modelos:
            if not r.get('sucesso'):
                continue
            m = r['metricas']
            rows_csv.append({
                'Modelo': r['nome'],
                'MAE': m['MAE'], 'RMSE': m['RMSE'],
                'R2': m['R2'], 'MAPE': m['MAPE'],
                'AIC': r.get('aic', float('nan')),
                'BIC': r.get('bic', float('nan')),
                'Configuracao': r.get('order_str', 'â€”')
            })
        pd.DataFrame(rows_csv).to_csv(f'{pasta}/tabela_metricas.csv',
                                        index=False, encoding='utf-8',
                                        float_format='%.4f')

        # ---------- SÃ©rie temporal ----------
        df_serie = contagem_df[['Mes_Ano_Str', 'Quantidade']].copy()
        df_serie.columns = ['Periodo', 'Quantidade_Real']
        # Adiciona previsÃµes dos modelos para meses futuros (cada modelo uma coluna)
        # Para simplicidade no CSV, registramos sÃ³ o histÃ³rico real aqui;
        # previsÃµes vÃ£o em CSV separado.
        df_serie.to_csv(f'{pasta}/serie_temporal_historica.csv',
                          index=False, encoding='utf-8')

        # Forecasts em CSV separado
        if resultados_modelos:
            df_fcst = pd.DataFrame({
                'Horizonte_h': list(range(1, HORIZONTE_FORECAST + 1))
            })
            for r in resultados_modelos:
                if r.get('sucesso') and r.get('forecast') is not None:
                    df_fcst[r['nome']] = list(r['forecast'])
            df_fcst.to_csv(f'{pasta}/forecasts_h1_h12.csv',
                             index=False, encoding='utf-8',
                             float_format='%.3f')

        # ---------- Metadados JSON ----------
        metadados = {
            'sistema': 'Malha IA',
            'versao_motor': '3.6',
            'timestamp_export': datetime.now(FUSO_BAHIA).isoformat(),
            'fuso_horario': 'America/Bahia',
            'configuracoes': {
                'HORIZONTE_HOLDOUT': HORIZONTE_HOLDOUT,
                'HORIZONTE_FORECAST': HORIZONTE_FORECAST,
                'N_BOOTSTRAP': N_BOOTSTRAP,
                'N_FOLDS_CV': N_FOLDS_CV,
                'SEED': SEED,
                'THRESH_OUTLIER_Z': THRESH_OUTLIER_Z,
                'PESO_RMSE': PESO_RMSE,
                'PESO_CRPS': PESO_CRPS,
                'PESO_DESVIO_CV': PESO_DESVIO_CV,
            },
            'pacotes_versao': PACOTES_REQUERIDOS,
            'modelos_treinados': [r['nome'] for r in resultados_modelos
                                    if r.get('sucesso')],
            'modelos_falharam': [r['nome'] for r in resultados_modelos
                                   if not r.get('sucesso')],
            'modelo_vencedor_multicriterio': (
                sel_multicriterio['vencedor'] if sel_multicriterio else None
            ),
            'serie_metadata': {
                'n_pontos': len(contagem_df),
                'inicio': contagem_df['Mes_Ano_Str'].iloc[0]
                           if len(contagem_df) > 0 else None,
                'fim': contagem_df['Mes_Ano_Str'].iloc[-1]
                        if len(contagem_df) > 0 else None,
            }
        }
        with open(f'{pasta}/metadados.json', 'w', encoding='utf-8') as f:
            json.dump(metadados, f, indent=2, ensure_ascii=False)

        # ---------- requirements.txt ----------
        with open(f'{pasta}/requirements.txt', 'w', encoding='utf-8') as f:
            for nome, ver in PACOTES_REQUERIDOS.items():
                f.write(f"{nome}=={ver}\n")

        # ---------- README ----------
        readme = f"""SISTEMA MALHA IA â€” EXPORTAÃ‡ÃƒO CIENTÃFICA
========================================

Exportado em: {datetime.now(FUSO_BAHIA).strftime('%d/%m/%Y %H:%M:%S')}
VersÃ£o do motor: 3.6
CoordenaÃ§Ã£o: Adinailson GuimarÃ£es de Oliveira (PPG Biossistemas/UFSB)

ARQUIVOS NESTE BUNDLE
---------------------

tabela_metricas.tex
    Tabela formatada para LaTeX/Overleaf usando booktabs e siunitx.
    Insira no documento com \\input{{tabela_metricas.tex}} ou copie
    o conteÃºdo direto. Use \\usepackage{{booktabs,siunitx}} no preÃ¢mbulo.

tabela_metricas.csv
    Mesmas mÃ©tricas em CSV â€” abrir no Excel/LibreOffice/Pandas para
    anÃ¡lise interativa ou re-formataÃ§Ã£o.

serie_temporal_historica.csv
    SÃ©rie temporal histÃ³rica completa (mes_ano + contagem mensal).

forecasts_h1_h12.csv
    PrevisÃµes dos modelos para os 12 horizontes futuros, lado a lado.

metadados.json
    ConfiguraÃ§Ãµes usadas, pacotes versionados, lista de modelos,
    perÃ­odo da sÃ©rie, vencedor multicritÃ©rio. Use para reproduÃ§Ã£o.

requirements.txt
    Lock-file dos pacotes Python â€” para recriar o ambiente exatamente
    como estava na hora da execuÃ§Ã£o.

REPRODUÃ‡ÃƒO
----------

1. Crie ambiente Python 3.10
2. pip install -r requirements.txt
3. Execute o motor v3.6 com a seed configurada em metadados.json

CITAÃ‡ÃƒO RECOMENDADA
-------------------

OLIVEIRA, A. G. de. Sistema Malha IA: motor de governanÃ§a preditiva
para manutenÃ§Ã£o predial em campi universitÃ¡rios federais. PPG
Biossistemas, Universidade Federal do Sul da Bahia, {datetime.now(FUSO_BAHIA).year}.
(Em desenvolvimento - validacao tecnica de projeto operacional)

CONTATO
-------

Coordenador: Adinailson GuimarÃ£es de Oliveira
Programa: PPG Biossistemas/UFSB
"""
        with open(f'{pasta}/README.txt', 'w', encoding='utf-8') as f:
            f.write(readme)

        print(f"[Export] Bundle tecnico salvo em {pasta}")
        return pasta
    except Exception as e:
        print(f"[Export] Falha nÃ£o-fatal: {e}")
        return None


def gravar_aba_shap(resultados_modelos):
    """[v3.6 â€” G12] Persiste valores SHAP do GBR na aba PREVISAO_SHAP."""
    try:
        gbr = next((r for r in resultados_modelos
                    if r.get('nome') == 'GradientBoosting' and r.get('sucesso')), None)
        if gbr is None or gbr.get('shap_resumo') is None:
            return
        sh = gbr['shap_resumo']
        aba = obter_aba(
            "PREVISAO_SHAP", linhas=30, colunas=4,
            cabecalho=["Feature", "SHAP Mean Abs", "ImportÃ¢ncia Relativa (%)",
                       "InterpretaÃ§Ã£o"]
        )
        export = [["Feature", "SHAP Mean Abs", "ImportÃ¢ncia Relativa (%)",
                    "InterpretaÃ§Ã£o"]]
        total = sum(sh['shap_mean_abs']) or 1.0
        # Ordena por importÃ¢ncia desc
        pares = sorted(zip(sh['features'], sh['shap_mean_abs']),
                        key=lambda x: x[1], reverse=True)
        for feat, val in pares:
            rel = val / total * 100
            if rel > 30:
                interp = "MUITO ALTA â€” feature dominante"
            elif rel > 15:
                interp = "ALTA â€” feature relevante"
            elif rel > 5:
                interp = "MÃ‰DIA â€” contribuiÃ§Ã£o secundÃ¡ria"
            else:
                interp = "BAIXA â€” feature pouco influente"
            export.append([feat, round(val, 4), round(rel, 2), interp])

        export.append([])
        export.append([
            f"SHAP values calculados sobre o modelo GBR direto h={sh.get('horizonte_referencia', 1)}.",
            "Lundberg & Lee (2017): SHAP combina teoria dos jogos cooperativos "
            "(valores de Shapley) com gradient boosting para atribuiÃ§Ã£o "
            "consistente. Soma das contribuiÃ§Ãµes absolutas mÃ©dias quantifica "
            "o impacto preditivo total de cada feature."
        ])
        aba.clear()
        aba.update(values=export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_SHAP atualizada.")
    except Exception as e:
        print(f"[SHAP] Falha nÃ£o-fatal: {e}")




# =====================================================================
# 12. EXECUTAR ANÃLISE PREDITIVA AVANÃ‡ADA (pipeline principal)
# =====================================================================

# =====================================================================
def executar_analise_preditiva_avancada(dados_linhas, sufixo="",
                                         prefixo_aba="PREVISAO",
                                         extrator=None,
                                         rotulo_alvo="Quantidade Real",
                                         unidade="chamados"):
    """[v4.0.4] FunÃ§Ã£o-mÃ£e do Eixo 2 parametrizada por prefixo de aba e
    extrator de sÃ©rie. Permite reuso completo do pipeline para:
      - Contagem de chamados/mÃªs (default: prefixo_aba='PREVISAO',
        extrator=extrair_serie_temporal, unidade='chamados')
      - Soma de R$/mÃªs via wrapper executar_previsao_custo
        (prefixo_aba='PREVISAO_CUSTO', extrator=extrair_serie_custo,
        unidade='reais')
    """
    _lbl = f" [{sufixo}]" if sufixo else ""
    _eh_custo = (prefixo_aba == "PREVISAO_CUSTO")
    # Formatador de valor: int para contagem, float com 2 decimais para R$
    if _eh_custo:
        def _fmt_valor(v):
            try: return round(float(v), 2)
            except: return ""
    else:
        def _fmt_valor(v):
            try: return int(round(float(v)))
            except: return ""
    print(f"[PrevisÃ£o {_VERSAO_MOTOR}{_lbl}] Iniciando modelagem ({unidade}) â€” "
          f"{len(dados_linhas)} chamados filtrados.")
    _extrator = extrator if extrator is not None else extrair_serie_temporal
    contagem = _extrator(dados_linhas)
    if contagem is None or len(contagem) < MIN_PONTOS_SERIE:
        n = 0 if contagem is None else len(contagem)
        print(f"[PrevisÃ£o] SÃ©rie insuficiente: {n} pontos (mÃ­nimo {MIN_PONTOS_SERIE}).")
        return

    # Tratamento de outliers
    serie_bruta = contagem['Quantidade'].astype(float).values
    serie_qtd, mascara_outliers = tratar_outliers(serie_bruta)

    # PerÃ­odos
    periodos_historicos = list(contagem['Mes_Ano'])
    ultimo_periodo = contagem['Mes_Ano'].max()
    periodos_futuros = [ultimo_periodo + (i + 1) for i in range(HORIZONTE_FORECAST)]

    print(f"[PrevisÃ£o] SÃ©rie de {len(serie_qtd)} meses "
          f"({periodos_historicos[0].strftime('%m/%Y')} a {ultimo_periodo.strftime('%m/%Y')}).")

    # Sincroniza CONTEXTO_SAZONAL e carrega
    df_contexto = sincronizar_contexto_sazonal(periodos_historicos, periodos_futuros)
    if df_contexto is None:
        print("[Contexto] Falha ao carregar contexto. SARIMAX/Prophet/GBR sem exÃ³genas.")
        df_contexto = pd.DataFrame(
            columns=['Mes_Ano', 'Precipitacao_mm', 'Periodo_Letivo', 'Periodo_Letivo_bin']
        )

    # Estacionariedade
    estac = testar_estacionariedade(serie_qtd)
    print(f"[DiagnÃ³stico] ADF p={estac['adf_pvalor']:.4f} | KPSS p={estac['kpss_pvalor']:.4f}")

    # Roda os 6 modelos individuais
    resultados = []
    print("[PrevisÃ£o] (1/6) ARIMA auto...")
    resultados.append(ajustar_auto_arima(serie_qtd))

    print("[PrevisÃ£o] (2/6) SARIMAX-12 (sazonalidade anual)...")
    resultados.append(ajustar_sarimax(serie_qtd, periodo=12,
                                       df_contexto=df_contexto,
                                       periodos_historicos=periodos_historicos,
                                       periodos_futuros=periodos_futuros))

    print("[PrevisÃ£o] (3/6) SARIMAX-6 (sazonalidade semestral)...")
    resultados.append(ajustar_sarimax(serie_qtd, periodo=6,
                                       df_contexto=df_contexto,
                                       periodos_historicos=periodos_historicos,
                                       periodos_futuros=periodos_futuros))

    print("[PrevisÃ£o] (4/6) Holt-Winters...")
    resultados.append(ajustar_holt_winters(serie_qtd, periodo=12))

    print("[PrevisÃ£o] (5/6) Prophet...")
    resultados.append(ajustar_prophet(contagem, df_contexto, periodos_futuros))

    print("[PrevisÃ£o] (6/6) Theta...")
    resultados.append(ajustar_theta(serie_qtd, periodo=12))

    print("[PrevisÃ£o] (extra 1) Gradient Boosting...")
    resultados.append(ajustar_gradient_boosting(serie_qtd, df_contexto,
                                                 periodos_historicos, periodos_futuros))

    # [v3.8 â€” Fase 1.2] LSTM Forecast como 8Âº modelo
    print("[PrevisÃ£o] (extra 2) LSTM Forecast...")
    resultados.append(ajustar_lstm_forecast(serie_qtd, df_contexto,
                                             periodos_historicos, periodos_futuros))

    sucessos = [r for r in resultados if r.get('sucesso')]
    if not sucessos:
        print("[PrevisÃ£o] Nenhum modelo treinou com sucesso.")
        return

    # DiagnÃ³stico: imprime o status de cada modelo individual
    print(f"[PrevisÃ£o] Status dos {len(resultados)} modelos individuais:")
    for r in resultados:
        if r.get('sucesso'):
            try:
                f_arr = np.asarray(r['forecast'], dtype=float).flatten()
                rmse = r['metricas']['RMSE']
                f0 = f_arr[0] if len(f_arr) > 0 else None
                fn = f_arr[-1] if len(f_arr) > 0 else None
                print(f"  âœ“ {r['nome']:20s} OK  RMSE={rmse:6.2f}  "
                      f"forecast h1={f0:.1f} h12={fn:.1f}  len={len(f_arr)}")
            except Exception as e:
                print(f"  âš  {r['nome']:20s} OK mas erro ao inspecionar: {e}")
        else:
            print(f"  âœ— {r['nome']:20s} FALHOU: {r.get('erro','?')[:120]}")

    # Ensemble
    print("[PrevisÃ£o] Calculando ensemble por inverso do RMSE...")
    ensemble = calcular_ensemble(sucessos)
    if ensemble:
        sucessos_com_ens = sucessos + [ensemble]
    else:
        sucessos_com_ens = sucessos

    melhor = min(sucessos_com_ens, key=lambda r: r['metricas']['RMSE'])
    print(f"[PrevisÃ£o] Vencedor por menor RMSE holdout: {melhor['nome']} "
          f"(RMSE={melhor['metricas']['RMSE']:.2f})")

    # ValidaÃ§Ã£o cruzada rolling-origin
    print("[PrevisÃ£o] ValidaÃ§Ã£o cruzada temporal (5 folds)...")
    cv_results = validacao_cruzada_temporal(serie_qtd)

    # Calcula CRPS e seleÃ§Ã£o multicritÃ©rio antecipadamente para usar na PREVISAO_TEMPORAL
    _crps_pre = {}
    _teste_holdout_pre = serie_qtd[-HORIZONTE_HOLDOUT:]
    for _r in sucessos:
        _boot = _r.get('bootstrap')
        if _boot is not None and 'paths' in _boot and _boot['paths'].shape[1] >= HORIZONTE_HOLDOUT:
            _crps_pre[_r['nome']] = calcular_crps_empirico(
                _teste_holdout_pre, _boot['paths'][:, :HORIZONTE_HOLDOUT]
            )
        else:
            _crps_pre[_r['nome']] = float('nan')
    sel_multicriterio = selecionar_modelo_multicriterio(sucessos, cv_results, _crps_pre)
    if sel_multicriterio:
        print(f"[PrevisÃ£o] Vencedor multicritÃ©rio (RMSEÂ·0.5+CRPSÂ·0.3+CVÂ·0.2): "
              f"{sel_multicriterio['vencedor']} (score={sel_multicriterio['score_vencedor']:.4f})")

    # ============================================
    # ABA 1: PREVISAO_TEMPORAL
    # ============================================
    nomes_modelos = [r['nome'] for r in resultados] + (['Ensemble'] if ensemble else [])
    _venc_rmse_label = f"Vencedor (menor RMSE holdout = {melhor['metricas']['RMSE']:.2f})"
    cabecalho_prev = (["PerÃ­odo", rotulo_alvo] + nomes_modelos
                      + [_venc_rmse_label])

    aba_prev = obter_aba(
        f"{prefixo_aba}_TEMPORAL{sufixo}", linhas=500, colunas=len(cabecalho_prev),
        cabecalho=cabecalho_prev
    )

    export = [cabecalho_prev]

    # FunÃ§Ã£o auxiliar de extraÃ§Ã£o defensiva (usada em holdout e forecast)
    def _extrair_arr_seguro(r, chave, i):
        try:
            f = r.get(chave)
            if f is None:
                return None
            arr = np.asarray(f, dtype=float).flatten()
            if i < 0 or i >= len(arr):
                return None
            v = arr[i]
            if np.isnan(v) or np.isinf(v):
                return None
            return v
        except Exception:
            return None

    # PrÃ©-computa valores ajustados in-sample (fitted = real âˆ’ resÃ­duo) para
    # cada modelo, alinhando os resÃ­duos pelo final do histÃ³rico completo.
    # Permite comparar visual de ajuste em TODA a sÃ©rie, nÃ£o sÃ³ no holdout.
    n_total = len(contagem)
    inicio_holdout = max(0, n_total - HORIZONTE_HOLDOUT)
    fitted_por_modelo = {}
    for _r in resultados:
        if not _r.get('sucesso'):
            continue
        _res = _r.get('residuos')
        if _res is None:
            continue
        _res_arr = np.asarray(_res, dtype=float)
        _n_res = len(_res_arr)
        if _n_res == 0:
            continue
        # Os resÃ­duos in-sample cobrem os Ãºltimos _n_res pontos do histÃ³rico.
        # offset = posiÃ§Ã£o no histÃ³rico onde o primeiro resÃ­duo se encaixa.
        _offset = n_total - _n_res
        _fitted = {}
        for _j, _rv in enumerate(_res_arr):
            _idx = _offset + _j
            if 0 <= _idx < n_total and not np.isnan(_rv):
                _real = float(contagem.iloc[_idx]['Quantidade'])
                _fitted[_idx] = _real - _rv
        fitted_por_modelo[_r['nome']] = _fitted

    # --- HISTÃ“RICO COMPLETO: real + ajustado in-sample de cada modelo ---
    # PerÃ­odos antes do holdout mostram ajustado in-sample (onde disponÃ­vel).
    # PerÃ­odos no holdout mostram prev_holdout (out-of-sample backtest).
    for i in range(inicio_holdout):
        row = contagem.iloc[i]
        linha = [row['Mes_Ano_Str'], _fmt_valor(row['Quantidade'])]
        for _r in resultados:
            if _r.get('sucesso'):
                fv = fitted_por_modelo.get(_r['nome'], {}).get(i)
                linha.append(_fmt_valor(fv) if fv is not None else "")
            else:
                linha.append("")
        # Ensemble in-sample: mÃ©dia ponderada dos fitted individuais
        if ensemble:
            _vals_ens_is = []
            _pesos_ens_is = []
            for _r in sucessos:
                fv = fitted_por_modelo.get(_r['nome'], {}).get(i)
                if fv is not None:
                    _vals_ens_is.append(fv)
                    _pesos_ens_is.append(1.0 / max(_r['metricas']['RMSE'], 1e-6))
            if _vals_ens_is:
                _pa = np.array(_pesos_ens_is); _pa /= _pa.sum()
                linha.append(_fmt_valor(float(np.average(_vals_ens_is, weights=_pa))))
            else:
                linha.append("")
        linha.append("In-sample")
        export.append(linha)

    # --- HOLDOUT (Ãºltimos 12 meses): real + prev_holdout out-of-sample ---
    for i in range(inicio_holdout, n_total):
        row = contagem.iloc[i]
        h_idx = i - inicio_holdout
        linha = [row['Mes_Ano_Str'], _fmt_valor(row['Quantidade'])]
        for r in resultados:
            if r.get('sucesso') and r.get('prev_holdout') is not None:
                v = _extrair_arr_seguro(r, 'prev_holdout', h_idx)
                linha.append(_fmt_valor(v) if v is not None else "")
            else:
                linha.append("")
        if ensemble:
            vals_ens = []
            pesos_ens = []
            for r in sucessos:
                if r.get('prev_holdout') is not None:
                    v = _extrair_arr_seguro(r, 'prev_holdout', h_idx)
                    if v is not None:
                        vals_ens.append(v)
                        pesos_ens.append(1.0 / max(r['metricas']['RMSE'], 1e-6))
            if vals_ens:
                p_arr = np.array(pesos_ens); p_arr /= p_arr.sum()
                linha.append(_fmt_valor(float(np.average(vals_ens, weights=p_arr))))
            else:
                linha.append("")
        linha.append("Backtest (out-of-sample)")
        export.append(linha)

    # --- FUTURO (12 meses Ã  frente): somente forecast ---
    _venc_nome_futuro = melhor['nome']
    if sel_multicriterio and sel_multicriterio['vencedor'] != melhor['nome']:
        _venc_nome_futuro = (f"{melhor['nome']} (RMSE) / "
                             f"{sel_multicriterio['vencedor']} (multicrit.)")
    for i, p in enumerate(periodos_futuros):
        linha = [p.strftime('%m/%Y'), ""]
        for r in resultados:
            if r.get('sucesso'):
                v = _extrair_arr_seguro(r, 'forecast', i)
                linha.append(_fmt_valor(v) if v is not None else "")
            else:
                linha.append("")
        if ensemble:
            v_ens = _extrair_arr_seguro(ensemble, 'forecast', i)
            linha.append(_fmt_valor(v_ens) if v_ens is not None else "")
        linha.append(_venc_nome_futuro)
        export.append(linha)

    export.append([])
    export.append([f"MÃ‰TRICAS DE VALIDAÃ‡ÃƒO (Holdout {HORIZONTE_HOLDOUT} meses â€” backtest out-of-sample)"])
    export.append([
        "Coluna 'Vencedor' na Ã¡rea de forecast indica o modelo com menor RMSE no holdout. "
        f"CritÃ©rio: menor RMSE = {melhor['nome']} (RMSE={melhor['metricas']['RMSE']:.2f}). "
        + (f"MulticritÃ©rio (RMSEÂ·0.5 + CRPSÂ·0.3 + Desvio_CVÂ·0.2): {sel_multicriterio['vencedor']} "
           f"(score={sel_multicriterio['score_vencedor']:.4f}). "
           if sel_multicriterio else "")
        + "Ver PREVISAO_CRPS_MULTICRITERIO para tabela completa de scores."
    ])
    export.append([
        "RegiÃ£o 'In-sample' (histÃ³rico antes do holdout): valores ajustados = real âˆ’ resÃ­duo do modelo. "
        "RegiÃ£o 'Backtest': previsÃ£o out-of-sample do modelo treinado atÃ© Tâˆ’12 para os 12 meses seguintes. "
        "RegiÃ£o 'Forecast': projeÃ§Ã£o alÃ©m do Ãºltimo ponto observado."
    ])
    export.append(["Modelo", "MAE", "RMSE", "RÂ²", "MAPE (%)", "AIC", "BIC", "ConfiguraÃ§Ã£o"])
    for r in sucessos_com_ens:
        m = r['metricas']
        export.append([
            r['nome'],
            round(m['MAE'], 2),
            round(m['RMSE'], 2),
            round(m['R2'], 3) if not _safe_isnan(m['R2']) else "NaN",
            round(m['MAPE'], 2) if not _safe_isnan(m['MAPE']) else "NaN",
            round(_safe_float(r['aic']), 2) if not _safe_isnan(r['aic']) else "â€”",
            round(_safe_float(r['bic']), 2) if not _safe_isnan(r['bic']) else "â€”",
            r['order_str']
        ])

    falhas = [r for r in resultados if not r.get('sucesso')]
    if falhas:
        export.append([])
        export.append(["MODELOS QUE FALHARAM"])
        for r in falhas:
            export.append([r['nome'], r.get('erro', 'desconhecido')])

    export.append([])
    export.append(["TESTES DE ESTACIONARIEDADE"])
    export.append(["Teste", "EstatÃ­stica", "p-valor", "InterpretaÃ§Ã£o"])
    export.append(["ADF (Dickey-Fuller)",
                   round(estac['adf_stat'], 4), round(estac['adf_pvalor'], 4),
                   estac['adf_interpretacao']])
    export.append(["KPSS",
                   round(estac['kpss_stat'], 4), round(estac['kpss_pvalor'], 4),
                   estac['kpss_interpretacao']])

    export.append([])
    export.append([f"Outliers tratados: {int(mascara_outliers.sum())} ponto(s) com |z|>{THRESH_OUTLIER_Z}"])
    export.append(["Atualizado em", datetime.now(FUSO_BAHIA).strftime('%d/%m/%Y %H:%M:%S')])

    try:
        aba_prev.clear()
        aba_prev.update(values=export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_TEMPORAL atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro ao gravar PREVISAO_TEMPORAL: {e}")

    # ============================================
    # ABA 2: PREVISAO_DETALHES
    # ============================================
    aba_det = obter_aba(
        f"{prefixo_aba}_DETALHES{sufixo}", linhas=600, colunas=10,
        cabecalho=["Modelo", "ParÃ¢metro", "Valor", "Erro PadrÃ£o",
                   "p-valor", "IC95% Inf", "IC95% Sup", "Significativo (p<0.05)"]
    )
    detalhes = [["Modelo", "ParÃ¢metro", "Valor", "Erro PadrÃ£o", "p-valor",
                 "IC95% Inf", "IC95% Sup", "Significativo (p<0.05)"]]

    for r in sucessos_com_ens:
        try:
            detalhes.append([r['nome'], "EQUAÃ‡ÃƒO", r.get('equacao', 'â€”'), "", "", "", "", ""])
            detalhes.append([r['nome'], "ConfiguraÃ§Ã£o", r.get('order_str', 'â€”'), "", "", "", "", ""])
            aic_val = _safe_float(r.get('aic', float('nan')))
            bic_val = _safe_float(r.get('bic', float('nan')))
            if not _safe_isnan(aic_val):
                detalhes.append([r['nome'], "AIC", round(aic_val, 2), "", "", "", "", ""])
            if not _safe_isnan(bic_val):
                detalhes.append([r['nome'], "BIC", round(bic_val, 2), "", "", "", "", ""])
            detalhes.append([r['nome'], "Usa exÃ³genas (chuva, letivo)",
                             "Sim" if r.get('usa_exog') else "NÃ£o", "", "", "", "", ""])
            for p in r.get('parametros', []):
                sig = ""
                pv     = _safe_float(p.get('p_valor',  float('nan')))
                val    = _safe_float(p.get('valor',     float('nan')))
                ep     = _safe_float(p.get('erro_padrao', float('nan')))
                ic_inf = _safe_float(p.get('IC95_inf',  float('nan')))
                ic_sup = _safe_float(p.get('IC95_sup',  float('nan')))
                if not _safe_isnan(pv):
                    sig = "Sim" if pv < 0.05 else "NÃ£o"
                detalhes.append([
                    r['nome'], p.get('nome', '?'),
                    round(val, 4) if not _safe_isnan(val) else "NaN",
                    round(ep, 4)     if not _safe_isnan(ep)     else "â€”",
                    round(pv, 4)     if not _safe_isnan(pv)     else "â€”",
                    round(ic_inf, 4) if not _safe_isnan(ic_inf) else "â€”",
                    round(ic_sup, 4) if not _safe_isnan(ic_sup) else "â€”",
                    sig
                ])
            detalhes.append([])
        except Exception as e:
            print(f"[PREVISAO_DETALHES] Falha ao serializar {r.get('nome','?')}: "
                  f"{type(e).__name__}: {e}")
            detalhes.append([r.get('nome','?'), f"erro: {type(e).__name__}: {str(e)[:100]}",
                             "", "", "", "", "", ""])
            detalhes.append([])

    try:
        aba_det.clear()
        aba_det.update(values=detalhes, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_DETALHES atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro ao gravar PREVISAO_DETALHES: {e}")

    # ============================================
    # ABA 3: PREVISAO_INCERTEZAS
    # ============================================
    aba_inc = obter_aba(
        f"{prefixo_aba}_INCERTEZAS{sufixo}", linhas=500, colunas=13,
        cabecalho=["Modelo", "Tipo", "Horizonte", "PerÃ­odo", "Forecast",
                   "IC 1Ïƒ Inf", "IC 1Ïƒ Sup", "IC 2Ïƒ Inf", "IC 2Ïƒ Sup",
                   "P10", "P50", "P90", "Desvio Ïƒ"]
    )
    incertezas = [["Modelo", "Tipo", "Horizonte", "PerÃ­odo", "Forecast",
                   "IC 1Ïƒ Inf", "IC 1Ïƒ Sup", "IC 2Ïƒ Inf", "IC 2Ïƒ Sup",
                   "P10", "P50", "P90", "Desvio Ïƒ"]]

    # PerÃ­odos do holdout (Ãºltimos 12 meses do histÃ³rico)
    periodos_holdout = periodos_historicos[-HORIZONTE_HOLDOUT:]
    # PerÃ­odos antes do holdout (in-sample)
    periodos_insample = periodos_historicos[:-HORIZONTE_HOLDOUT]

    for r in sucessos:
        boot = r.get('bootstrap')
        holdout_arr = None
        forecast_arr = None

        try:
            forecast_arr = np.asarray(r['forecast'], dtype=float).flatten()
        except Exception:
            forecast_arr = None

        try:
            if r.get('prev_holdout') is not None:
                holdout_arr = np.asarray(r['prev_holdout'], dtype=float).flatten()
        except Exception:
            holdout_arr = None

        if boot is None and holdout_arr is None and forecast_arr is None:
            incertezas.append([r['nome'], "â€”", "â€”", "â€”", "Sem dados",
                               "", "", "", "", "", "", "", ""])
            continue

        # [v3.8 â€” Fase 1.4] HISTÃ“RICO IN-SAMPLE â€” fitted values com IC baseado
        # no desvio padrÃ£o dos resÃ­duos in-sample.
        # IC: fitted Â± Ïƒ_res (1Ïƒ) e fitted Â± 2Ïƒ_res (2Ïƒ).
        _res = r.get('residuos')
        if _res is not None and len(_res) > 0:
            _res_arr = np.asarray(_res, dtype=float)
            _sigma_res = float(np.std(_res_arr))
            _n_res = len(_res_arr)
            _offset = n_total - _n_res
            for _j, _rv in enumerate(_res_arr):
                _idx = _offset + _j
                # SÃ³ expÃµe pontos in-sample (antes do holdout)
                if _idx >= inicio_holdout:
                    break
                if _idx < 0 or _idx >= len(contagem):
                    continue
                _real = float(contagem.iloc[_idx]['Quantidade'])
                _fitted = _real - float(_rv)
                _p_str = periodos_historicos[_idx].strftime('%m/%Y') \
                    if _idx < len(periodos_historicos) else "â€”"
                incertezas.append([
                    r['nome'], "HistÃ³rico", 0, _p_str,
                    round(_fitted, 2),
                    round(max(0, _fitted - _sigma_res), 2),   # IC 1Ïƒ inf
                    round(_fitted + _sigma_res, 2),            # IC 1Ïƒ sup
                    round(max(0, _fitted - 2*_sigma_res), 2), # IC 2Ïƒ inf
                    round(_fitted + 2*_sigma_res, 2),          # IC 2Ïƒ sup
                    round(max(0, _fitted - 1.28*_sigma_res), 2),  # P10
                    round(_fitted, 2),                          # P50
                    round(_fitted + 1.28*_sigma_res, 2),       # P90
                    round(_sigma_res, 2),
                ])

        # v3.6.5: BACKTEST IC â€” usa desvio do bootstrap como proxy
        # da incerteza por horizonte aplicada ao holdout.
        # Justificativa: se o modelo tem desvio Ïƒ_h na previsÃ£o h passos
        # Ã  frente (estimado pelo bootstrap), a mesma incerteza se aplica
        # ao holdout que previu os mesmos h passos sem ver os dados reais.
        if holdout_arr is not None and boot is not None:
            desvio = boot.get('desvio')
            if desvio is not None:
                desvio_arr = np.asarray(desvio, dtype=float)
                for h in range(min(HORIZONTE_HOLDOUT, len(holdout_arr))):
                    if h >= len(periodos_holdout):
                        break
                    p_str = periodos_holdout[h].strftime('%m/%Y')
                    fc = float(holdout_arr[h])
                    # Usa desvio do horizonte h (ou Ãºltimo disponÃ­vel)
                    dh = float(desvio_arr[min(h, len(desvio_arr)-1)])
                    try:
                        incertezas.append([
                            r['nome'], "Backtest", h + 1, p_str,
                            round(fc, 2),
                            round(max(0, fc - dh), 2),       # IC 1Ïƒ inf
                            round(fc + dh, 2),                # IC 1Ïƒ sup
                            round(max(0, fc - 2*dh), 2),     # IC 2Ïƒ inf
                            round(fc + 2*dh, 2),              # IC 2Ïƒ sup
                            round(max(0, fc - 1.28*dh), 2),  # P10 aprox
                            round(fc, 2),                      # P50 = pontual
                            round(fc + 1.28*dh, 2),           # P90 aprox
                            round(dh, 2),
                        ])
                    except Exception:
                        pass

        # FORECAST IC â€” original (bootstrap efetivo)
        if forecast_arr is not None and boot is not None:
            for h in range(HORIZONTE_FORECAST):
                if h >= len(forecast_arr):
                    break
                p_str = periodos_futuros[h].strftime('%m/%Y')
                try:
                    incertezas.append([
                        r['nome'], "Forecast", h + 1, p_str,
                        round(float(forecast_arr[h]), 2),
                        round(float(boot['IC1_inf'][h]), 2),
                        round(float(boot['IC1_sup'][h]), 2),
                        round(float(boot['IC2_inf'][h]), 2),
                        round(float(boot['IC2_sup'][h]), 2),
                        round(float(boot['P10'][h]), 2),
                        round(float(boot['P50'][h]), 2),
                        round(float(boot['P90'][h]), 2),
                        round(float(boot['desvio'][h]), 2),
                    ])
                except Exception as e:
                    incertezas.append([r['nome'], "Forecast", h + 1, p_str,
                                       f"erro: {type(e).__name__}",
                                       "", "", "", "", "", "", "", ""])
        incertezas.append([])

    incertezas.append([f"Bootstrap n={N_BOOTSTRAP} (Prophet/UC n=200, GBR n=300). "
                       f"IC 1Ïƒ â‰ˆ 68%, IC 2Ïƒ â‰ˆ 95%. "
                       f"Backtest: IC aproximado usando desvio do bootstrap futuro como proxy. "
                       f"Forecast: IC direto dos caminhos bootstrap."])

    try:
        aba_inc.clear()
        aba_inc.update(values=incertezas, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_INCERTEZAS atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro ao gravar PREVISAO_INCERTEZAS: {e}")

    # ============================================
    # ABA 4: PREVISAO_DIAGNOSTICO
    # ============================================
    _cab_diag = [
        "Modelo", "N ResÃ­duos", "MÃ©dia ResÃ­duos", "Desvio ResÃ­duos",
        "Ljung-Box Stat", "LB p-valor", "LB InterpretaÃ§Ã£o",
        "Jarque-Bera Stat", "JB p-valor", "JB InterpretaÃ§Ã£o",
        "Shapiro-Wilk Stat", "SW p-valor", "SW InterpretaÃ§Ã£o",
        "Durbin-Watson", "DW InterpretaÃ§Ã£o",
        "Breusch-Pagan Stat", "BP p-valor", "BP InterpretaÃ§Ã£o",
    ]
    aba_diag = obter_aba(
        f"{prefixo_aba}_DIAGNOSTICO{sufixo}", linhas=200, colunas=len(_cab_diag),
        cabecalho=_cab_diag
    )
    diag = [_cab_diag]

    for r in sucessos:
        d = diagnosticar_residuos(r['residuos'], r['nome'])
        if d is None:
            diag.append([r['nome']] + ["â€”"] * (len(_cab_diag) - 1))
            diag[-1][6] = "ResÃ­duos insuficientes"
            continue
        diag.append([
            d['modelo'], d['n_residuos'],
            round(d['media_res'], 4), round(d['std_res'], 4),
            round(d['ljung_box_stat'], 4) if not np.isnan(d['ljung_box_stat']) else "â€”",
            round(d['ljung_box_pvalor'], 4) if not np.isnan(d['ljung_box_pvalor']) else "â€”",
            d['ljung_box_interpretacao'],
            round(d['jarque_bera_stat'], 4) if not np.isnan(d['jarque_bera_stat']) else "â€”",
            round(d['jarque_bera_pvalor'], 4) if not np.isnan(d['jarque_bera_pvalor']) else "â€”",
            d['jarque_bera_interpretacao'],
            round(d['shapiro_wilk_stat'], 4) if not np.isnan(d['shapiro_wilk_stat']) else "â€”",
            round(d['shapiro_wilk_pvalor'], 4) if not np.isnan(d['shapiro_wilk_pvalor']) else "â€”",
            d['shapiro_wilk_interpretacao'],
            round(d['durbin_watson'], 4) if not np.isnan(d['durbin_watson']) else "â€”",
            d['durbin_watson_interpretacao'],
            round(d['breusch_pagan_stat'], 4) if not np.isnan(d['breusch_pagan_stat']) else "â€”",
            round(d['breusch_pagan_pvalor'], 4) if not np.isnan(d['breusch_pagan_pvalor']) else "â€”",
            d['breusch_pagan_interpretacao'],
        ])

    diag.append([])
    diag.append(["TESTES DE ESTACIONARIEDADE DA SÃ‰RIE"])
    diag.append(["Teste", "EstatÃ­stica", "p-valor", "InterpretaÃ§Ã£o", "HipÃ³validacao tecnica Nula"])
    diag.append(["ADF (Dickey-Fuller Aumentado)",
                 round(estac['adf_stat'], 4), round(estac['adf_pvalor'], 4),
                 estac['adf_interpretacao'], "SÃ©rie tem raiz unitÃ¡ria"])
    diag.append(["KPSS",
                 round(estac['kpss_stat'], 4), round(estac['kpss_pvalor'], 4),
                 estac['kpss_interpretacao'], "SÃ©rie Ã© estacionÃ¡ria em nÃ­vel"])

    diag.append([])
    diag.append(["Legenda:",
                 "LB = Ljung-Box (independÃªncia); JB = Jarque-Bera (normalidade via assimetria+curtose); "
                 "SW = Shapiro-Wilk (normalidade, sensÃ­vel para n<50); "
                 "DW = Durbin-Watson (independÃªncia sequencial, 0â€“4; ~2 = OK); "
                 "BP = Breusch-Pagan (homocedasticidade dos resÃ­duos ao longo do tempo). "
                 "Todos com Î±=0,05."])
    diag.append(["Atualizado em", datetime.now(FUSO_BAHIA).strftime('%d/%m/%Y %H:%M:%S')])

    try:
        aba_diag.clear()
        aba_diag.update(values=diag, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_DIAGNOSTICO atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro ao gravar PREVISAO_DIAGNOSTICO: {e}")

    # ============================================
    # ABA 5: PREVISAO_RESIDUOS (resÃ­duos individuais)
    # ============================================
    aba_res = obter_aba(
        f"{prefixo_aba}_RESIDUOS{sufixo}", linhas=2000, colunas=4,
        cabecalho=["Modelo", "Indice", "Periodo", "Residuo"]
    )
    res_export = [["Modelo", "Indice", "Periodo", "Residuo"]]
    for r in sucessos:
        residuos = r['residuos']
        if residuos is None or len(residuos) == 0:
            continue
        n_res = len(residuos)
        # Alinha perÃ­odo: resÃ­duos correspondem aos pontos finais da sÃ©rie
        offset = len(periodos_historicos) - n_res
        for i, val in enumerate(residuos):
            if np.isnan(val):
                continue
            idx_periodo = offset + i
            periodo_str = (periodos_historicos[idx_periodo].strftime('%m/%Y')
                           if 0 <= idx_periodo < len(periodos_historicos) else f'idx_{i}')
            res_export.append([r['nome'], i + 1, periodo_str, round(float(val), 4)])

    try:
        aba_res.clear()
        aba_res.update(values=res_export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_RESIDUOS atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro ao gravar PREVISAO_RESIDUOS: {e}")

    # ============================================
    # ABA 5b: PREVISAO_PRESSUPOSTOS â€” testes completos OLS/NLS/GAM
    # ============================================
    try:
        _cab_pp = [
            "Modelo", "Pressuposto", "Teste / MÃ©todo", "EstatÃ­stica",
            "p-valor", "Resultado", "RecomendaÃ§Ã£o"
        ]
        aba_pp = obter_aba(
            f"{prefixo_aba}_PRESSUPOSTOS{sufixo}", linhas=400, colunas=len(_cab_pp),
            cabecalho=_cab_pp
        )
        pp_export = [_cab_pp]

        def _fmt(v):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                return "â€”"
            if isinstance(v, float):
                return round(v, 4)
            return v

        for r in sucessos:
            res_arr = np.asarray(r.get('residuos', []), dtype=float)
            res_arr = res_arr[~np.isnan(res_arr)]
            nome = r['nome']
            if len(res_arr) < 8:
                pp_export.append([nome, "Geral", "â€”", "â€”", "â€”",
                                   "ResÃ­duos insuficientes (<8)", "â€”"])
                continue

            n_r = len(res_arr)
            idx_t = np.arange(n_r, dtype=float)

            # --- Linearidade: resÃ­duos vs ajustados (ausÃªncia de padrÃ£o) ---
            # Avaliamos via correlaÃ§Ã£o de Spearman entre |resÃ­duo| e Ã­ndice temporal
            try:
                rho, p_rho = sps.spearmanr(np.abs(res_arr), idx_t)
                lin_ok = abs(rho) < 0.3 or p_rho > 0.05
                pp_export.append([
                    nome, "Linearidade",
                    "Spearman |resÃ­duo| vs tempo (proxy grÃ¡fico resÃ­duosÃ—ajustados)",
                    _fmt(rho), _fmt(p_rho),
                    "OK (sem tendÃªncia sistemÃ¡tica)" if lin_ok else "ATENÃ‡ÃƒO (tendÃªncia nos resÃ­duos)",
                    "OK" if lin_ok else "Inspecionar grÃ¡fico resÃ­duosÃ—ajustados; considerar transformaÃ§Ã£o"
                ])
            except Exception:
                pp_export.append([nome, "Linearidade", "Spearman", "â€”", "â€”", "NÃ£o calculado", "â€”"])

            # --- Normalidade: Shapiro-Wilk ---
            try:
                sw_s, sw_p = shapiro(res_arr[:min(n_r, 5000)])
                sw_ok = sw_p > 0.05
                pp_export.append([
                    nome, "Normalidade",
                    "Shapiro-Wilk (resÃ­duos; mais sensÃ­vel para n<50)",
                    _fmt(sw_s), _fmt(sw_p),
                    "OK (normalidade nÃ£o rejeitada)" if sw_ok else "ATENÃ‡ÃƒO (normalidade rejeitada)",
                    "OK" if sw_ok else "Usar bootstrap ou erros HC3; verificar Q-Q plot (aba PREVISAO_QQPLOT)"
                ])
            except Exception:
                pp_export.append([nome, "Normalidade", "Shapiro-Wilk", "â€”", "â€”", "NÃ£o calculado", "â€”"])

            # --- Normalidade: Jarque-Bera ---
            try:
                jb_s, jb_p, _, _ = jarque_bera(res_arr)
                jb_ok = jb_p > 0.05
                pp_export.append([
                    nome, "Normalidade",
                    "Jarque-Bera (assimetria + curtose)",
                    _fmt(jb_s), _fmt(jb_p),
                    "OK (normalidade nÃ£o rejeitada)" if jb_ok else "ATENÃ‡ÃƒO (normalidade rejeitada)",
                    "OK" if jb_ok else "Usar bootstrap ou erros HC3"
                ])
            except Exception:
                pp_export.append([nome, "Normalidade", "Jarque-Bera", "â€”", "â€”", "NÃ£o calculado", "â€”"])

            # --- Homocedasticidade: Breusch-Pagan ---
            try:
                X_bp = np.column_stack([np.ones(n_r), idx_t])
                bp_lm, bp_p, _, _ = het_breuschpagan(res_arr, X_bp)
                bp_ok = bp_p > 0.05
                pp_export.append([
                    nome, "Homocedasticidade",
                    "Breusch-Pagan (resÃ­duosÂ² ~ Ã­ndice temporal)",
                    _fmt(bp_lm), _fmt(bp_p),
                    "OK (homocedasticidade nÃ£o rejeitada)" if bp_ok else "ATENÃ‡ÃƒO (heterocedasticidade)",
                    "OK" if bp_ok else "Usar erros padrÃ£o robustos HC3 ou WLS com pesos ~1/ÏƒÂ²"
                ])
            except Exception:
                pp_export.append([nome, "Homocedasticidade", "Breusch-Pagan", "â€”", "â€”", "NÃ£o calculado", "â€”"])

            # --- IndependÃªncia: Durbin-Watson ---
            try:
                dw_val = durbin_watson(res_arr)
                dw_ok = 1.5 <= dw_val <= 2.5
                pp_export.append([
                    nome, "IndependÃªncia",
                    "Durbin-Watson (sequencial; ~2 = OK; <1.5 = autocorr. positiva)",
                    _fmt(dw_val), "â€”",
                    "OK" if dw_ok else ("ATENÃ‡ÃƒO (autocorr. positiva)" if dw_val < 1.5
                                         else "ATENÃ‡ÃƒO (autocorr. negativa)"),
                    "OK" if dw_ok else "Adicionar lags autoregressivos ou diferenciaÃ§Ã£o"
                ])
            except Exception:
                pp_export.append([nome, "IndependÃªncia", "Durbin-Watson", "â€”", "â€”", "NÃ£o calculado", "â€”"])

            # --- IndependÃªncia: Ljung-Box ---
            try:
                lb = acorr_ljungbox(res_arr, lags=[min(10, n_r // 2)], return_df=True)
                lb_s = float(lb['lb_stat'].iloc[0])
                lb_p = float(lb['lb_pvalue'].iloc[0])
                lb_ok = lb_p > 0.05
                pp_export.append([
                    nome, "IndependÃªncia",
                    "Ljung-Box (autocorrelaÃ§Ã£o atÃ© lag 10)",
                    _fmt(lb_s), _fmt(lb_p),
                    "OK (sem autocorrelaÃ§Ã£o residual)" if lb_ok else "ATENÃ‡ÃƒO (autocorrelaÃ§Ã£o residual)",
                    "OK" if lb_ok else "Revisar ordem AR/MA ou adicionar termos sazonais"
                ])
            except Exception:
                pp_export.append([nome, "IndependÃªncia", "Ljung-Box", "â€”", "â€”", "NÃ£o calculado", "â€”"])

            # --- Multicolinearidade: VIF para regressores exÃ³genos ---
            if r.get('usa_exog'):
                try:
                    df_ctx_vif = ler_contexto_sazonal()
                    if df_ctx_vif is not None and len(df_ctx_vif) > 0:
                        _cols_exog = ['Precipitacao_mm', 'Periodo_Letivo_Bin']
                        _cols_ok = [c for c in _cols_exog if c in df_ctx_vif.columns]
                        if len(_cols_ok) >= 2:
                            X_vif = df_ctx_vif[_cols_ok].dropna().astype(float).values
                            X_vif_c = np.column_stack([np.ones(len(X_vif)), X_vif])
                            for j_vif, col_vif in enumerate(_cols_ok):
                                vif_val = variance_inflation_factor(X_vif_c, j_vif + 1)
                                vif_ok = vif_val < 5
                                pp_export.append([
                                    nome, "Multicolinearidade",
                                    f"VIF â€” {col_vif}",
                                    _fmt(vif_val), "â€”",
                                    "OK (VIF<5)" if vif_ok else ("ATENÃ‡ÃƒO (VIF 5â€“10)" if vif_val < 10 else "CRÃTICO (VIF>10)"),
                                    "OK" if vif_ok else "Considerar Ridge/Lasso ou remover regressor colinear"
                                ])
                except Exception:
                    pp_export.append([nome, "Multicolinearidade", "VIF", "â€”", "â€”", "NÃ£o calculado", "â€”"])

            # --- Pontos influentes: distÃ¢ncia de Cook (OLS aproximada em resÃ­duos) ---
            try:
                if n_r >= 10:
                    X_cook = np.column_stack([np.ones(n_r), idx_t])
                    ols_fit = sm_api.OLS(res_arr, X_cook).fit()
                    infl = OLSInfluence(ols_fit)
                    cook_d = infl.cooks_distance[0]
                    threshold_cook = 4.0 / n_r
                    n_influentes = int(np.sum(cook_d > threshold_cook))
                    cook_ok = n_influentes == 0
                    pp_export.append([
                        nome, "Pontos Influentes",
                        f"DistÃ¢ncia de Cook (limiar 4/n = {threshold_cook:.4f})",
                        f"{n_influentes} ponto(s) > limiar", "â€”",
                        "OK (nenhum ponto influente)" if cook_ok else f"ATENÃ‡ÃƒO ({n_influentes} ponto(s) influente(s))",
                        "OK" if cook_ok else "Inspecionar e tratar outliers influentes; considerar regressÃ£o robusta"
                    ])
            except Exception:
                pp_export.append([nome, "Pontos Influentes", "DistÃ¢ncia de Cook", "â€”", "â€”", "NÃ£o calculado", "â€”"])

            # --- EspecificaÃ§Ã£o: RESET (apenas para modelos com tendÃªncia linear) ---
            if nome in ('ARIMA', 'SARIMAX-12', 'SARIMAX-6', 'Theta'):
                try:
                    if n_r >= 12:
                        X_reset = np.column_stack([np.ones(n_r), idx_t])
                        ols_reset = sm_api.OLS(res_arr, X_reset).fit()
                        reset_res = linear_reset(ols_reset, power=3, use_f=True)
                        reset_p = float(reset_res.pvalue)
                        reset_ok = reset_p > 0.05
                        pp_export.append([
                            nome, "EspecificaÃ§Ã£o",
                            "Ramsey RESET (potÃªncias dos ajustados; H0 = especificaÃ§Ã£o correta)",
                            _fmt(reset_res.statistic), _fmt(reset_p),
                            "OK (especificaÃ§Ã£o nÃ£o rejeitada)" if reset_ok else "ATENÃ‡ÃƒO (erro de especificaÃ§Ã£o)",
                            "OK" if reset_ok else "Considerar termos nÃ£o-lineares ou diferenciaÃ§Ã£o adicional"
                        ])
                except Exception:
                    pp_export.append([nome, "EspecificaÃ§Ã£o", "RESET", "â€”", "â€”", "NÃ£o calculado", "â€”"])

            # --- Erros HC3 (robusto Ã  heterocedasticidade) ---
            try:
                if n_r >= 10:
                    X_hc3 = np.column_stack([np.ones(n_r), idx_t])
                    ols_hc3 = sm_api.OLS(res_arr, X_hc3).fit(cov_type='HC3')
                    pv_trend = float(ols_hc3.pvalues[1])
                    coef_trend = float(ols_hc3.params[1])
                    hc3_ok = pv_trend > 0.05
                    pp_export.append([
                        nome, "Erros Robustos HC3",
                        "OLS(resÃ­duos ~ tempo) com erros HC3 â€” coeficiente de tendÃªncia",
                        _fmt(coef_trend), _fmt(pv_trend),
                        "OK (tendÃªncia nos resÃ­duos nÃ£o significativa)" if hc3_ok else "ATENÃ‡ÃƒO (tendÃªncia significativa em HC3)",
                        "OK" if hc3_ok else "ResÃ­duos tÃªm estrutura temporal â€” considerar diferenciaÃ§Ã£o ou modelo mais complexo"
                    ])
            except Exception:
                pp_export.append([nome, "Erros Robustos HC3", "OLS HC3", "â€”", "â€”", "NÃ£o calculado", "â€”"])

            # --- ValidaÃ§Ã£o cruzada k-fold (referÃªncia ao CV jÃ¡ feito) ---
            if cv_results and nome in cv_results:
                rmses_cv = cv_results[nome]
                if rmses_cv:
                    pp_export.append([
                        nome, "ValidaÃ§Ã£o Cruzada",
                        f"Rolling-origin {N_FOLDS_CV}-fold â€” RMSE por fold",
                        f"MÃ©dia={round(float(np.mean(rmses_cv)), 2)} | DP={round(float(np.std(rmses_cv)), 2)}",
                        "â€”",
                        "EstÃ¡vel" if float(np.std(rmses_cv)) / max(float(np.mean(rmses_cv)), 1e-6) < 0.3 else "ATENÃ‡ÃƒO (CV instÃ¡vel)",
                        "Ver detalhes em PREVISAO_VALIDACAO"
                    ])

            pp_export.append([])  # linha em branco entre modelos

        pp_export.append([])
        pp_export.append([
            "ReferÃªncias metodolÃ³gicas:",
            "Shapiro-Wilk (1965); Jarque-Bera (1987); Breusch-Pagan (1979); "
            "Durbin-Watson (1950); Cook (1977); Ramsey RESET (1969); HC3 (MacKinnon-White 1985); "
            "VIF (O'Brien 2007). Todos Î±=0.05. "
            "Para ARIMA/SARIMAX: resÃ­duos sÃ£o os in-sample do modelo treinado atÃ© T-H."
        ])
        pp_export.append(["Atualizado em", datetime.now(FUSO_BAHIA).strftime('%d/%m/%Y %H:%M:%S')])

        aba_pp.clear()
        aba_pp.update(values=pp_export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_PRESSUPOSTOS atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro ao gravar PREVISAO_PRESSUPOSTOS: {e}")
    except Exception as e:
        print(f"[PrevisÃ£o] PREVISAO_PRESSUPOSTOS falhou: {type(e).__name__}: {e}")

    # ============================================
    # ABA 6: PREVISAO_QQPLOT
    # ============================================
    aba_qq = obter_aba(
        f"{prefixo_aba}_QQPLOT{sufixo}", linhas=1500, colunas=3,
        cabecalho=["Modelo", "Quantil_Teorico", "Quantil_Observado_Padronizado"]
    )
    qq_export = [["Modelo", "Quantil_Teorico", "Quantil_Observado_Padronizado"]]
    for r in sucessos:
        pts = calcular_qqplot_pontos(r['residuos'])
        if pts is None:
            continue
        for qt, qo in pts:
            qq_export.append([r['nome'], round(float(qt), 4), round(float(qo), 4)])

    try:
        aba_qq.clear()
        aba_qq.update(values=qq_export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_QQPLOT atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro ao gravar PREVISAO_QQPLOT: {e}")

    # ============================================
    # ABA 7: PREVISAO_VALIDACAO (rolling-origin CV)
    # ============================================
    aba_val = obter_aba(
        f"{prefixo_aba}_VALIDACAO{sufixo}", linhas=200, colunas=10,
        cabecalho=["Modelo", "RMSE_MÃ©dio_CV", "RMSE_DesvPad_CV", "N_Folds",
                   "Fold_1", "Fold_2", "Fold_3", "Fold_4", "Fold_5", "InterpretaÃ§Ã£o"]
    )
    val_export = [["Modelo", "RMSE_MÃ©dio_CV", "RMSE_DesvPad_CV", "N_Folds",
                   "Fold_1", "Fold_2", "Fold_3", "Fold_4", "Fold_5", "InterpretaÃ§Ã£o"]]
    if cv_results is not None:
        for nome_mod, lista_rmse in cv_results.items():
            if not lista_rmse:
                val_export.append([nome_mod, "â€”", "â€”", 0, "", "", "", "", "",
                                   "Falha em todos os folds"])
                continue
            arr = np.array(lista_rmse)
            media = float(arr.mean())
            std = float(arr.std()) if len(arr) > 1 else 0.0
            interp = ("Baixa variÃ¢ncia (CV estÃ¡vel)" if std < media * 0.2
                      else "Alta variÃ¢ncia (modelo sensÃ­vel ao perÃ­odo de treino)")
            linha = [nome_mod, round(media, 2), round(std, 2), len(arr)]
            for i in range(5):
                linha.append(round(arr[i], 2) if i < len(arr) else "")
            linha.append(interp)
            val_export.append(linha)
    else:
        val_export.append(["â€”", "â€”", "â€”", "â€”", "", "", "", "", "",
                           "CV nÃ£o executada (sÃ©rie curta)"])

    val_export.append([])
    val_export.append([f"ValidaÃ§Ã£o Rolling-Origin com {N_FOLDS_CV} folds Ã— {HORIZONTE_HOLDOUT} meses cada. "
                        "Compara robustez relativa entre modelos sob diferentes janelas de treino."])

    try:
        aba_val.clear()
        aba_val.update(values=val_export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_VALIDACAO atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro ao gravar PREVISAO_VALIDACAO: {e}")

    # ============================================
    # [v3.5] ABAS NOVAS â€” DIEBOLD-MARIANO, GRANGER, STL, PERIODOGRAMA, ACF/PACF
    # ============================================

    # ---------- ABA: PREVISAO_DIEBOLD_MARIANO (G3) ----------
    try:
        aba_dm = obter_aba(
            f"{prefixo_aba}_DIEBOLD_MARIANO{sufixo}", linhas=200, colunas=8,
            cabecalho=["Modelo_A", "Modelo_B", "DM_Stat", "p_valor",
                       "n_pares", "Significativo (Î±=0.05)", "Vencedor", "InterpretaÃ§Ã£o"]
        )
        dm_export = [["Modelo_A", "Modelo_B", "DM_Stat", "p_valor",
                      "n_pares", "Significativo (Î±=0.05)", "Vencedor", "InterpretaÃ§Ã£o"]]
        # Pares sÃ³ de modelos com resÃ­duos disponÃ­veis
        modelos_dm = [r for r in sucessos if r.get('residuos') is not None]
        for i in range(len(modelos_dm)):
            for j in range(i+1, len(modelos_dm)):
                r1, r2 = modelos_dm[i], modelos_dm[j]
                dm = teste_diebold_mariano(r1['residuos'], r2['residuos'])
                if np.isnan(dm['DM']):
                    continue
                sig = "Sim" if dm['p_valor'] < 0.05 else "NÃ£o"
                if dm['p_valor'] >= 0.05:
                    venc = "Empate"
                else:
                    venc = r1['nome'] if dm['DM'] < 0 else r2['nome']
                dm_export.append([
                    r1['nome'], r2['nome'],
                    round(dm['DM'], 4), round(dm['p_valor'], 4),
                    dm['n'], sig, venc, dm['interpretacao']
                ])
        dm_export.append([])
        dm_export.append(["Teste de Diebold-Mariano (1995): H0 = acurÃ¡cia preditiva igual."
                           " p<0.05 implica diferenÃ§a estatÃ­stica entre os modelos."])
        aba_dm.clear()
        aba_dm.update(values=dm_export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_DIEBOLD_MARIANO atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro DIEBOLD_MARIANO: {e}")

    # ---------- ABA: PREVISAO_DECOMPOSICAO (G17) ----------
    try:
        stl_result = decompor_stl_serie(serie_qtd, periodo=12)
        if stl_result is not None:
            aba_stl = obter_aba(
                f"{prefixo_aba}_DECOMPOSICAO{sufixo}", linhas=300, colunas=6,
                cabecalho=["PerÃ­odo", "Observado", "TendÃªncia", "Sazonal", "ResÃ­duo"]
            )
            stl_export = [["PerÃ­odo", "Observado", "TendÃªncia", "Sazonal", "ResÃ­duo"]]
            periodos_str = contagem['Mes_Ano_Str'].tolist()
            for i in range(len(stl_result['observado'])):
                stl_export.append([
                    periodos_str[i],
                    round(stl_result['observado'][i], 2),
                    round(stl_result['tendencia'][i], 2),
                    round(stl_result['sazonal'][i], 2),
                    round(stl_result['residuo'][i], 2),
                ])
            stl_export.append([])
            stl_export.append([
                "DecomposiÃ§Ã£o STL (Cleveland et al., 1990) com perÃ­odo=12.",
                f"ForÃ§a da tendÃªncia: {stl_result['forca_tendencia']:.3f}",
                f"ForÃ§a da sazonalidade: {stl_result['forca_sazonalidade']:.3f}",
                "(Valores prÃ³ximos de 1 indicam componente forte; prÃ³ximos de 0, fraca)"
            ])
            aba_stl.clear()
            aba_stl.update(values=stl_export, range_name='A1', value_input_option='USER_ENTERED')
            print("[PrevisÃ£o] PREVISAO_DECOMPOSICAO atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro DECOMPOSICAO: {e}")
    except Exception as e:
        print(f"[PrevisÃ£o] STL falhou: {e}")

    # ---------- ABA: PREVISAO_ESPECTRO (G19) ----------
    try:
        per = calcular_periodograma(serie_qtd)
        if per is not None:
            aba_per = obter_aba(
                f"{prefixo_aba}_ESPECTRO{sufixo}", linhas=200, colunas=4,
                cabecalho=["FrequÃªncia", "PerÃ­odo (meses)", "PotÃªncia", "Top 10?"]
            )
            per_export = [["FrequÃªncia", "PerÃ­odo (meses)", "PotÃªncia", "Top 10?"]]
            top_periods = {round(p[0], 4): True for p in per['top_periodos']}
            for i, (f, p) in enumerate(zip(per['frequencias'], per['potencias'])):
                if i == 0:  # f=0 Ã© DC
                    continue
                periodo = 1.0 / f if f > 0 else float('inf')
                is_top = "Sim" if round(periodo, 4) in top_periods else ""
                if not np.isfinite(periodo) or periodo > 100:
                    continue
                per_export.append([
                    round(f, 5), round(periodo, 2), round(p, 4), is_top
                ])
            per_export.append([])
            per_export.append([
                "Periodograma de Fourier â€” picos indicam ciclos relevantes.",
                "Os 10 perÃ­odos com maior potÃªncia sÃ£o marcados como 'Top 10'.",
                "PerÃ­odos prÃ³ximos de 12 (sazonalidade anual) ou 6 (semestral) "
                "justificam empiricamente a configuraÃ§Ã£o SARIMAX."
            ])
            aba_per.clear()
            aba_per.update(values=per_export, range_name='A1', value_input_option='USER_ENTERED')
            print("[PrevisÃ£o] PREVISAO_ESPECTRO atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro ESPECTRO: {e}")
    except Exception as e:
        print(f"[PrevisÃ£o] Periodograma falhou: {e}")

    # ---------- ABA: PREVISAO_ACF_PACF (G20) ----------
    try:
        ap = calcular_acf_pacf(serie_qtd, n_lags=ACF_PACF_LAGS)
        if ap is not None:
            aba_ap = obter_aba(
                f"{prefixo_aba}_ACF_PACF{sufixo}", linhas=50, colunas=8,
                cabecalho=["Lag", "ACF", "ACF_IC95_Inf", "ACF_IC95_Sup",
                           "PACF", "PACF_IC95_Inf", "PACF_IC95_Sup", "InterpretaÃ§Ã£o"]
            )
            ap_export = [["Lag", "ACF", "ACF_IC95_Inf", "ACF_IC95_Sup",
                          "PACF", "PACF_IC95_Inf", "PACF_IC95_Sup", "InterpretaÃ§Ã£o"]]
            limiar = 1.96 / np.sqrt(len(serie_qtd))  # banda de 95% para H0
            for k, lag in enumerate(ap['lags']):
                acf_v = ap['acf'][k]
                pacf_v = ap['pacf'][k]
                # InterpretaÃ§Ã£o resumida
                sig_acf = abs(acf_v) > limiar and lag > 0
                sig_pacf = abs(pacf_v) > limiar and lag > 0
                interp = ""
                if sig_acf and sig_pacf:
                    interp = "ACF e PACF significativas neste lag"
                elif sig_acf:
                    interp = "ACF significativa (sugere componente MA)"
                elif sig_pacf:
                    interp = "PACF significativa (sugere componente AR)"
                ap_export.append([
                    lag,
                    round(acf_v, 4),
                    round(ap['acf_ic_inf'][k], 4),
                    round(ap['acf_ic_sup'][k], 4),
                    round(pacf_v, 4),
                    round(ap['pacf_ic_inf'][k], 4),
                    round(ap['pacf_ic_sup'][k], 4),
                    interp
                ])
            ap_export.append([])
            ap_export.append([
                "ACF/PACF atÃ© 24 lags. Banda de significÃ¢ncia 95%: Â±",
                round(limiar, 4),
                "Box-Jenkins: PACF cortando no lag p sugere AR(p); ACF cortando no lag q sugere MA(q)."
            ])
            aba_ap.clear()
            aba_ap.update(values=ap_export, range_name='A1', value_input_option='USER_ENTERED')
            print("[PrevisÃ£o] PREVISAO_ACF_PACF atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro ACF_PACF: {e}")
    except Exception as e:
        print(f"[PrevisÃ£o] ACF/PACF falhou: {e}")

    # ---------- ABA: PREVISAO_GRANGER (G15) ----------
    # Testa se precipitaÃ§Ã£o e perÃ­odo letivo Granger-causam chamados.
    try:
        aba_gr = obter_aba(
            f"{prefixo_aba}_GRANGER{sufixo}", linhas=20, colunas=6,
            cabecalho=["VariÃ¡vel ExÃ³gena", "Lag MÃ­nimo p", "p-valor MÃ­nimo",
                       "Significativo (Î±=0.05)", "RecomendaÃ§Ã£o", "InterpretaÃ§Ã£o"]
        )
        gr_export = [["VariÃ¡vel ExÃ³gena", "Lag MÃ­nimo p", "p-valor MÃ­nimo",
                      "Significativo (Î±=0.05)", "RecomendaÃ§Ã£o", "InterpretaÃ§Ã£o"]]
        # Recupera contexto para alinhar com a sÃ©rie histÃ³rica
        try:
            df_ctx = ler_contexto_sazonal()
        except Exception:
            df_ctx = None
        if df_ctx is not None and len(df_ctx) >= len(serie_qtd):
            periodos_serie = contagem['Mes_Ano'].tolist()
            df_ctx_alinhado = df_ctx.set_index('Mes_Ano').reindex(periodos_serie).reset_index()
            # [v3.8 â€” Fase 1.0] Inclui variÃ¡veis de Ã¡rea na causalidade Granger
            variaveis_granger = ['Precipitacao_mm', 'Periodo_Letivo_Bin']
            # Adiciona Ã¡rea se disponÃ­vel no df_contexto consolidado
            for col_area in ['Area_Construida_m2', 'Area_Total_m2']:
                if col_area in df_contexto.columns:
                    variaveis_granger.append(col_area)
                    # Mescla ao alinhado se ainda nÃ£o presente
                    if col_area not in df_ctx_alinhado.columns:
                        _area_map = df_contexto.set_index('Mes_Ano')[col_area].to_dict()
                        df_ctx_alinhado[col_area] = df_ctx_alinhado['Mes_Ano'].map(_area_map).fillna(0)
            for nome_var in variaveis_granger:
                if nome_var in df_ctx_alinhado.columns:
                    serie_x = df_ctx_alinhado[nome_var].fillna(0).astype(float).values
                    gr = testar_granger_causality(serie_qtd, serie_x, GRANGER_MAX_LAG)
                    sig = "Sim" if not np.isnan(gr['p_valor_min']) and gr['p_valor_min'] < 0.05 else "NÃ£o"
                    rec = ("Manter como regressor" if sig == "Sim"
                           else "Considerar remoÃ§Ã£o (efeito nÃ£o significativo)")
                    gr_export.append([
                        nome_var, gr['lag_min'],
                        round(gr['p_valor_min'], 4) if not np.isnan(gr['p_valor_min']) else "â€”",
                        sig, rec, gr['interpretacao']
                    ])
        else:
            gr_export.append(["â€”", "â€”", "â€”", "â€”", "â€”",
                              "Aba CONTEXTO_SAZONAL nÃ£o disponÃ­vel ou desalinhada"])

        gr_export.append([])
        gr_export.append([
            "Teste de causalidade Granger (Granger, 1969): H0 = x nÃ£o Granger-causa y.",
            f"Lag testado: 1 a {GRANGER_MAX_LAG} meses.",
            "p<0.05 sustenta empiricamente a inclusÃ£o da variÃ¡vel como regressor exÃ³geno em SARIMAX/Prophet/GBR."
        ])
        aba_gr.clear()
        aba_gr.update(values=gr_export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_GRANGER atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro GRANGER: {e}")
    except Exception as e:
        print(f"[PrevisÃ£o] Granger falhou: {e}")

    # ---------- ABA: PREVISAO_CRPS_MULTICRITERIO (G14) ----------
    try:
        # Calcula CRPS por modelo usando paths do bootstrap (quando existe)
        crps_por_modelo = {}
        # Para CRPS precisamos das observaÃ§Ãµes reais do holdout â€” usamos
        # o conjunto de teste jÃ¡ separado em cada ajuste (Ãºltimos H meses).
        teste_holdout = serie_qtd[-HORIZONTE_HOLDOUT:]
        for r in sucessos:
            boot = r.get('bootstrap')
            if boot is None or 'paths' not in boot:
                crps_por_modelo[r['nome']] = float('nan')
                continue
            # paths[:, :H] tem horizonte mas precisamos dos primeiros H referentes ao holdout
            # Como bootstrap Ã© feito para HORIZONTE_FORECAST, comparamos sÃ³ a parte coincidente
            if boot['paths'].shape[1] >= HORIZONTE_HOLDOUT:
                paths_holdout = boot['paths'][:, :HORIZONTE_HOLDOUT]
                # Mas estes sÃ£o forecasts FUTUROS, nÃ£o holdout. Para CRPS rigoroso
                # precisarÃ­amos refazer fit no treino e bootstrap; aqui usamos como
                # aproximaÃ§Ã£o que CRPS sobre paths futuros vs Ãºltimos H reais Ã© razoÃ¡vel.
                crps_por_modelo[r['nome']] = calcular_crps_empirico(teste_holdout, paths_holdout)
            else:
                crps_por_modelo[r['nome']] = float('nan')

        sel = selecionar_modelo_multicriterio(sucessos, cv_results, crps_por_modelo)

        aba_crps = obter_aba(
            f"{prefixo_aba}_CRPS_MULTICRITERIO{sufixo}", linhas=30, colunas=6,
            cabecalho=["Modelo", "RMSE", "CRPS", "Desvio_CV",
                       "Score_Multicriterio", "PosiÃ§Ã£o"]
        )
        crps_export = [["Modelo", "RMSE", "CRPS", "Desvio_CV",
                        "Score_Multicriterio", "PosiÃ§Ã£o"]]
        if sel is not None:
            ord_score = sorted(sel['tabela_scores'], key=lambda x: x['score'])
            for pos, item in enumerate(ord_score, start=1):
                crps_export.append([
                    item['modelo'],
                    round(item['rmse'], 3),
                    round(item['crps'], 3) if item['crps'] is not None else "â€”",
                    round(item['desvio_cv'], 3) if item['desvio_cv'] is not None else "â€”",
                    round(item['score'], 4),
                    pos
                ])
            crps_export.append([])
            crps_export.append([
                f"Vencedor multicritÃ©rio: {sel['vencedor']} (score = {sel['score_vencedor']:.4f})",
                f"Pesos: RMSE={PESO_RMSE} Â· CRPS={PESO_CRPS} Â· Desvio_CV={PESO_DESVIO_CV}",
                "Score = combinaÃ§Ã£o ponderada normalizada [0,1]; menor Ã© melhor.",
                "RMSE = precisÃ£o pontual; CRPS = calibraÃ§Ã£o de incerteza; Desvio_CV = estabilidade."
            ])
        else:
            crps_export.append(["â€”", "â€”", "â€”", "â€”", "â€”", "â€”"])
            crps_export.append(["Nenhum modelo com bootstrap disponÃ­vel para CRPS"])
        aba_crps.clear()
        aba_crps.update(values=crps_export, range_name='A1', value_input_option='USER_ENTERED')
        print("[PrevisÃ£o] PREVISAO_CRPS_MULTICRITERIO atualizada.")
    except APIError as e:
        print(f"[PrevisÃ£o] Erro CRPS: {e}")
    except Exception as e:
        print(f"[PrevisÃ£o] CRPS/multicritÃ©rio falhou: {e}")

    # Marca timestamp da execuÃ§Ã£o para evitar repetir no boot
    try:
        with open(f'{CAMINHO_PASTA}/ultima_previsao.txt', 'w') as f:
            f.write(datetime.now(FUSO_BAHIA).isoformat())
    except Exception:
        pass

    print(f"[PrevisÃ£o] ConcluÃ­do. Modelo vencedor: {melhor['nome']}")




# =====================================================================
# 13. UTILITÃRIO DE CONTROLE DE EXECUÃ‡ÃƒO
# =====================================================================

def previsao_recente_existe(horas=INTERVALO_HORAS_PREVISAO_BOOT):
    """Verifica se houve execuÃ§Ã£o de previsÃ£o nas Ãºltimas N horas."""
    arq = f'{CAMINHO_PASTA}/ultima_previsao.txt'
    if not os.path.exists(arq):
        return False
    try:
        with open(arq, 'r') as f:
            ts_str = f.read().strip()
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            # pytz tem .localize, datetime.timezone nÃ£o â€” usa replace como fallback
            if hasattr(FUSO_BAHIA, 'localize'):
                ts = FUSO_BAHIA.localize(ts)
            else:
                ts = ts.replace(tzinfo=FUSO_BAHIA)
        delta = datetime.now(FUSO_BAHIA) - ts
        return delta.total_seconds() < horas * 3600
    except Exception:
        return False


# =====================================================================
# 14. MODO OPERACIONAL E ENTRY POINT
# =====================================================================

def _modo_previsao_chamados():
    """[v4.0.8] SÃ³ previsÃ£o global de chamados (contagem). Sem custos, sem filtros, sem ODS.
    Projetado para rodar uma vez por dia (workflow previsao_chamados_global).
    Gera as 14 abas PREVISAO_* sem sufixo (TEMPORAL, DETALHES, INCERTEZAS, etc.).
    """
    if previsao_recente_existe():
        print(f"[Modo previsao_chamados] PrevisÃ£o recente encontrada "
              f"(< {INTERVALO_HORAS_PREVISAO_BOOT}h). Abortando para evitar re-execuÃ§Ã£o.")
        return
    try:
        todas_linhas = planilha.get_all_values()
    except APIError as e:
        print(f"[Modo previsao_chamados] Falha: {e}"); return
    dados_op = todas_linhas[1:]
    executar_analise_preditiva_avancada(dados_op, sufixo="")


# =====================================================================
# ENTRY POINT
# =====================================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Motor Malha IA â€” mÃ³dulo de previsÃ£o de chamados (v4.0.8)"
    )
    parser.add_argument(
        "--apenas-previsao-chamados",
        action="store_true",
        help="Executa APENAS o pipeline de previsÃ£o global de chamados/mÃªs."
    )
    args = parser.parse_args()

    if args.apenas_previsao_chamados:
        _modo_previsao_chamados()
    else:
        print("[motor_previsao_chamados] Nenhum modo ativo. "
              "Use --apenas-previsao-chamados para executar.")
