# -*- coding: utf-8 -*-
"""
ANÁLISE DE SPREAD DAS TURMAS  (script de teste, standalone — não mexe no app)
============================================================================

Objetivo
--------
Separar as turmas (por DATA EXATA de admissão), identificá-las por letras
(A = turma mais antiga, B a seguinte, ...) e acompanhar, ano a ano, o
"spread" de cada turma: em que postos os militares da turma se encontram,
onde a turma se SEPARA e quantos PERMANECEM JUNTOS no mesmo posto.

Notação do spread (por turma, num dado ano)
-------------------------------------------
Os militares da turma são numerados por ANTIGUIDADE (A1 = o mais antigo).
Blocos contíguos de mesmo posto viram um intervalo. Ex.:

    F1-3 CAP (3) | F4-10 1º TEN (7) | F11-25 2º TEN (15)

lê-se: os 3 mais antigos da turma F são CAP, os 7 seguintes são 1º TEN, etc.

Decisões (conforme combinado — todas revisáveis)
------------------------------------------------
1. TURMA = data exata de Data_Admissao (não o ano). Letra por ordem cronológica.
2. ANTIGUIDADE A1..An — controlada pela flag SUAVIZAR:
   - SUAVIZADA (padrão, SUAVIZAR=True): a cada ano os ATIVOS da turma são
     RE-ORDENADOS por POSTO (mais alto primeiro) e, dentro do posto, por
     TEMPO DE POSTO (Ultima_promocao mais antiga primeiro = mais tempo no
     posto). Assim os blocos ficam sempre "limpos" (sem ilhas de 1 militar).
     Custo: o número deixa de ser a mesma pessoa entre anos — 'F5' passa a
     significar "o 5º colocado da turma NAQUELE ano".
   - CRUA (SUAVIZAR=False): numeração FIXA pela ordem do arquivo (fiel ao
     sort estável do motor, já que 'Pos_Hierarquica' está quase toda vazia).
     Preserva a identidade do militar entre anos, mas pode gerar ilhas.
3. Granularidade das colunas (flag GRANULARIDADE):
   - 'ciclo' (padrão): uma linha por DATA DE PROMOÇÃO (26/06 e 29/11 de cada ano).
   - 'ano': uma linha por ano (estado ao fim do ano, após o ciclo de novembro).
   Em ambos há a linha "Atual" = foto de hoje, antes de simular.
4. APOSENTADOS SAEM do spread (somem da notação a partir do ano em que inativam).
5. A lógica de simulação (promoção A -> absorção B -> aposentadoria C) replica
   fielmente 'executar_simulacao_quadro' de teste5.py, incluindo a migração de
   vagas de condutores/músicos quando o quadro é o QOA. Gerador Quântico: OFF.

Saída
-----
- Relatório no terminal (turmas grandes).
- Excel 'analise_spread_turmas.xlsx' com:
    * 'Visao_Geral'  -> matriz turma × ano com o Nº de postos distintos
                        (largura do spread) de cada turma.
    * 'Turma_<L>'    -> uma aba por turma grande: ano × [Ativos, Nº postos,
                        Maior bloco junto, Spread (notação)].
"""

from datetime import datetime
from itertools import groupby
import math

import pandas as pd
from dateutil.relativedelta import relativedelta
import matplotlib
matplotlib.use('Agg')                       # backend sem janela (salva PNG)
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch

# Reaproveita constantes e utilitários do app (fonte única da verdade).
import teste5 as t5
from teste5 import (
    HIERARQUIA, TEMPO_MINIMO, POSTOS_COM_EXCEDENTE,
    VAGAS_QOA, VAGAS_QOMT, VAGAS_QOM, get_anos,
)

# ==========================================================================
# CONFIGURAÇÃO DO TESTE
# ==========================================================================
QUADRO_ARQ   = 'militares.xlsx'          # 'militares.xlsx' | 'condutores.xlsx' | 'musicos.xlsx'
ANOS_FOCO    = [2018, 2023]              # anos de ingresso a analisar (agrupa por ANO; A=mais antigo).
                                         # [] = analisa TODAS as turmas por data exata de admissão.
DATA_ALVO    = pd.Timestamp('2058-12-31')  # até quando projetar
GRANULARIDADE = 'ciclo'                  # 'ciclo' = cada data de promoção (26/06 e 29/11)
                                         # 'ano'   = colapsa no fim de cada ano
TEMPO_APO    = 35                        # aposentadoria por tempo de serviço (anos)
IDADE_APO    = 63                        # aposentadoria por idade (anos)
MIN_DETALHE  = 10                        # (modo TODAS) detalha turmas com >= este efetivo
SUAVIZAR     = True                      # True = reordena por posto->tempo de posto (sem ilhas);
                                         # False = numeração crua pela ordem do arquivo
SAIDA_XLSX   = 'analise_spread_turmas.xlsx'
SAIDA_PNG    = 'spread_turmas.png'       # gráfico de área empilhada (composição por posto)

NIVEL = {p: i for i, p in enumerate(HIERARQUIA)}   # posto -> nível (0 = base)


# ==========================================================================
# TURMAS E ANTIGUIDADE
# ==========================================================================
def letra(idx: int) -> str:
    """0->A, 1->B, ... 25->Z, 26->AA (caso raro de >26 turmas)."""
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def montar_turmas(df_inicial):
    """
    Modo TODAS: turma = Data_Admissao exata; letra por ordem cronológica (A = mais antiga).
    Antiguidade = ordem de aparição no arquivo dentro da turma (A1 = 1º a aparecer).
    Retorna (mapa_matricula, info_turmas):
        mapa[matricula] = {'letra','antig'}
        info = [{'letra','rotulo','n'}] ordenada por data.
    """
    datas_ordenadas = sorted(df_inicial['Data_Admissao'].dropna().unique())
    letra_por_data = {d: letra(i) for i, d in enumerate(datas_ordenadas)}

    mapa = {}
    contador = {d: 0 for d in datas_ordenadas}
    for r in df_inicial.itertuples():          # ordem do arquivo = ordem das linhas
        d = r.Data_Admissao
        if pd.isna(d):
            continue
        contador[d] += 1
        mapa[r.Matricula] = {'letra': letra_por_data[d], 'antig': contador[d]}

    info = [{'letra': letra_por_data[d], 'rotulo': str(pd.Timestamp(d).date()), 'n': contador[d]}
            for d in datas_ordenadas]
    return mapa, info


def montar_turmas_foco(df_inicial, anos_foco):
    """
    Modo FOCO: turma = ANO de ingresso (agrupa datas do mesmo ano); só os anos em anos_foco.
    Letra por ordem cronológica dos anos (A = ano mais antigo). Antiguidade = ordem do arquivo.
    Retorna (mapa, info) no mesmo esquema de montar_turmas; info inclui 'ano' e 'composicao'
    (lista [(data, n)]) para o relatório mostrar o que foi agrupado.
    """
    anos = sorted(a for a in anos_foco)
    letra_por_ano = {ano: letra(i) for i, ano in enumerate(anos)}

    mapa = {}
    contador = {ano: 0 for ano in anos}
    composicao = {ano: {} for ano in anos}
    for r in df_inicial.itertuples():          # ordem do arquivo
        d = r.Data_Admissao
        if pd.isna(d):
            continue
        ano = pd.Timestamp(d).year
        if ano not in letra_por_ano:
            continue
        contador[ano] += 1
        comp = composicao[ano]
        comp[pd.Timestamp(d).date()] = comp.get(pd.Timestamp(d).date(), 0) + 1
        mapa[r.Matricula] = {'letra': letra_por_ano[ano], 'antig': contador[ano]}

    info = [{'letra': letra_por_ano[ano], 'rotulo': str(ano), 'ano': ano, 'n': contador[ano],
             'composicao': sorted(composicao[ano].items())} for ano in anos]
    return mapa, info


# ==========================================================================
# SIMULAÇÃO FIEL COM SNAPSHOTS POR CICLO
# ==========================================================================
def simular_com_snapshots(df_input, vagas_base, data_alvo, tempo_apo, idade_apo,
                          vagas_extras_dict=None):
    """
    Replica executar_simulacao_quadro (sem quântico/históricos) e, ao fim de cada
    ciclo, guarda uma FOTO {matricula: posto} dos ATIVOS.
    Retorna (snapshots, datas_ciclo) com snapshots[data] = {matricula: posto}.
    """
    df = df_input.copy()
    data_atual = pd.to_datetime(datetime.now().strftime('%d/%m/%Y'), dayfirst=True)

    datas_ciclo = []
    for ano in range(data_atual.year, data_alvo.year + 1):
        for mes, dia in [(6, 26), (11, 29)]:
            d = pd.Timestamp(year=ano, month=mes, day=dia)
            if data_atual <= d <= data_alvo:
                datas_ciclo.append(d)
    datas_ciclo.sort()

    snapshots = {}
    for data_ref in datas_ciclo:
        extras = (vagas_extras_dict or {}).get(data_ref, {})

        # --- A) PROMOÇÕES ---
        for i in range(len(HIERARQUIA) - 1):
            posto_atual, proximo = HIERARQUIA[i], HIERARQUIA[i + 1]
            candidatos = df[df['Posto_Graduacao'] == posto_atual].sort_values('Pos_Hierarquica')
            limite = vagas_base.get(proximo, 9999) + extras.get(proximo, 0)
            ocupados = len(df[(df['Posto_Graduacao'] == proximo) & (df['Excedente'] != "x")])
            vagas = max(0, limite - ocupados)
            for idx, mil in candidatos.iterrows():
                anos_posto = relativedelta(data_ref, mil['Ultima_promocao']).years
                if anos_posto >= TEMPO_MINIMO.get(posto_atual, 99) and vagas > 0:
                    df.at[idx, 'Posto_Graduacao'] = proximo
                    df.at[idx, 'Ultima_promocao'] = data_ref
                    df.at[idx, 'Excedente'] = ""
                    vagas -= 1
                elif posto_atual in POSTOS_COM_EXCEDENTE and anos_posto >= 6:
                    df.at[idx, 'Posto_Graduacao'] = proximo
                    df.at[idx, 'Ultima_promocao'] = data_ref
                    df.at[idx, 'Excedente'] = "x"

        # --- B) ABSORÇÃO ---
        for posto in HIERARQUIA:
            limite = vagas_base.get(posto, 9999) + extras.get(posto, 0)
            abertas = limite - len(df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] != "x")])
            if abertas > 0:
                exc = df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] == "x")].sort_values('Pos_Hierarquica')
                for idx_exc in exc.head(int(abertas)).index:
                    df.at[idx_exc, 'Excedente'] = ""

        # --- C) APOSENTADORIA ---
        idade = pd.to_numeric(df['Data_Nascimento'].apply(lambda x: get_anos(data_ref, x)))
        servico = pd.to_numeric(df['Data_Admissao'].apply(lambda x: get_anos(data_ref, x)))
        mask_apo = (idade >= idade_apo) | (servico >= tempo_apo)
        if mask_apo.any():
            df = df[~mask_apo].copy()

        # --- FOTO dos ativos ao fim do ciclo: matricula -> (posto, ultima_promocao) ---
        snapshots[data_ref] = {m: (p, up) for m, p, up in
                               zip(df['Matricula'], df['Posto_Graduacao'], df['Ultima_promocao'])}

    return snapshots, datas_ciclo


def vagas_migradas_qoa(df_condutores, df_musicos, data_alvo, tempo_apo, idade_apo):
    """Reproduz a migração de sobras (condutores + músicos) para o QOA (como no app)."""
    migradas = {}
    if df_condutores is not None:
        _, _, _, s_cond, _, _ = t5.executar_simulacao_quadro(
            df_condutores, VAGAS_QOMT, data_alvo, tempo_apo, idade_apo, [])
        for d, v in s_cond.items():
            migradas[d] = dict(v)
    if df_musicos is not None:
        _, _, _, s_mus, _, _ = t5.executar_simulacao_quadro(
            df_musicos, VAGAS_QOM, data_alvo, tempo_apo, idade_apo, [])
        base_praca = ['SD 1', 'CB', '3º SGT', '2º SGT', '1º SGT', 'SUB TEN']
        for d, v in s_mus.items():
            migradas.setdefault(d, {})
            for p, q in v.items():
                mq = q if p in base_praca else math.ceil(q / 2)
                migradas[d][p] = migradas[d].get(p, 0) + mq
    return migradas


# ==========================================================================
# SPREAD (NOTAÇÃO + MÉTRICAS)
# ==========================================================================
def ordenar_e_numerar(membros):
    """
    membros: lista [(antig, posto, ultima_promocao), ...] dos ATIVOS da turma no ano.
    Devolve [(numero, posto), ...] na ordem de exibição (numero crescente):
      - SUAVIZAR: reordena por POSTO (mais alto 1º) e, no mesmo posto, por TEMPO
        DE POSTO (Ultima_promocao mais antiga 1º); renumera 1..k. Assim cada posto
        vira um bloco contíguo, sem ilhas. 'antig' é só desempate determinístico.
      - senão: mantém a numeração crua da ordem do arquivo (o 'antig' fixo).
    """
    if SUAVIZAR:
        def chave(m):
            antig, posto, up = m
            up_ord = up if pd.notna(up) else pd.Timestamp.max   # sem promoção -> mais moderno
            return (-NIVEL[posto], up_ord, antig)               # posto desc, tempo de posto, desempate
        ordenados = sorted(membros, key=chave)
        return [(k + 1, posto) for k, (_, posto, _) in enumerate(ordenados)]
    ordenados = sorted(membros, key=lambda m: m[0])             # por antig (ordem do arquivo)
    return [(antig, posto) for antig, posto, _ in ordenados]


def agrupar_spread(letra_turma, numerados):
    """
    numerados: [(numero, posto), ...] em ordem de exibição.
    Agrupa blocos contíguos de mesmo posto -> notação + métricas do spread.
    """
    if not numerados:
        return {'spread': '— (todos inativos)', 'n_postos': 0, 'maior_junto': 0, 'ativos': 0}
    segmentos, postos_distintos, maior_junto = [], set(), 0
    for posto, grupo in groupby(numerados, key=lambda x: x[1]):
        nums = [n for n, _ in grupo]
        i, j, n = nums[0], nums[-1], len(nums)
        rotulo = f"{letra_turma}{i}" if i == j else f"{letra_turma}{i}-{j}"
        segmentos.append(f"{rotulo} {posto} ({n})")
        postos_distintos.add(posto)
        maior_junto = max(maior_junto, n)
    return {
        'spread': ' | '.join(segmentos),
        'n_postos': len(postos_distintos),
        'maior_junto': maior_junto,
        'ativos': len(numerados),
    }


def construir_analise(df_inicial, mapa_matricula, snapshots):
    """
    Constrói, por turma e por ANO, a foto do spread.
    Foto inicial ("Atual") = estado do arquivo antes de simular.
    Cada ano seguinte = último ciclo (novembro) daquele ano.
    Retorna (labels, dados) com dados[letra][ano] = resultado de agrupar_spread(...).
    """
    # Foto inicial (antes de qualquer ciclo): matricula -> (posto, ultima_promocao).
    snap_inicial = {m: (p, up) for m, p, up in
                    zip(df_inicial['Matricula'], df_inicial['Posto_Graduacao'], df_inicial['Ultima_promocao'])}

    colunas = [('Atual', snap_inicial)]
    if GRANULARIDADE == 'ano':
        # Um ponto por ano: o ciclo mais tardio (novembro) de cada ano.
        ultimo_ciclo_do_ano = {}
        for d in sorted(snapshots.keys()):
            ultimo_ciclo_do_ano[d.year] = d
        for ano in sorted(ultimo_ciclo_do_ano):
            colunas.append((str(ano), snapshots[ultimo_ciclo_do_ano[ano]]))
    else:
        # Um ponto por DATA DE PROMOÇÃO (cada ciclo 26/06 e 29/11).
        for d in sorted(snapshots.keys()):
            colunas.append((d.strftime('%d/%m/%Y'), snapshots[d]))

    # Matrículas por turma (com o antig da ordem do arquivo p/ desempate/numeração crua).
    por_turma = {}
    for mat, info in mapa_matricula.items():
        por_turma.setdefault(info['letra'], []).append((info['antig'], mat))

    dados, contagens = {}, {}
    for letra_turma, lista in por_turma.items():
        dados[letra_turma], contagens[letra_turma] = {}, {}
        for label, snap in colunas:
            # ativos da turma neste ciclo, com (antig, posto, ultima_promocao)
            membros = [(antig, snap[mat][0], snap[mat][1]) for antig, mat in lista if mat in snap]
            numerados = ordenar_e_numerar(membros)
            dados[letra_turma][label] = agrupar_spread(letra_turma, numerados)
            cont = {}
            for _, posto, _ in membros:
                cont[posto] = cont.get(posto, 0) + 1
            contagens[letra_turma][label] = cont      # posto -> nº de ativos

    labels = [c[0] for c in colunas]
    return labels, dados, contagens


# ==========================================================================
# GRÁFICO — "seguir o spread"
# ==========================================================================
def _label_para_data(lab):
    """Converte um rótulo de coluna (Atual / 'dd/mm/aaaa' / 'aaaa') em Timestamp (eixo x)."""
    if lab == 'Atual':
        return pd.Timestamp.today().normalize()
    try:
        return pd.to_datetime(lab, format='%d/%m/%Y')
    except ValueError:
        return pd.Timestamp(year=int(lab), month=12, day=31)


def plotar_spread(info_turmas, labels, contagens, arquivo_png):
    """
    Área empilhada por turma (um subplot cada): x = data de promoção, y = militares
    ativos, faixas = postos. Como posto é uma escala ORDINAL, a cor é uma rampa
    SEQUENCIAL de um matiz (posto baixo = claro -> posto alto = escuro), com
    separadores brancos entre faixas e legenda compartilhada. A espessura da região
    multicolor num dado x = o "spread" (quantos postos a turma ocupa naquele momento).
    """
    datas = [_label_para_data(l) for l in labels]

    # Postos que aparecem (união das turmas), ordenados por nível (baixo -> alto).
    usados = set()
    for t in info_turmas:
        for lab in labels:
            usados.update(contagens[t['letra']][lab])
    postos_ord = [p for p in HIERARQUIA if p in usados]
    if not postos_ord:
        return None

    # Rampa sequencial de um matiz, amostrada numa faixa visível (0.40..0.95) do 'Blues'
    # (piso 0.40 p/ o posto mais baixo já ser um azul nítido contra o fundo branco).
    cmap = plt.get_cmap('Blues')
    k = len(postos_ord)
    cor = {p: cmap(0.40 + 0.55 * (i / (k - 1) if k > 1 else 0.5))
           for i, p in enumerate(postos_ord)}

    n = len(info_turmas)
    fig, axes = plt.subplots(n, 1, figsize=(13, 3.9 * n), sharex=True)
    if n == 1:
        axes = [axes]
    for ax, t in zip(axes, info_turmas):
        L = t['letra']
        series = [[contagens[L][lab].get(p, 0) for lab in labels] for p in postos_ord]
        polys = ax.stackplot(datas, series, colors=[cor[p] for p in postos_ord])
        for poly in polys:                       # spacer branco (~2px) entre faixas
            poly.set_edgecolor('white')
            poly.set_linewidth(1.4)
        ax.set_title(f"Turma {L} ({t['rotulo']}) — {t['n']} militares",
                     fontsize=12, weight='bold', color='#333333')
        ax.set_ylabel("Militares ativos", color='#555555')
        ax.margins(x=0)
        ax.grid(axis='x', linestyle=':', alpha=0.35)
        ax.tick_params(colors='#555555')
        for lado in ('top', 'right'):
            ax.spines[lado].set_visible(False)

    axes[-1].xaxis.set_major_locator(mdates.YearLocator(2))
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    axes[-1].set_xlabel("Data de promoção", color='#555555')

    # Legenda compartilhada, do posto mais alto (topo da pilha) ao mais baixo.
    handles = [Patch(facecolor=cor[p], edgecolor='white', label=p) for p in reversed(postos_ord)]
    fig.legend(handles=handles, title="Posto", loc='center left',
               bbox_to_anchor=(0.995, 0.5), frameon=False, fontsize=9)
    fig.suptitle("Spread das turmas ao longo do tempo — composição por posto",
                 fontsize=13, weight='bold', color='#222222')
    fig.savefig(arquivo_png, dpi=130, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return arquivo_png


# ==========================================================================
# EXECUÇÃO
# ==========================================================================
def main():
    print("=" * 78)
    print(f"ANÁLISE DE SPREAD — quadro: {QUADRO_ARQ}  |  até {DATA_ALVO.date()}"
          f"  |  aposentadoria: {TEMPO_APO} anos sv / {IDADE_APO} idade")
    print(f"Numeração: {'SUAVIZADA (posto -> tempo de posto, sem ilhas)' if SUAVIZAR else 'CRUA (ordem do arquivo)'}")
    print(f"Granularidade: {'CICLO (cada data de promoção 26/06 e 29/11)' if GRANULARIDADE == 'ciclo' else 'ANUAL'}")
    print("=" * 78)

    rotulo_tempo = 'Ciclo' if GRANULARIDADE == 'ciclo' else 'Ano'

    df_ativo = t5.carregar_dados(QUADRO_ARQ)
    if df_ativo is None:
        print(f"ERRO: não encontrei {QUADRO_ARQ}")
        return

    if ANOS_FOCO:
        mapa_matricula, info_turmas = montar_turmas_foco(df_ativo, ANOS_FOCO)
        print(f"\nMODO FOCO — anos de ingresso: {ANOS_FOCO} (turma = ANO; A = mais antigo)")
        for t in info_turmas:
            comp = ", ".join(f"{d} ({n})" for d, n in t['composicao'])
            print(f"  {t['letra']}  ano {t['rotulo']}  n={t['n']:>3}   [datas agrupadas: {comp}]")
    else:
        mapa_matricula, info_turmas = montar_turmas(df_ativo)
        print("\nTURMAS IDENTIFICADAS (letra · data de admissão · efetivo inicial):")
        for t in info_turmas:
            marca = "  <-- detalhada" if t['n'] >= MIN_DETALHE else ""
            print(f"  {t['letra']:>2}  {t['rotulo']}  n={t['n']:>3}{marca}")

    # Migração de vagas (só faz sentido para o QOA).
    vagas_base = {'militares.xlsx': VAGAS_QOA,
                  'condutores.xlsx': VAGAS_QOMT,
                  'musicos.xlsx': VAGAS_QOM}[QUADRO_ARQ]
    vagas_extras = None
    if QUADRO_ARQ == 'militares.xlsx':
        df_cond = t5.carregar_dados('condutores.xlsx')
        df_mus = t5.carregar_dados('musicos.xlsx')
        vagas_extras = vagas_migradas_qoa(df_cond, df_mus, DATA_ALVO, TEMPO_APO, IDADE_APO)

    print("\nProcessando simulação (fiel a teste5.py)...")
    snapshots, _ = simular_com_snapshots(
        df_ativo, vagas_base, DATA_ALVO, TEMPO_APO, IDADE_APO, vagas_extras)

    labels, dados, contagens = construir_analise(df_ativo, mapa_matricula, snapshots)

    # ---------- RELATÓRIO NO TERMINAL ----------
    grandes = info_turmas if ANOS_FOCO else [t for t in info_turmas if t['n'] >= MIN_DETALHE]
    for t in grandes:
        L = t['letra']
        print("\n" + "-" * 78)
        print(f"TURMA {L}  ·  {'ano ' if ANOS_FOCO else 'admissão '}{t['rotulo']}  ·  {t['n']} militares")
        print("-" * 78)
        linhas = []
        for lab in labels:
            r = dados[L][lab]
            linhas.append({rotulo_tempo: lab, 'Ativos': r['ativos'],
                           'Postos': r['n_postos'], 'Junto': r['maior_junto'],
                           'Spread': r['spread']})
        df_print = pd.DataFrame(linhas)
        with pd.option_context('display.max_colwidth', 120, 'display.width', 200):
            print(df_print.to_string(index=False))

    # ---------- EXPORTAÇÃO EXCEL ----------
    with pd.ExcelWriter(SAIDA_XLSX, engine='xlsxwriter') as writer:
        if ANOS_FOCO:
            # Comparativo lado a lado: ano × (ativos, nº postos, maior bloco) de cada turma.
            comp_rows = []
            for lab in labels:
                row = {rotulo_tempo: lab}
                for t in info_turmas:
                    L = t['letra']; r = dados[L][lab]
                    row[f"{L} ({t['rotulo']}) ativos"] = r['ativos']
                    row[f"{L} nº postos"] = r['n_postos']
                    row[f"{L} maior junto"] = r['maior_junto']
                comp_rows.append(row)
            pd.DataFrame(comp_rows).to_excel(writer, sheet_name='Comparativo', index=False)
        else:
            # Visão geral: turma × ano -> nº de postos distintos (largura do spread).
            idx = [f"{t['letra']} · {t['rotulo']} · n={t['n']}" for t in info_turmas]
            matriz = []
            for t in info_turmas:
                linha = {lab: (dados[t['letra']][lab]['n_postos']
                               if dados[t['letra']][lab]['ativos'] > 0 else None) for lab in labels}
                matriz.append(linha)
            pd.DataFrame(matriz, index=idx).to_excel(writer, sheet_name='Visao_Geral')

        # Uma aba por turma detalhada (ano × métricas + notação do spread).
        for t in grandes:
            L = t['letra']
            linhas = [{rotulo_tempo: lab, 'Ativos': dados[L][lab]['ativos'],
                       'Nº postos': dados[L][lab]['n_postos'],
                       'Maior bloco junto': dados[L][lab]['maior_junto'],
                       'Spread': dados[L][lab]['spread']} for lab in labels]
            nome = f"Turma_{L}_{t['rotulo']}"[:31]
            pd.DataFrame(linhas).to_excel(writer, sheet_name=nome, index=False)

    # ---------- GRÁFICO ----------
    plotar_spread(info_turmas, labels, contagens, SAIDA_PNG)

    print("\n" + "=" * 78)
    print(f"Excel salvo em: {SAIDA_XLSX}")
    print(f"Gráfico salvo em: {SAIDA_PNG}")
    print("=" * 78)


if __name__ == '__main__':
    main()
