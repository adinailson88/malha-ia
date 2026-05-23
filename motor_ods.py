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

# =====================================================================
# 1. INSTALAÇÃO INTELIGENTE DE DEPENDÊNCIAS COM CACHE PERSISTENTE
# =====================================================================
import os
import sys
import json
import subprocess
import hashlib

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
    'requests': '2.32.3',
    'groq': '0.13.0',
    'pandas': '2.2.3',
    'numpy': '1.26.4',
    'statsmodels': '0.14.4',
    'scikit-learn': '1.5.2',
    'pytz': '2024.2',
    'pmdarima': '2.0.4',
    'prophet': '1.1.6',
    'scipy': '1.13.1',
    'arch': '7.2.0',         # block bootstrap (Künsch 1989) — G2
    'tenacity': '9.0.0',     # retry exponencial em APIs LLM — G9
    'shap': '0.46.0',        # interpretabilidade do GBR — G12 (v3.6)
    'tensorflow': '2.17.0',  # LSTM classificação + previsão — v3.8
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

# =====================================================================
# 2. IMPORTAÇÕES
# =====================================================================
import gspread
from gspread.exceptions import WorksheetNotFound, APIError
import time
import re
import requests
import warnings
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier, GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.calibration import CalibratedClassifierCV   # G4 — v3.5
from sklearn.metrics import (
    classification_report, mean_absolute_error, mean_squared_error,
    f1_score, balanced_accuracy_score
)
from sklearn.pipeline import Pipeline

from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.forecasting.theta import ThetaModel
from statsmodels.stats.diagnostic import acorr_ljungbox, het_breuschpagan, linear_reset
from statsmodels.stats.stattools import jarque_bera, durbin_watson
from statsmodels.stats.outliers_influence import variance_inflation_factor, OLSInfluence
import statsmodels.api as sm_api
from statsmodels.tsa.stattools import (
    adfuller, kpss, grangercausalitytests, acf, pacf   # G15, G20 — v3.5
)
from statsmodels.tsa.seasonal import STL                 # G17 — v3.5

from scipy import stats as sps
from scipy.stats import boxcox, norm, ks_2samp, shapiro  # G6 — v3.5; shapiro para pressupostos
from scipy.signal import periodogram                     # G19 — v3.5

# Block bootstrap (G2) e retry (G9) — v3.5
from arch.bootstrap import MovingBlockBootstrap
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type
)

warnings.filterwarnings('ignore')
import logging
logging.getLogger('cmdstanpy').setLevel(logging.WARNING)
logging.getLogger('prophet').setLevel(logging.WARNING)

# v3.6.3 — pmdarima e Prophet são opcionais. Quando indisponíveis ou
# quebrados (quebra binária com numpy, falta de cmdstanpy, etc.), o motor
# cai para implementações nativas baseadas em statsmodels via grid-search
# de ordem com seleção por AIC, que são cientificamente equivalentes.
_PMDARIMA_OK = False
_PROPHET_OK = False
try:
    import pmdarima as pm
    # Teste real de funcionamento — não basta importar, precisa ter auto_arima
    if hasattr(pm, 'auto_arima'):
        _teste = pm.auto_arima(np.array([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24]),
                                seasonal=False, suppress_warnings=True,
                                error_action='ignore', stepwise=True, max_p=1, max_q=1)
        _PMDARIMA_OK = True
        print("[Imports] pmdarima OK — auto_arima disponível.")
    else:
        print("[Imports] pmdarima importou mas SEM auto_arima — usando fallback statsmodels.")
except Exception as _e_pm:
    print(f"[Imports] pmdarima indisponível ({type(_e_pm).__name__}) — "
          f"usando fallback baseado em statsmodels (grid-search + AIC).")

try:
    from prophet import Prophet
    # Teste real — Prophet em ambientes sem cmdstanpy quebra silenciosamente
    _df_teste = pd.DataFrame({
        'ds': pd.date_range('2020-01-01', periods=24, freq='MS'),
        'y': np.arange(24, dtype=float)
    })
    _p = Prophet(yearly_seasonality=False, weekly_seasonality=False,
                  daily_seasonality=False)
    _p.fit(_df_teste)
    if hasattr(_p, 'stan_backend') and _p.stan_backend is not None:
        _PROPHET_OK = True
        print("[Imports] Prophet OK — backend ativo.")
    else:
        print("[Imports] Prophet importou mas SEM stan_backend — usando UnobservedComponents.")
except Exception as _e_p:
    print(f"[Imports] Prophet indisponível ({type(_e_p).__name__}) — "
          f"usando UnobservedComponents (decomposição estrutural via statsmodels).")

# Imports para fallback statsmodels (sempre disponíveis)
from statsmodels.tsa.statespace.sarimax import SARIMAX as _SM_SARIMAX
from statsmodels.tsa.statespace.structural import UnobservedComponents

# v3.8 — TensorFlow/Keras para LSTM de classificação e de previsão.
# Opcional: se indisponível, classificador cai para Random Forest e
# previsão ignora o 8º modelo (LSTM Forecast).
#
# IMPORTANTE (NumPy 2.0 / Colab — fix v3.8.1):
#   - O TF cacheado em PASTA_LIBS foi compilado com NumPy 1.x e quebra
#     no Colab atual (NumPy 2.0.2). É preciso forçar o TF nativo do Colab.
#   - Não basta remover PASTA_LIBS de sys.path: quando uma tentativa
#     anterior falhou, módulos `tensorflow.*` parciais ficam em
#     `sys.modules` apontando para o cache. Python consulta sys.modules
#     ANTES de sys.path, então a próxima import volta a usar o cache.
#   - Fix definitivo: limpar TODAS as entradas tensorflow*/keras* de
#     sys.modules, invalidar caches do importlib, remover PASTA_LIBS
#     de sys.path durante a importação, e tentar APENAS o TF nativo.
_TF_OK = False
tf = None
Sequential = None
Model = None
Embedding = None
Bidirectional = None
KerasLSTM = None
Dense = None
Dropout = None
Input = None
concatenate = None
Tokenizer = None
pad_sequences = None
to_categorical = None
LabelEncoder = None
MinMaxScaler = None

def _importar_tf():
    """Importa TF nativo do Colab; ignora cache do Drive (NumPy 1.x)."""
    global _TF_OK, tf, Sequential, Model, Embedding, Bidirectional, KerasLSTM
    global Dense, Dropout, Input, concatenate, Tokenizer, pad_sequences
    global to_categorical, LabelEncoder, MinMaxScaler
    import sys as _sys

    # 1. Purga sys.modules de qualquer referência parcial a TF/Keras
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
        print(f"[Imports] Limpou {len(_mods_remover)} módulos TF/Keras "
              f"de sys.modules (resíduos de tentativa anterior).")

    # 2. Invalida caches do mecanismo de import (path_importer_cache etc.)
    try:
        import importlib
        importlib.invalidate_caches()
    except Exception:
        pass

    # 3. Remove cache do Drive de sys.path durante a importação
    _path_orig = _sys.path[:]
    _sys.path[:] = [p for p in _path_orig if p != PASTA_LIBS]

    try:
        import tensorflow as _tf_mod
        # Sanity-check: o arquivo do TF carregado precisa NÃO estar no cache
        _tf_file = getattr(_tf_mod, '__file__', '') or ''
        if PASTA_LIBS in _tf_file:
            raise ImportError(
                f"TF carregado do cache do Drive ({_tf_file}); "
                f"esperado caminho nativo do Colab. "
                f"Limpe a pasta {PASTA_LIBS}/tensorflow no Drive."
            )
        from tensorflow.keras.models import Sequential as _Seq, Model as _Mod
        from tensorflow.keras.layers import (
            Embedding as _Emb, Bidirectional as _Bid, LSTM as _KLSTM, Dense as _Den,
            Dropout as _Dro, Input as _Inp, concatenate as _conc
        )
        from tensorflow.keras.preprocessing.text import Tokenizer as _Tok
        from tensorflow.keras.preprocessing.sequence import pad_sequences as _pad
        from tensorflow.keras.utils import to_categorical as _to_cat
        from sklearn.preprocessing import LabelEncoder as _LE, MinMaxScaler as _MMS
        # Atribui as globais
        tf = _tf_mod
        Sequential = _Seq; Model = _Mod
        Embedding = _Emb; Bidirectional = _Bid; KerasLSTM = _KLSTM
        Dense = _Den; Dropout = _Dro; Input = _Inp; concatenate = _conc
        Tokenizer = _Tok; pad_sequences = _pad; to_categorical = _to_cat
        LabelEncoder = _LE; MinMaxScaler = _MMS
        tf.get_logger().setLevel('ERROR')
        _TF_OK = True
        print(f"[Imports] TensorFlow nativo OK ({_tf_file}) — LSTM disponível.")
    except Exception as _e_tf:
        msg = str(_e_tf)
        if len(msg) > 180:
            msg = msg[:180] + '...'
        print(f"[Imports] TensorFlow indisponível ({type(_e_tf).__name__}: {msg}) — "
              f"LSTM desativado; fallback Random Forest para classificação.")
        # Limpa de novo o que tentou carregar nesta tentativa
        for _m in [k for k in list(_sys.modules.keys())
                   if k == 'tensorflow' or k.startswith('tensorflow.')
                   or k == 'keras' or k.startswith('keras.')]:
            try:
                del _sys.modules[_m]
            except KeyError:
                pass
    finally:
        _sys.path[:] = _path_orig  # restaura sempre

_importar_tf()

# G12 (v3.6) — SHAP para interpretabilidade do GBR
try:
    import shap
    _SHAP_DISPONIVEL = True
except ImportError:
    _SHAP_DISPONIVEL = False
    print("[Imports] SHAP indisponível — interpretabilidade do GBR ficará limitada.")

# Versão única do motor (v4.0.5): usada em logs, METRICAS_TREINO e header.
# v4.0.5 (2026-05-14):
#   - Novo modo `reclassificacao`: reavalia chamados já classificados
#     com baixa confiança (< LIMIAR_RECLASSIFICACAO) usando o LSTM atual
#     (mais treinado) e os 4 campos textuais (B + W + X + Y).
#   - Respeita coluna AF (CONFERENCIA): se TRUE, motor NUNCA sobrescreve
#     — preserva revisão humana.
#   - Só sobrescreve se nova confiança > antiga + DELTA_MELHORIA_MINIMA.
#   - Workflow GitHub Actions dedicado roda 1× por dia.
# v4.0.4 (2026-05-14):
#   - Suporte a execução por MODO via env var MOTOR_MODO ou flag CLI:
#       * classificacao      → só LSTM + 1 lote (rápido, 15min)
#       * previsao_global    → só previsão global (médio, 45min)
#       * previsao_filtros   → só campus/tipo/categoria (pesado, 5h)
#       * ods                → só indicadores + PESOS_ODS (rápido)
#       * completo (default) → tudo (compatibilidade Colab/legado)
#     Permite dividir em 4 workflows GitHub Actions com cadências distintas.
# v4.0.3 (2026-05-14):
#   - Previsão temporal de custos mensais (Coluna Q, "Valor do chamado") —
#     série + parser preparados (Fase 4A). Refatoração de previsão para
#     reaproveitamento será aplicada em Fase 4B (sessão dedicada).
#   - Indicadores brutos por localização para painel ODS (ODS 9, 11, 12).
#   - Nova aba PESOS_ODS (configurável pelo usuário; lida pelo HTML).
# v4.0.2 (2026-05-14):
#   - Detecção automática Colab vs. local; google.colab.drive opcional.
#   - Imports do TensorFlow (Keras) elevados a escopo global para uso
#     em treinar_classificador_lstm() fora da função _importar_tf().
_VERSAO_MOTOR = "v4.0.8-ods"

print(f"[Imports] OK · pandas={pd.__version__} · {_VERSAO_MOTOR} "
      f"(pmdarima={'ON' if _PMDARIMA_OK else 'fallback'}, "
      f"Prophet={'ON' if _PROPHET_OK else 'UnobservedComponents'}, "
      f"TF={'ON' if _TF_OK else 'OFF/fallback_RF'})")

# ─────────────────────────────────────────────────────────────────────
# NumPy 2.0 compat: np.isnan() é mais estrito com tipos não-numéricos.
# _safe_isnan() converte para float antes do teste, evitando TypeError.
# _safe_float() garante Python float a partir de qualquer escalar.
# ─────────────────────────────────────────────────────────────────────
def _safe_isnan(val):
    """Retorna True se val é NaN; False para não-NaN ou não-numérico."""
    try:
        f = float(val)
        return f != f  # NaN é o único valor onde x != x é verdadeiro
    except (TypeError, ValueError):
        return False

def _safe_float(val, default=float('nan')):
    """Converte val para Python float; retorna default em caso de erro."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default



# =====================================================================
# 3. CONFIGURAÇÕES INICIAIS
# =====================================================================

# =====================================================================
# 3. CONFIGURAÇÕES INICIAIS
# =====================================================================
ARQUIVO_GOOGLE = f'{CAMINHO_PASTA}/autenticacao_google.json'
gc = gspread.service_account(filename=ARQUIVO_GOOGLE)

NOME_PLANILHA = "CHAMADOS"
NOME_MAQUINA = "GOOGLE_COLAB_CLOUD"
# v3.6.5 — Fuso horário com fallback resiliente. O pytz cacheado pode
# ter tzdata incompleto/corrompido. America/Bahia, America/Sao_Paulo e
# America/Fortaleza compartilham o mesmo offset (UTC-3) sem DST desde
# 2019, então a substituição é semanticamente equivalente para o motor.
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
                print(f"[Fuso] America/Bahia indisponível no pytz instalado. "
                      f"Usando {nome} (offset equivalente UTC-3).")
            return tz
        except Exception:
            continue
    # Último recurso: offset fixo manual via datetime
    print("[Fuso] Nenhum fuso brasileiro disponível no pytz. "
          "Usando offset fixo UTC-3.")
    from datetime import timezone as _tz_dt, timedelta as _td_dt
    return _tz_dt(_td_dt(hours=-3))

FUSO_BAHIA = _resolver_fuso_brasil()

INTERVALO_PREVISAO_CICLOS = 10    # 10 × 15 = 150 chamados
INTERVALO_RETREINO_CICLOS = 10
MIN_AMOSTRAS_TREINO = 10
MIN_PONTOS_SERIE = 6
MIN_PONTOS_SERIE_CUSTO = 12        # mínimo 12 meses para previsão de custos [v4.0.7 — reduzido de 24]
MIN_EXEMPLOS_POR_CLASSE = 3

# Eixo 2
# v3.6.5 — Holdout estendido para 12 meses (backtest visual).
# O modelo treina com dados até T-12 e prevê os 12 meses seguintes.
# Isso permite comparar visualmente previsão × real no último ano,
# além dos 12 meses futuros puros. No dashboard, o período T-12..T
# mostra dados reais + linha pontilhada de cada modelo.
HORIZONTE_HOLDOUT = 12
HORIZONTE_FORECAST = 12
N_BOOTSTRAP = 1000
N_FOLDS_CV = 3                    # v3.6.5: reduzido de 5 para 3 (holdout=12 × 3=36 meses)
SEED = 42
THRESH_OUTLIER_Z = 3.0
INTERVALO_HORAS_PREVISAO_BOOT = 24

# Constantes v3.5
BLOCK_BOOTSTRAP_AUTO = True       # tamanho do bloco via Politis-White; senão usa fixo
BLOCK_SIZE_FIXO = 6                # fallback se PW falhar (~ raiz cubica de N para N=200)
GRANGER_MAX_LAG = 6                # lag máximo para teste de Granger (meses)
ACF_PACF_LAGS = 24                 # número de lags ACF/PACF
ROTACAO_LOG_DIAS = 90              # logs com mais de N dias vão para CSV no Drive
THRESH_DRIFT_KS = 0.15             # estatística KS acima deste valor força retreino
PESO_RMSE = 0.5                    # critério multicritério G14
PESO_CRPS = 0.3
PESO_DESVIO_CV = 0.2
LLM_RETRY_MAX = 3
LLM_RETRY_WAIT_BASE = 1            # segundos (cresce exponencialmente)

# Constantes v3.6
INTERVALO_DIAS_ABLATION = 90       # ablation rodado a cada 90 dias (trimestral)
INTERVALO_DIAS_EXPORT = 30         # exportação científica mensal

# Constantes v3.8
EXECUTAR_POR_CATEGORIA = True      # gera PREVISAO_*__Cat_* por categoria hierárquica
MIN_REGISTROS_FILTRO = 12          # mín. chamados por categoria para gerar previsão
LSTM_VOCAB_SIZE = 8000             # vocabulário tokenizador LSTM classificação
LSTM_MAX_LEN = 120                 # comprimento fixo de sequência (tokens)
LSTM_EMBED_DIM = 128               # dimensão de embedding
LSTM_UNITS = 64                    # unidades LSTM bidirecionais
LSTM_FORECAST_WINDOW = 12          # janela de entrada do LSTM de previsão

# Mapeamento de colunas
COL_TITULO = 1                   # B
COL_DATA_ABERTURA = 2            # C
COL_CATEGORIA_TOPO = 4           # E
COL_CAMPUS = 7                   # H
COL_CATEGORIA_HIERARQUICA = 12   # M
COL_VALOR = 16                   # Q  — "Valor do chamado" (R$) [v4.0.3]
COL_DESCRICAO_GLPI = 22          # W
COL_TITULO_OSM = 23              # X
COL_DESCRICAO_OSM = 24           # Y
COL_CAT_IA = 25                  # Z

# Colunas opcionais (podem não existir em todas as bases) — tratar None
COL_DATA_CONCLUSAO = None        # se a planilha não tem, indicadores que dependem
                                 # disso ficam em branco. Atribua manualmente se existir.
COL_LOCAL = None                 # idem — proxy para "chamados repetidos no mesmo local"

# Filtragem por campus/tipo/categoria
FILTROS_ATIVOS = True            # True = roda análise completa por filtro após análise principal

COL_CAT_IA_OUT = 26              # Z
COL_AVALIACAO_OUT = 28           # AB
COL_EXECUTOR_OUT = 29            # AC
COL_CRITICIDADE_OUT = 30         # AD
COL_CONFERENCIA = 31             # AF — caixa de seleção [v4.0.5]
                                  # TRUE = revisado pelo usuário; motor não sobrescreve.

# Reclassificação (v4.0.5)
LIMIAR_RECLASSIFICACAO = 0.80    # reavalia tudo com confiança < 80%
DELTA_MELHORIA_MINIMA = 0.05     # só sobrescreve se nova_conf > antiga + 5pp
LOTE_RECLASSIFICACAO = 200       # máx. de chamados por execução

try:
    doc = gc.open(NOME_PLANILHA)
    planilha = doc.worksheet("CHAMADOS")
    print(f"✅ Conectado à planilha: {NOME_PLANILHA}, aba: CHAMADOS")
except Exception as e:
    print(f"❌ Erro crítico: {e}")
    raise



# =====================================================================
# 4. UTILITÁRIO DE ABAS COM CACHE
# =====================================================================

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

def recriar_aba(nome, linhas=500, colunas=10, cabecalho=None):
    """Apaga e recria aba, útil para correção de cabeçalho."""
    try:
        aba_antiga = doc.worksheet(nome)
        doc.del_worksheet(aba_antiga)
        print(f"[Migração] Aba '{nome}' apagada para recriação.")
    except WorksheetNotFound:
        pass
    if nome in _cache_abas:
        del _cache_abas[nome]
    aba = doc.add_worksheet(title=nome, rows=linhas, cols=colunas)
    if cabecalho:
        aba.update(values=[cabecalho], range_name='A1', value_input_option='USER_ENTERED')
    _cache_abas[nome] = aba
    return aba

# Migração v3.3 → v3.4: METRICAS_TREINO precisa do novo cabeçalho
ARQUIVO_FLAG_MIGRACAO = f'{CAMINHO_PASTA}/migracao_v34.flag'
if not os.path.exists(ARQUIVO_FLAG_MIGRACAO):
    print("[Migração v3.4] Executando migrações de aba uma única vez...")
    try:
        recriar_aba("METRICAS_TREINO", linhas=500, colunas=12,
                    cabecalho=["Timestamp", "N_Amostras", "N_Classes", "Acuracia",
                               "Precision_Macro", "Recall_Macro", "F1_Macro",
                               "F1_Weighted", "Balanced_Accuracy", "Hash_Base", "Maquina", "Versao_Motor"])
        print("[Migração v3.4] METRICAS_TREINO recriada com cabeçalho v3.4.")
    except Exception as e:
        print(f"[Migração v3.4] Falha (não-crítica): {e}")
    with open(ARQUIVO_FLAG_MIGRACAO, 'w') as f:
        f.write(f"Migração v3.4 executada em {datetime.now(FUSO_BAHIA).isoformat()}")


# =====================================================================
# 5. UTILITÁRIOS GERAIS
# =====================================================================

# =====================================================================
# 5. UTILITÁRIOS GERAIS
# =====================================================================
def montar_texto_classificacao(linha):
    campos = []
    if len(linha) > COL_TITULO and linha[COL_TITULO].strip():
        campos.append(linha[COL_TITULO].strip())
    if len(linha) > COL_DESCRICAO_GLPI and linha[COL_DESCRICAO_GLPI].strip():
        campos.append(linha[COL_DESCRICAO_GLPI].strip())
    if len(linha) > COL_TITULO_OSM and linha[COL_TITULO_OSM].strip():
        campos.append(linha[COL_TITULO_OSM].strip())
    if len(linha) > COL_DESCRICAO_OSM and linha[COL_DESCRICAO_OSM].strip():
        campos.append(linha[COL_DESCRICAO_OSM].strip())
    return " | ".join(campos)

def extrair_nome_executor(origem):
    """
    [v4.0.0] Mapeia origem da classificação para nome do executor.
    Origens suportadas (todas LOCAIS):
        - "Supervisionado_LSTM"            → "LSTM"
        - "Supervisionado_LSTM_baixa_conf" → "LSTM_BAIXA_CONF"
        - "RF_Fallback"                    → "RF_Fallback"
        - "RF_Fallback_baixa_conf"         → "RF_Fallback_BAIXA_CONF"
        - "SemClassificador"               → "SemClassificador"
        - "NaoProcessado"                  → "NaoProcessado"
    APIs externas (Groq/Gemini/DeepSeek/etc) foram REMOVIDAS em v4.0.0.
    """
    if not origem:
        return "Desconhecido"
    if origem == "Supervisionado_LSTM":
        return "LSTM"
    if origem == "Supervisionado_LSTM_baixa_conf":
        return "LSTM_BAIXA_CONF"
    if origem == "RF_Fallback":
        return "RF_Fallback"
    if origem == "RF_Fallback_baixa_conf":
        return "RF_Fallback_BAIXA_CONF"
    if origem == "SemClassificador":
        return "SemClassificador"
    if origem == "NaoProcessado":
        return "NaoProcessado"
    # Compatibilidade reversa para entradas antigas no log (não geradas mais):
    if origem == "Supervisionado":
        return "Supervisionado_legado"
    return origem.split(' ')[0].split('(')[0].strip()

def confianca_para_decimal(valor):
    return round(valor / 100.0, 2)

def extrair_tipo_categoria(texto):
    """Interpreta coluna M para retornar (tipo, categoria).

    Preventiva: texto contém 'Manutenção Preventiva' (ou 'Manutencao Preventiva'
                após normalização ASCII) → categoria = primeiro nível após '>',
                ex.: 'Manutenção Preventiva > Hidráulica > Instalação' → 'Hidráulica'.
    Corretiva:  demais → categoria = texto antes do primeiro '>',
                ex.: 'Elétrica > Iluminação' → 'Elétrica'.
    """
    if not texto or not texto.strip():
        return ('Desconhecida', 'Desconhecida')
    t = texto.strip()
    # Normaliza para comparação insensível a encoding (ã/a~)
    t_norm = _ud.normalize('NFKD', t).encode('ascii', 'ignore').decode('ascii').lower()
    if 'manutencao preventiva' in t_norm or 'manutenção preventiva' in t.lower():
        partes = t.split('>')
        # Primeiro subcategoria real (índice 1); fallback para texto completo
        cat = partes[1].strip() if len(partes) > 1 else t.strip()
        return ('Preventiva', cat or 'Preventiva')
    else:
        partes = t.split('>')
        cat = partes[0].strip() if partes else t.strip()
        return ('Corretiva', cat or t.strip())

import unicodedata as _ud, re as _re
def sanitizar_sufixo(label):
    """Converte label em sufixo seguro para nome de aba do Google Sheets (≤ 20 chars)."""
    s = _ud.normalize('NFKD', label).encode('ascii', 'ignore').decode('ascii')
    s = _re.sub(r'[^\w]', '_', s)
    s = _re.sub(r'_+', '_', s).strip('_')
    return s[:20]

def hash_base_treino(df):
    """Hash determinístico da base de treino para detectar mudanças."""
    if df is None or len(df) == 0:
        return "vazio"
    s = df[['Texto', 'Categoria']].sort_values(['Categoria', 'Texto']).to_csv(index=False)
    return hashlib.md5(s.encode('utf-8')).hexdigest()[:16]



# =====================================================================
# 6. CATEGORIAS VÁLIDAS
# =====================================================================

# =====================================================================
# 6. CATEGORIAS VÁLIDAS
# =====================================================================
ARQUIVO_CATEGORIAS = f'{CAMINHO_PASTA}/categorias_validas.txt'
categorias_unicas = []

def atualizar_categorias(dados_linhas):
    global categorias_unicas
    cats = sorted(list(set(
        [linha[COL_CATEGORIA_HIERARQUICA].strip()
         for linha in dados_linhas
         if len(linha) > COL_CATEGORIA_HIERARQUICA
         and linha[COL_CATEGORIA_HIERARQUICA].strip()]
    )))
    categorias_unicas = cats
    print(f"[Dicionário] {len(cats)} categorias hierárquicas únicas detectadas em M.")
    try:
        with open(ARQUIVO_CATEGORIAS, 'w', encoding='utf-8') as f:
            f.write("usados\n")
            for cat in cats:
                f.write(f"{cat}\n")
    except Exception:
        pass



# =====================================================================
# 7. CREDENCIAIS [retrocompatibilidade — APIs externas removidas v4.0.0]
# =====================================================================

# =====================================================================
# 7. CREDENCIAIS [v4.0.0]
# ---------------------------------------------------------------------
# APIs externas de LLM (Groq, Gemini, DeepSeek, OpenRouter, SambaNova)
# foram REMOVIDAS em v4.0.0. Classificação agora é 100% LOCAL via LSTM
# (fallback RandomForest em emergência). As chaves continuam sendo
# carregadas em modo opcional apenas para retrocompatibilidade — não
# são mais consultadas em runtime de classificação.
# =====================================================================
ARQUIVO_CREDENCIAIS = f'{CAMINHO_PASTA}/chaves_api.json'
matriz_chaves = {}
if os.path.exists(ARQUIVO_CREDENCIAIS):
    try:
        with open(ARQUIVO_CREDENCIAIS, 'r') as arquivo:
            matriz_chaves = json.load(arquivo)
    except Exception:
        matriz_chaves = {}

# Variáveis mantidas para retrocompatibilidade (não usadas em v4.0.0):
CHAVES_GROQ       = matriz_chaves.get("GROQ", {})
CHAVES_GEMINI     = matriz_chaves.get("GEMINI", {})
CHAVES_DEEPSEEK   = matriz_chaves.get("DEEPSEEK", {})
CHAVES_OPENROUTER = matriz_chaves.get("OPENROUTER", {})
CHAVES_SAMBANOVA  = matriz_chaves.get("SAMBANOVA", {})

print(f"[{NOME_MAQUINA}] {_VERSAO_MOTOR} — Classificação LOCAL apenas "
      f"(LSTM/RF). APIs externas de LLM desativadas.")



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
    atualizar_categorias(dados_op)
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
