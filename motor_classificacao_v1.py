# -*- coding: utf-8 -*-
"""
MOTOR DE GOVERNANÇA PREDITIVA – BIOSSISTEMAS CONSTRUÍDOS
Módulo: CLASSIFICAÇÃO E RECLASSIFICAÇÃO
Doutorado UFSB – Versão 1.0.0

Extraído de motor_v36.py v4.0.8 em 2026-05-22.
Workflows cobertos:
  • classificacao.yml    → --apenas-classificacao    (a cada 15 min)
  • reclassificacao.yml  → --apenas-reclassificacao  (diário 07:30 UTC)

Dependências removidas em relação ao motor completo:
  statsmodels, pmdarima, prophet, scipy, arch, tenacity, shap
  (usadas apenas nos módulos de previsão temporal)

Classificador primário: LSTM Bidirecional (100% local)
Fallback de emergência: RandomForest (sklearn)
APIs externas de LLM: removidas desde v4.0.0, não retornam
"""

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
ARQUIVO_LOCK = f'{PASTA_LIBS}/requirements_clf.lock'

PACOTES_REQUERIDOS = {
    'gspread': '6.1.4',
    'pandas': '2.2.3',
    'numpy': '1.26.4',
    'scikit-learn': '1.5.2',
    'pytz': '2024.2',
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
        return True, "pasta libs não existe"
    lock_atual = carregar_lock()
    if lock_atual is None:
        return True, "requirements_clf.lock ausente"
    if lock_atual != PACOTES_REQUERIDOS:
        adicionados = set(PACOTES_REQUERIDOS) - set(lock_atual)
        removidos   = set(lock_atual) - set(PACOTES_REQUERIDOS)
        alterados   = {k for k in PACOTES_REQUERIDOS
                       if k in lock_atual and PACOTES_REQUERIDOS[k] != lock_atual[k]}
        motivos = []
        if adicionados: motivos.append(f"adicionados: {', '.join(adicionados)}")
        if removidos:   motivos.append(f"removidos: {', '.join(removidos)}")
        if alterados:   motivos.append(f"versão alterada: {', '.join(alterados)}")
        return True, "; ".join(motivos)
    return False, "lock confere"

def instalar_pacotes():
    print(f"[Cache] Instalando pacotes em {PASTA_LIBS}...")
    os.makedirs(PASTA_LIBS, exist_ok=True)
    spec = [f"{nome}=={ver}" for nome, ver in PACOTES_REQUERIDOS.items()]
    cmd = ['pip', 'install', '--target', PASTA_LIBS, '--upgrade'] + spec
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        print("[Cache] ERRO na instalação:")
        print(resultado.stderr[-2000:])
        raise RuntimeError("Falha ao instalar pacotes — veja stderr acima.")
    salvar_lock(PACOTES_REQUERIDOS)
    print(f"[Cache] {len(PACOTES_REQUERIDOS)} pacotes instalados e lock salvo.")

if _EM_COLAB:
    deve_instalar, motivo = precisa_instalar()
    if deve_instalar:
        print(f"[Cache] Reinstalação necessária: {motivo}")
        instalar_pacotes()
        print("\n" + "="*70)
        print("⚠️  PACOTES INSTALADOS. Reinicie o runtime do Colab agora.")
        print("="*70 + "\n")
        try:
            import IPython
            IPython.Application.instance().kernel.do_shutdown(restart=True)
        except Exception:
            pass
        raise SystemExit("Aguardando reinício do runtime.")
    else:
        print(f"[Cache] {len(PACOTES_REQUERIDOS)} pacotes carregados do cache.")

    if PASTA_LIBS not in sys.path:
        sys.path.insert(0, PASTA_LIBS)
else:
    print("[Local] Modo offline — pacotes carregados do ambiente Python local.")

# =====================================================================
# 2. IMPORTAÇÕES
# =====================================================================
import gspread
from gspread.exceptions import WorksheetNotFound, APIError
import warnings
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    f1_score, balanced_accuracy_score, classification_report
)
from sklearn.pipeline import Pipeline

warnings.filterwarnings('ignore')

# ─── TensorFlow / Keras (opcional — fallback RF se indisponível) ──────
_TF_OK = False
tf = None
Sequential = None
Embedding = None
Bidirectional = None
KerasLSTM = None
Dense = None
Dropout = None
Tokenizer = None
pad_sequences = None
to_categorical = None
LabelEncoder = None

def _importar_tf():
    global _TF_OK, tf, Sequential, Embedding, Bidirectional, KerasLSTM
    global Dense, Dropout, Tokenizer, pad_sequences, to_categorical, LabelEncoder
    import sys as _sys

    # Purga módulos TF residuais de tentativas anteriores
    _mods = [m for m in list(_sys.modules.keys())
             if m in ('tensorflow', 'keras', 'tensorboard')
             or m.startswith(('tensorflow.', 'keras.', 'tensorboard.'))]
    for _m in _mods:
        try: del _sys.modules[_m]
        except KeyError: pass
    if _mods:
        print(f"[Imports] Limpou {len(_mods)} módulos TF/Keras de sys.modules.")

    try:
        import importlib; importlib.invalidate_caches()
    except Exception:
        pass

    _path_orig = _sys.path[:]
    _sys.path[:] = [p for p in _path_orig if p != PASTA_LIBS]

    try:
        import tensorflow as _tf_mod
        _tf_file = getattr(_tf_mod, '__file__', '') or ''
        if PASTA_LIBS in _tf_file:
            raise ImportError(
                f"TF carregado do cache do Drive ({_tf_file}). "
                f"Limpe a pasta {PASTA_LIBS}/tensorflow no Drive."
            )
        from tensorflow.keras.models import Sequential as _Seq
        from tensorflow.keras.layers import (
            Embedding as _Emb, Bidirectional as _Bid, LSTM as _KLSTM,
            Dense as _Den, Dropout as _Dro
        )
        from tensorflow.keras.preprocessing.text import Tokenizer as _Tok
        from tensorflow.keras.preprocessing.sequence import pad_sequences as _pad
        from tensorflow.keras.utils import to_categorical as _to_cat
        from sklearn.preprocessing import LabelEncoder as _LE
        tf = _tf_mod
        Sequential = _Seq; Embedding = _Emb; Bidirectional = _Bid
        KerasLSTM = _KLSTM; Dense = _Den; Dropout = _Dro
        Tokenizer = _Tok; pad_sequences = _pad; to_categorical = _to_cat
        LabelEncoder = _LE
        tf.get_logger().setLevel('ERROR')
        _TF_OK = True
        print(f"[Imports] TensorFlow nativo OK ({_tf_file}) — LSTM disponível.")
    except Exception as _e_tf:
        msg = str(_e_tf)[:180]
        print(f"[Imports] TensorFlow indisponível ({type(_e_tf).__name__}: {msg}) — "
              f"fallback Random Forest para classificação.")
        for _m in [k for k in list(_sys.modules.keys())
                   if k in ('tensorflow', 'keras') or k.startswith(('tensorflow.', 'keras.'))]:
            try: del _sys.modules[_m]
            except KeyError: pass
    finally:
        _sys.path[:] = _path_orig

_importar_tf()

_VERSAO_MOTOR = "clf-v1.0.0"
print(f"[Imports] OK · {_VERSAO_MOTOR} · TF={'ON' if _TF_OK else 'OFF/fallback_RF'}")

# =====================================================================
# 3. CONFIGURAÇÕES INICIAIS
# =====================================================================
ARQUIVO_GOOGLE = f'{CAMINHO_PASTA}/autenticacao_google.json'
gc = gspread.service_account(filename=ARQUIVO_GOOGLE)

NOME_PLANILHA = "CHAMADOS"
NOME_MAQUINA  = "GOOGLE_COLAB_CLOUD"

def _resolver_fuso_brasil():
    candidatos = [
        'America/Bahia', 'America/Sao_Paulo',
        'America/Fortaleza', 'America/Recife', 'Brazil/East',
    ]
    for nome in candidatos:
        try:
            tz = pytz.timezone(nome)
            if nome != 'America/Bahia':
                print(f"[Fuso] Usando {nome} (offset equivalente UTC-3).")
            return tz
        except Exception:
            continue
    print("[Fuso] Usando offset fixo UTC-3.")
    from datetime import timezone as _tz_dt, timedelta as _td_dt
    return _tz_dt(_td_dt(hours=-3))

FUSO_BAHIA = _resolver_fuso_brasil()

# Limites e limiares de classificação
MIN_AMOSTRAS_TREINO     = 10
MIN_EXEMPLOS_POR_CLASSE = 3
ROTACAO_LOG_DIAS        = 90
LIMIAR_RECLASSIFICACAO  = 0.80
DELTA_MELHORIA_MINIMA   = 0.05
LOTE_RECLASSIFICACAO    = 200
LIMIAR_CONFIANCA        = 70
LIMIAR_ALTA_CONFIANCA   = 95.0
TAMANHO_LOTE            = 15
SEED                    = 42

# LSTM de classificação
LSTM_VOCAB_SIZE = 8000
LSTM_MAX_LEN    = 120
LSTM_EMBED_DIM  = 128
LSTM_UNITS      = 64

# Mapeamento de colunas (base CHAMADOS)
COL_TITULO               = 1   # B
COL_DATA_ABERTURA        = 2   # C
COL_CATEGORIA_HIERARQUICA = 12  # M
COL_DESCRICAO_GLPI       = 22  # W
COL_TITULO_OSM           = 23  # X
COL_DESCRICAO_OSM        = 24  # Y
COL_CAT_IA               = 25  # Z
COL_CAT_IA_OUT           = 26  # Z
COL_AVALIACAO_OUT        = 28  # AB
COL_EXECUTOR_OUT         = 29  # AC
COL_CRITICIDADE_OUT      = 30  # AD
COL_CONFERENCIA          = 31  # AF — TRUE = revisado pelo usuário, motor não sobrescreve

try:
    doc       = gc.open(NOME_PLANILHA)
    planilha  = doc.worksheet("CHAMADOS")
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
                aba.update(values=[cabecalho], range_name='A1',
                           value_input_option='USER_ENTERED')
        except Exception as e:
            print(f"[Aviso] Não foi possível gravar cabeçalho em {nome}: {e}")
    _cache_abas[nome] = aba
    return aba

def recriar_aba(nome, linhas=500, colunas=10, cabecalho=None):
    try:
        aba_antiga = doc.worksheet(nome)
        doc.del_worksheet(aba_antiga)
    except WorksheetNotFound:
        pass
    if nome in _cache_abas:
        del _cache_abas[nome]
    aba = doc.add_worksheet(title=nome, rows=linhas, cols=colunas)
    if cabecalho:
        aba.update(values=[cabecalho], range_name='A1',
                   value_input_option='USER_ENTERED')
    _cache_abas[nome] = aba
    return aba

# Migração v3.3 → v3.4: garante cabeçalho correto em METRICAS_TREINO
ARQUIVO_FLAG_MIGRACAO = f'{CAMINHO_PASTA}/migracao_v34.flag'
if not os.path.exists(ARQUIVO_FLAG_MIGRACAO):
    try:
        recriar_aba("METRICAS_TREINO", linhas=500, colunas=12,
                    cabecalho=["Timestamp", "N_Amostras", "N_Classes", "Acuracia",
                               "Precision_Macro", "Recall_Macro", "F1_Macro",
                               "F1_Weighted", "Balanced_Accuracy", "Hash_Base",
                               "Maquina", "Versao_Motor"])
        print("[Migração v3.4] METRICAS_TREINO recriada.")
    except Exception as e:
        print(f"[Migração v3.4] Falha (não-crítica): {e}")
    with open(ARQUIVO_FLAG_MIGRACAO, 'w') as f:
        f.write(f"Migração v3.4 executada em {datetime.now(FUSO_BAHIA).isoformat()}")

# =====================================================================
# 5. UTILITÁRIOS GERAIS (apenas os usados por classificação)
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
    """Mapeia origem da classificação para nome do executor (100% local desde v4.0.0)."""
    if not origem:
        return "Desconhecido"
    mapa = {
        "Supervisionado_LSTM":            "LSTM",
        "Supervisionado_LSTM_baixa_conf": "LSTM_BAIXA_CONF",
        "RF_Fallback":                    "RF_Fallback",
        "RF_Fallback_baixa_conf":         "RF_Fallback_BAIXA_CONF",
        "Reclassificacao_LSTM":           "Reclass_LSTM",
        "Reclassificacao_RF":             "Reclass_RF",
        "SemClassificador":               "SemClassificador",
        "NaoProcessado":                  "NaoProcessado",
        "Supervisionado":                 "Supervisionado_legado",
    }
    return mapa.get(origem, origem.split(' ')[0].split('(')[0].strip())

def confianca_para_decimal(valor):
    return round(valor / 100.0, 2)

def hash_base_treino(df):
    if df is None or len(df) == 0:
        return "vazio"
    s = df[['Texto', 'Categoria']].sort_values(['Categoria', 'Texto']).to_csv(index=False)
    return hashlib.md5(s.encode('utf-8')).hexdigest()[:16]

def estimar_criticidade(texto):
    t = texto.lower()
    alta  = ['urgente', 'incêndio', 'queda', 'choque', 'alagamento',
             'infiltração grave', 'perigo']
    media = ['reparo', 'substituição', 'quebra', 'falha', 'defeito', 'corretiva']
    if any(p in t for p in alta):
        return "Alta"
    if any(p in t for p in media):
        return "Média"
    return "Baixa"

# =====================================================================
# 6. CATEGORIAS VÁLIDAS
# =====================================================================
ARQUIVO_CATEGORIAS = f'{CAMINHO_PASTA}/categorias_validas.txt'
categorias_unicas = []

def atualizar_categorias(dados_linhas):
    global categorias_unicas
    cats = sorted(list(set(
        linha[COL_CATEGORIA_HIERARQUICA].strip()
        for linha in dados_linhas
        if len(linha) > COL_CATEGORIA_HIERARQUICA
        and linha[COL_CATEGORIA_HIERARQUICA].strip()
    )))
    categorias_unicas = cats
    print(f"[Dicionário] {len(cats)} categorias hierárquicas únicas.")
    try:
        with open(ARQUIVO_CATEGORIAS, 'w', encoding='utf-8') as f:
            f.write("usados\n")
            for cat in cats:
                f.write(f"{cat}\n")
    except Exception:
        pass

print(f"[{NOME_MAQUINA}] {_VERSAO_MOTOR} — Classificação LOCAL apenas (LSTM/RF).")

# =====================================================================
# 8. EIXO 1 – CLASSIFICAÇÃO SUPERVISIONADA
# =====================================================================

def popular_treinamento_a_partir_de_chamados(dados_linhas):
    aba_treino = obter_aba(
        "TREINAMENTO", linhas=2000, colunas=4,
        cabecalho=["Texto", "Categoria", "Linha_Origem", "Data_Insercao"]
    )
    candidatos = []
    for i, linha in enumerate(dados_linhas, start=2):
        if len(linha) <= COL_CATEGORIA_HIERARQUICA:
            continue
        cat = linha[COL_CATEGORIA_HIERARQUICA].strip()
        if not cat:
            continue
        texto = montar_texto_classificacao(linha)
        if len(texto) < 5:
            continue
        candidatos.append([texto, cat, i,
                            datetime.now(FUSO_BAHIA).strftime('%d/%m/%Y %H:%M:%S')])

    if not candidatos:
        print("[Treino] Nenhum chamado com categoria hierárquica em M.")
        return None

    try:
        atuais = aba_treino.get_all_values()
        n_atual = max(len(atuais) - 1, 0)
    except Exception:
        n_atual = 0

    if n_atual == 0 or len(candidatos) >= int(n_atual * 1.2):
        try:
            aba_treino.clear()
            aba_treino.update(
                values=[["Texto", "Categoria", "Linha_Origem", "Data_Insercao"]] + candidatos,
                range_name='A1', value_input_option='USER_ENTERED'
            )
            print(f"[Treino] TREINAMENTO atualizada com {len(candidatos)} amostras.")
        except APIError as e:
            print(f"[Treino] Erro ao gravar TREINAMENTO: {e}")

    return pd.DataFrame(candidatos,
                        columns=["Texto", "Categoria", "Linha_Origem", "Data_Insercao"])

def carregar_dados_rotulados(dados_linhas=None):
    if dados_linhas is not None:
        popular_treinamento_a_partir_de_chamados(dados_linhas)
    try:
        aba_treino = obter_aba("TREINAMENTO", linhas=2000, colunas=4)
        dados = aba_treino.get_all_values()
    except Exception:
        return None
    if len(dados) < 2:
        return None
    df = pd.DataFrame(dados[1:], columns=dados[0])
    if 'Categoria' not in df.columns or 'Texto' not in df.columns:
        return None
    if categorias_unicas:
        df = df[df['Categoria'].isin(categorias_unicas)]
    df = df[df['Texto'].str.len() >= 5]
    return df

_ultimo_hash_treino = None

def hash_existe_em_metricas(hash_atual):
    try:
        aba = obter_aba("METRICAS_TREINO", linhas=500, colunas=12)
        valores = aba.get_all_values()
        if len(valores) < 2:
            return False
        for linha in valores[1:]:
            if len(linha) > 9 and linha[9].strip() == hash_atual:
                return True
        return False
    except Exception:
        return False


def treinar_classificador(df_treino, forcar=False):
    """Treina RandomForest com calibração de probabilidades (fallback do LSTM)."""
    global _ultimo_hash_treino

    if df_treino is None or len(df_treino) < MIN_AMOSTRAS_TREINO:
        print(f"[Treino RF] Insuficiente: {0 if df_treino is None else len(df_treino)} amostras.")
        return None, None

    contagem = df_treino['Categoria'].value_counts()
    MIN_PARA_ISOTONIC = 5
    MIN_PARA_SIGMOID  = 4
    classes_validas = contagem[contagem >= MIN_EXEMPLOS_POR_CLASSE].index
    n_descartadas = (contagem < MIN_EXEMPLOS_POR_CLASSE).sum()
    if n_descartadas > 0:
        print(f"[Treino RF] {n_descartadas} categorias descartadas.")
    df_treino = df_treino[df_treino['Categoria'].isin(classes_validas)]
    if len(df_treino) < MIN_AMOSTRAS_TREINO:
        return None, None

    h = hash_base_treino(df_treino)
    if not forcar and h == _ultimo_hash_treino and hash_existe_em_metricas(h):
        print(f"[Treino RF] Base inalterada (hash {h}). Métricas não regravadas.")
        skip_metrics = True
    else:
        skip_metrics = False

    print(f"[Treino RF] {len(classes_validas)} categorias, {len(df_treino)} amostras.")
    X, y = df_treino['Texto'], df_treino['Categoria']
    try:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, stratify=y, random_state=SEED)
    except ValueError:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=SEED)

    contagem_treino = pd.Series(y_train).value_counts()
    min_por_classe = int(contagem_treino.min())
    base_rf = RandomForestClassifier(n_estimators=200, random_state=SEED, n_jobs=-1)

    if min_por_classe >= MIN_PARA_ISOTONIC:
        clf = CalibratedClassifierCV(base_rf, method='isotonic', cv=3)
        metodo = 'isotonic (cv=3)'
    elif min_por_classe >= MIN_PARA_SIGMOID:
        clf = CalibratedClassifierCV(base_rf, method='sigmoid', cv=3)
        metodo = 'sigmoid (cv=3)'
    elif min_por_classe >= 2:
        clf = CalibratedClassifierCV(base_rf, method='sigmoid', cv=2)
        metodo = 'sigmoid (cv=2)'
    else:
        clf = base_rf
        metodo = 'RF puro (calibração inviável)'

    print(f"[Treino RF] Calibração: {metodo} (min exemplos/classe treino = {min_por_classe})")

    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(max_features=5000, ngram_range=(1, 2))),
        ('clf', clf)
    ])
    try:
        pipeline.fit(X_train, y_train)
    except ValueError as e:
        if 'cross-validation' in str(e) or 'less than' in str(e):
            print(f"[Treino RF] Calibração falhou ({str(e)[:80]}). Caindo para RF puro.")
            pipeline = Pipeline([
                ('tfidf', TfidfVectorizer(max_features=5000, ngram_range=(1, 2))),
                ('clf', base_rf)
            ])
            pipeline.fit(X_train, y_train)
        else:
            raise

    y_pred = pipeline.predict(X_test)
    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
    f1_w   = f1_score(y_test, y_pred, average='weighted', zero_division=0)
    bal_acc = balanced_accuracy_score(y_test, y_pred)
    metrics = {
        'accuracy': report['accuracy'],
        'f1_macro': report['macro avg']['f1-score'],
        'f1_weighted': float(f1_w),
        'balanced_accuracy': float(bal_acc),
        'n_amostras': len(df_treino),
        'n_classes': len(classes_validas),
        'hash_base': h
    }
    print(f"[Treino RF] Acc={metrics['accuracy']:.3f} | F1_macro={metrics['f1_macro']:.3f}")

    if not skip_metrics:
        _gravar_metricas(metrics, sufixo='[RF]')
        _ultimo_hash_treino = h

    return pipeline, metrics


# =====================================================================
# LSTM DE CLASSIFICAÇÃO TEXTUAL (classificador primário — v4.0.0)
# Arquitetura:
#   Embedding(8000, 128) → BiLSTM(64) → Dropout(0.5) → Dense(64,ReLU) → Dense(K,Softmax)
# =====================================================================
class LSTMClassifier:
    """Wrapper LSTM compatível com a interface sklearn (predict, predict_proba, classes_)."""
    def __init__(self, model, tokenizer, encoder, max_len):
        self._model = model
        self._tok   = tokenizer
        self._enc   = encoder
        self._max_len = max_len
        self.classes_ = encoder.classes_

    def predict(self, textos):
        seqs = self._tok.texts_to_sequences(textos)
        X = pad_sequences(seqs, maxlen=self._max_len, padding='post', truncating='post')
        probs = self._model.predict(X, verbose=0)
        return self._enc.inverse_transform(np.argmax(probs, axis=1))

    def predict_proba(self, textos):
        seqs = self._tok.texts_to_sequences(textos)
        X = pad_sequences(seqs, maxlen=self._max_len, padding='post', truncating='post')
        return self._model.predict(X, verbose=0)


def treinar_classificador_lstm(df_treino, forcar=False):
    """
    Treina LSTM Bidirecional para classificação textual.
    Em emergência (TF indisponível, OOM, crash), faz fallback para RandomForest.
    Nunca cai para LLM externo.
    """
    global _ultimo_hash_treino

    if not _TF_OK:
        print("[LSTM Clf] TensorFlow indisponível — fallback Random Forest.")
        return treinar_classificador(df_treino, forcar=forcar)

    if df_treino is None or len(df_treino) < MIN_AMOSTRAS_TREINO:
        n = 0 if df_treino is None else len(df_treino)
        print(f"[LSTM Clf] Base insuficiente ({n}) — fallback RF.")
        return treinar_classificador(df_treino, forcar=forcar)

    contagem = df_treino['Categoria'].value_counts()
    classes_validas = contagem[contagem >= MIN_EXEMPLOS_POR_CLASSE].index
    n_desc = (contagem < MIN_EXEMPLOS_POR_CLASSE).sum()
    if n_desc > 0:
        print(f"[LSTM Clf] {n_desc} categorias descartadas.")
    df_treino = df_treino[df_treino['Categoria'].isin(classes_validas)]
    if len(df_treino) < MIN_AMOSTRAS_TREINO:
        print("[LSTM Clf] Após filtro, ficou abaixo do mínimo — fallback RF.")
        return treinar_classificador(df_treino, forcar=forcar)

    h_base = hash_base_treino(df_treino)
    if not forcar and h_base == _ultimo_hash_treino and hash_existe_em_metricas(h_base):
        print(f"[LSTM Clf] Base inalterada (hash {h_base}). Métricas não regravadas.")
        skip_metrics = True
    else:
        skip_metrics = False

    print(f"[LSTM Clf] Treinando com {len(classes_validas)} categorias "
          f"e {len(df_treino)} amostras.")

    try:
        textos = df_treino['Texto'].tolist()
        rotulos = df_treino['Categoria'].tolist()

        tok = Tokenizer(num_words=LSTM_VOCAB_SIZE, oov_token='<OOV>')
        tok.fit_on_texts(textos)
        seqs = tok.texts_to_sequences(textos)
        X = pad_sequences(seqs, maxlen=LSTM_MAX_LEN, padding='post', truncating='post')

        enc = LabelEncoder()
        y_int = enc.fit_transform(rotulos)
        K = len(enc.classes_)

        try:
            X_tr, X_te, y_tr_int, y_te_int = train_test_split(
                X, y_int, test_size=0.2, stratify=y_int, random_state=SEED)
            tipo_split = 'estratificado'
        except ValueError:
            X_tr, X_te, y_tr_int, y_te_int = train_test_split(
                X, y_int, test_size=0.2, random_state=SEED)
            tipo_split = 'simples'
        Y_tr = to_categorical(y_tr_int, num_classes=K)
        Y_te = to_categorical(y_te_int, num_classes=K)
        print(f"[LSTM Clf] Split {tipo_split}: {len(X_tr)} treino / {len(X_te)} teste.")

        model = Sequential([
            Embedding(LSTM_VOCAB_SIZE, LSTM_EMBED_DIM, input_length=LSTM_MAX_LEN),
            Bidirectional(KerasLSTM(LSTM_UNITS)),
            Dropout(0.5),
            Dense(64, activation='relu'),
            Dense(K, activation='softmax')
        ])
        model.compile(loss='categorical_crossentropy', optimizer='adam', metrics=['accuracy'])

        from tensorflow.keras.callbacks import EarlyStopping
        es = EarlyStopping(monitor='val_loss', patience=4, restore_best_weights=True)
        hist = model.fit(X_tr, Y_tr, epochs=50, batch_size=32,
                         validation_data=(X_te, Y_te), callbacks=[es], verbose=0)
        n_epocas = len(hist.history.get('loss', []))
        print(f"[LSTM Clf] Treino concluído em {n_epocas} épocas.")

        probs_te = model.predict(X_te, verbose=0)
        y_pred_int = np.argmax(probs_te, axis=1)
        from sklearn.metrics import f1_score as _f1, balanced_accuracy_score as _bac, accuracy_score as _acc
        acc     = float(_acc(y_te_int, y_pred_int))
        f1_mac  = float(_f1(y_te_int, y_pred_int, average='macro', zero_division=0))
        f1_w    = float(_f1(y_te_int, y_pred_int, average='weighted', zero_division=0))
        bal_acc = float(_bac(y_te_int, y_pred_int))
        print(f"[LSTM Clf] Acc={acc:.3f} | F1_macro={f1_mac:.3f} | "
              f"F1_w={f1_w:.3f} | Bal.Acc={bal_acc:.3f}")

        clf_wrapper = LSTMClassifier(model, tok, enc, LSTM_MAX_LEN)
        metricas = {
            'accuracy': acc, 'f1_macro': f1_mac, 'f1_weighted': f1_w,
            'balanced_accuracy': bal_acc, 'n_amostras': len(df_treino),
            'n_classes': K, 'hash_base': h_base,
            'modelo': 'LSTM_Bidirecional', 'epocas_treino': n_epocas
        }

        if not skip_metrics:
            _gravar_metricas(metricas, sufixo='[LSTM]')
            _ultimo_hash_treino = h_base

        return clf_wrapper, metricas

    except Exception as e:
        import traceback
        print(f"[LSTM Clf] Falha ({type(e).__name__}: {e}) — fallback Random Forest.")
        traceback.print_exc()
        return treinar_classificador(df_treino, forcar=forcar)


def _gravar_metricas(metrics, sufixo=''):
    """Grava linha em METRICAS_TREINO. Função interna compartilhada entre LSTM e RF."""
    try:
        aba = obter_aba(
            "METRICAS_TREINO", linhas=500, colunas=12,
            cabecalho=["Timestamp", "N_Amostras", "N_Classes", "Acuracia",
                       "Precision_Macro", "Recall_Macro", "F1_Macro",
                       "F1_Weighted", "Balanced_Accuracy", "Hash_Base",
                       "Maquina", "Versao_Motor"]
        )
        ts = datetime.now(FUSO_BAHIA).strftime('%d/%m/%Y %H:%M:%S')
        aba.append_row(
            [ts,
             metrics.get('n_amostras', ''),
             metrics.get('n_classes', ''),
             round(metrics.get('accuracy', 0), 4),
             round(metrics.get('precision_macro', 0), 4),
             round(metrics.get('recall_macro', 0), 4),
             round(metrics.get('f1_macro', 0), 4),
             round(metrics.get('f1_weighted', 0), 4),
             round(metrics.get('balanced_accuracy', 0), 4),
             metrics.get('hash_base', ''),
             f"{NOME_MAQUINA} {sufixo}",
             _VERSAO_MOTOR],
            value_input_option='USER_ENTERED'
        )
        print(f"[Treino] METRICAS_TREINO atualizada (hash {metrics.get('hash_base','?')}).")
    except Exception as e:
        print(f"[Treino] Aviso: falha ao gravar METRICAS_TREINO: {e}")


def classificar_supervisionado(pipeline, texto, categorias_validas):
    probas = pipeline.predict_proba([texto])[0]
    idx_max = np.argmax(probas)
    confianca = probas[idx_max] * 100
    cat_predita = pipeline.classes_[idx_max]
    if confianca < 50:
        return "PENDENTE_REVISAO", confianca
    return cat_predita, confianca

# =====================================================================
# 9. LOG DE AUDITORIA
# =====================================================================
def rotacionar_logs_se_necessario():
    """Move logs com mais de ROTACAO_LOG_DIAS dias para CSV — roda 1×/dia."""
    flag_arq = f'{CAMINHO_PASTA}/.ultima_rotacao_log'
    hoje = datetime.now(FUSO_BAHIA).date()
    if os.path.exists(flag_arq):
        try:
            with open(flag_arq, 'r') as f:
                ultima_data = datetime.fromisoformat(f.read().strip()).date()
            if ultima_data == hoje:
                return
        except Exception:
            pass

    try:
        aba_log = obter_aba("LOG_CLASSIFICACAO", linhas=5000, colunas=10)
        valores = aba_log.get_all_values()
        if len(valores) < 2:
            return
        cab, rows = valores[0], valores[1:]
        limite = datetime.now(FUSO_BAHIA) - timedelta(days=ROTACAO_LOG_DIAS)
        antigos, recentes = [], []
        for r in rows:
            try:
                ts = datetime.strptime(r[0], '%d/%m/%Y %H:%M:%S')
                if hasattr(FUSO_BAHIA, 'localize'):
                    ts = FUSO_BAHIA.localize(ts)
                else:
                    ts = ts.replace(tzinfo=FUSO_BAHIA)
                (antigos if ts < limite else recentes).append(r)
            except Exception:
                recentes.append(r)

        if not antigos:
            with open(flag_arq, 'w') as f:
                f.write(datetime.now(FUSO_BAHIA).isoformat())
            return

        pasta_arq = f'{CAMINHO_PASTA}/logs_arquivo'
        os.makedirs(pasta_arq, exist_ok=True)
        por_mes = {}
        for r in antigos:
            try:
                chave = datetime.strptime(r[0], '%d/%m/%Y %H:%M:%S').strftime('%Y_%m')
            except Exception:
                chave = 'sem_data'
            por_mes.setdefault(chave, []).append(r)

        for chave, linhas_mes in por_mes.items():
            arq_csv = f'{pasta_arq}/log_{chave}.csv'
            modo = 'a' if os.path.exists(arq_csv) else 'w'
            df_export = pd.DataFrame(linhas_mes, columns=cab[:len(linhas_mes[0])])
            df_export.to_csv(arq_csv, mode=modo, header=(modo == 'w'),
                             index=False, encoding='utf-8')

        aba_log.clear()
        aba_log.update(values=[cab] + recentes, range_name='A1',
                       value_input_option='USER_ENTERED')
        with open(flag_arq, 'w') as f:
            f.write(datetime.now(FUSO_BAHIA).isoformat())
        print(f"[Rotação] {len(antigos)} log(s) arquivado(s).")
    except Exception as e:
        print(f"[Rotação] Falha não-fatal: {e}")


def registrar_log(num_linha, texto, cat_original, cat_ia, confianca,
                  criticidade, origem, decisao):
    try:
        aba_log = obter_aba(
            "LOG_CLASSIFICACAO", linhas=5000, colunas=9,
            cabecalho=["Timestamp", "Linha", "Texto", "Cat_Original",
                       "Cat_IA", "Confianca", "Criticidade", "Origem", "Decisao"]
        )
        ts = datetime.now(FUSO_BAHIA).strftime('%d/%m/%Y %H:%M:%S')
        aba_log.append_row(
            [ts, num_linha, texto[:120], cat_original, cat_ia,
             confianca_para_decimal(confianca), criticidade, origem, decisao],
            value_input_option='USER_ENTERED'
        )
    except Exception as e:
        print(f"[Aviso] Falha ao gravar log da linha {num_linha}: {e}")

# =====================================================================
# 10. MODOS DE EXECUÇÃO
# =====================================================================

def _modo_classificacao():
    """Treina/carrega LSTM + processa 1 lote de 15 chamados pendentes."""
    print("[Modo classificacao] Iniciando.")
    try:
        todas_linhas = planilha.get_all_values()
    except APIError as e:
        print(f"[Modo classificacao] Falha ao ler planilha: {e}")
        return

    dados_op = todas_linhas[1:]
    atualizar_categorias(dados_op)

    df_treino = carregar_dados_rotulados(dados_op)
    pipeline, _ = (treinar_classificador_lstm(df_treino)
                   if df_treino is not None else (None, None))
    _eh_lstm = isinstance(pipeline, LSTMClassifier)
    nome_orig_alta  = "Supervisionado_LSTM"            if _eh_lstm else "RF_Fallback"
    nome_orig_baixa = "Supervisionado_LSTM_baixa_conf" if _eh_lstm else "RF_Fallback_baixa_conf"
    print(f"[Modo classificacao] Classificador: {'LSTM' if _eh_lstm else ('RF' if pipeline else 'NENHUM')}")

    # Coleta lote de pendentes (coluna Z vazia)
    lote = []
    for i, linha in enumerate(todas_linhas):
        if i == 0:
            continue
        cat_ia = linha[COL_CAT_IA].strip() if len(linha) > COL_CAT_IA else ""
        if cat_ia == "":
            texto = montar_texto_classificacao(linha)
            if not texto:
                continue
            cat_orig = (linha[COL_CATEGORIA_HIERARQUICA]
                        if len(linha) > COL_CATEGORIA_HIERARQUICA else "")
            lote.append({"num_linha": i + 1, "texto": texto, "cat_original": cat_orig})
            if len(lote) >= TAMANHO_LOTE:
                break

    if not lote:
        print("[Modo classificacao] Nenhum chamado pendente. Encerrando.")
        return

    for item in lote:
        if pipeline is None:
            item.update(cat_predita=item['cat_original'] or 'PENDENTE_REVISAO',
                        confianca=0, origem='SemClassificador')
            continue
        cat, conf = classificar_supervisionado(pipeline, item['texto'], categorias_unicas)
        if cat == "PENDENTE_REVISAO" or conf < LIMIAR_CONFIANCA:
            item.update(cat_predita=item['cat_original'] or 'PENDENTE_REVISAO',
                        confianca=conf, origem=nome_orig_baixa)
        elif conf >= LIMIAR_ALTA_CONFIANCA:
            item.update(cat_predita=cat, confianca=conf, origem=nome_orig_alta)
        else:
            item.update(cat_predita=cat, confianca=conf, origem=nome_orig_baixa)

    celulas = []
    for item in lote:
        if item['cat_predita'] not in categorias_unicas and \
                item['cat_predita'] != 'PENDENTE_REVISAO':
            item['cat_predita'] = 'PENDENTE_REVISAO'
        crit     = estimar_criticidade(item['texto'])
        executor = extrair_nome_executor(item['origem'])
        num      = item['num_linha']
        celulas += [
            gspread.Cell(num, COL_CAT_IA_OUT,       item['cat_predita']),
            gspread.Cell(num, COL_AVALIACAO_OUT,     confianca_para_decimal(item['confianca'])),
            gspread.Cell(num, COL_EXECUTOR_OUT,      executor),
            gspread.Cell(num, COL_CRITICIDADE_OUT,   crit),
        ]
        registrar_log(num, item['texto'], item['cat_original'], item['cat_predita'],
                      item['confianca'], crit, item['origem'], "Processado")

    try:
        planilha.update_cells(celulas, value_input_option='USER_ENTERED')
        print(f"[Modo classificacao] {len(lote)} chamados classificados e gravados.")
    except APIError as e:
        print(f"[Modo classificacao] Erro ao gravar: {e}")


def _modo_reclassificacao():
    """
    Reavalia chamados já classificados com baixa confiança.
    Respeita coluna AF (CONFERENCIA=TRUE → não sobrescreve revisão humana).
    Só sobrescreve se nova_conf > antiga + DELTA_MELHORIA_MINIMA ou mudança com alta conf.
    """
    print("[Modo reclassificacao] Iniciando.")
    try:
        todas_linhas = planilha.get_all_values()
    except APIError as e:
        print(f"[Modo reclassificacao] Falha ao ler planilha: {e}")
        return

    dados_op = todas_linhas[1:]
    atualizar_categorias(dados_op)

    df_treino = carregar_dados_rotulados(dados_op)
    pipeline, _ = (treinar_classificador_lstm(df_treino)
                   if df_treino is not None else (None, None))
    if pipeline is None:
        print("[Modo reclassificacao] Sem classificador disponível. Encerrando.")
        return
    _eh_lstm = isinstance(pipeline, LSTMClassifier)
    nome_origem = "Reclassificacao_LSTM" if _eh_lstm else "Reclassificacao_RF"
    print(f"[Modo reclassificacao] Classificador: {'LSTM' if _eh_lstm else 'RF'} | "
          f"Limiar={LIMIAR_RECLASSIFICACAO} | Delta={DELTA_MELHORIA_MINIMA}")

    candidatos = []
    for i, linha in enumerate(todas_linhas):
        if i == 0:
            continue
        if len(linha) <= COL_AVALIACAO_OUT:
            continue
        cat_atual = (linha[COL_CAT_IA_OUT] or '').strip() if len(linha) > COL_CAT_IA_OUT else ''
        if not cat_atual:
            continue
        # Respeita conferência humana
        conf_marcada = ''
        if len(linha) > COL_CONFERENCIA:
            conf_marcada = (linha[COL_CONFERENCIA] or '').strip().upper()
        if conf_marcada in ('TRUE', 'VERDADEIRO', '1', 'SIM'):
            continue
        # Filtra por confiança abaixo do limiar
        try:
            conf_antiga = float(str(linha[COL_AVALIACAO_OUT]).replace(',', '.'))
        except (ValueError, TypeError):
            continue
        if conf_antiga >= LIMIAR_RECLASSIFICACAO:
            continue
        texto = montar_texto_classificacao(linha)
        if not texto or len(texto) < 5:
            continue
        cat_orig = linha[COL_CATEGORIA_HIERARQUICA] if len(linha) > COL_CATEGORIA_HIERARQUICA else ''
        candidatos.append({
            'num_linha': i + 1, 'texto': texto,
            'cat_original': cat_orig, 'cat_atual': cat_atual,
            'conf_antiga': conf_antiga
        })
        if len(candidatos) >= LOTE_RECLASSIFICACAO:
            break

    if not candidatos:
        print("[Modo reclassificacao] Nenhum chamado elegível.")
        return
    print(f"[Modo reclassificacao] {len(candidatos)} candidato(s) com "
          f"confiança < {LIMIAR_RECLASSIFICACAO}.")

    celulas_update = []
    n_alterados = n_inalterados = 0
    for c in candidatos:
        nova_cat, nova_conf_pct = classificar_supervisionado(
            pipeline, c['texto'], categorias_unicas)
        nova_conf = nova_conf_pct / 100.0

        sobrescrever = False
        motivo = ''
        if nova_cat == 'PENDENTE_REVISAO':
            motivo = 'nova_cat=PENDENTE_REVISAO'
        elif nova_cat == c['cat_atual'] and nova_conf > c['conf_antiga'] + DELTA_MELHORIA_MINIMA:
            sobrescrever = True; motivo = 'mesma cat, +confiança'
        elif nova_cat != c['cat_atual'] and nova_conf >= LIMIAR_RECLASSIFICACAO:
            sobrescrever = True; motivo = 'nova cat, alta confiança'
        elif nova_conf > c['conf_antiga'] + DELTA_MELHORIA_MINIMA:
            sobrescrever = True; motivo = 'melhoria forte'

        if not sobrescrever:
            n_inalterados += 1
            continue

        crit     = estimar_criticidade(c['texto'])
        executor = extrair_nome_executor(nome_origem)
        num      = c['num_linha']
        celulas_update += [
            gspread.Cell(num, COL_CAT_IA_OUT,     nova_cat),
            gspread.Cell(num, COL_AVALIACAO_OUT,   confianca_para_decimal(nova_conf_pct)),
            gspread.Cell(num, COL_EXECUTOR_OUT,    executor),
            gspread.Cell(num, COL_CRITICIDADE_OUT, crit),
        ]
        registrar_log(num, c['texto'], c['cat_original'], nova_cat,
                      nova_conf_pct, crit, nome_origem,
                      f"Reclass: {c['cat_atual']}→{nova_cat} "
                      f"({c['conf_antiga']:.2f}→{nova_conf:.2f}) [{motivo}]")
        n_alterados += 1

    if celulas_update:
        try:
            planilha.update_cells(celulas_update, value_input_option='USER_ENTERED')
            print(f"[Modo reclassificacao] {n_alterados} reclassificado(s), "
                  f"{n_inalterados} mantido(s).")
        except APIError as e:
            print(f"[Modo reclassificacao] Erro ao gravar: {e}")
    else:
        print(f"[Modo reclassificacao] Nenhuma alteração aplicável.")

# =====================================================================
# 11. ENTRY POINT
# =====================================================================
import sys as _sys_entry
_argv = _sys_entry.argv

# Flags CLI → variáveis de ambiente
if '--ciclo-unico' in _argv:
    os.environ['MOTOR_MAX_CICLOS'] = '1'
    print("[Entry] --ciclo-unico → MOTOR_MAX_CICLOS=1")

_MODOS_CLI = {
    '--apenas-classificacao':   'classificacao',
    '--apenas-reclassificacao': 'reclassificacao',
}
for _flag, _modo in _MODOS_CLI.items():
    if _flag in _argv:
        os.environ['MOTOR_MODO'] = _modo
        os.environ['MOTOR_MAX_CICLOS'] = '1'
        print(f"[Entry] {_flag} → MOTOR_MODO={_modo}")
        break

MODO = os.environ.get('MOTOR_MODO', 'classificacao').strip().lower()
print(f"\n{'='*70}")
print(f"MÓDULO CLASSIFICAÇÃO — {_VERSAO_MOTOR}")
print(f"MODO = {MODO}")
print(f"{'='*70}\n")

rotacionar_logs_se_necessario()

if MODO == 'classificacao':
    _modo_classificacao()
elif MODO == 'reclassificacao':
    _modo_reclassificacao()
else:
    print(f"[Entry] MODO '{MODO}' não reconhecido neste módulo.")
    print("        Modos válidos: classificacao | reclassificacao")
    print("        Para previsão, use motor_previsao_chamados.py")
    print("        Para custos,   use motor_previsao_custos.py")
    print("        Para filtros,  use motor_previsao_filtros.py")
    print("        Para ODS,      use motor_ods.py")
