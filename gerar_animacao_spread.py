# -*- coding: utf-8 -*-
"""
Gera/atualiza os dados embutidos em spread_animacao.html (protótipo standalone).

Simula o QOA fiel a teste5.py (mesma lógica de analise_spread.py), acompanhando
as turmas reais em ANOS_FOCO (letra por ordem cronológica, A = mais antiga) e
uma turma TEÓRICA (última letra): N_C soldados ingressando como SD 1 no ciclo
ENTRADA_C, disputando as mesmas vagas legais. Ao final, substitui a linha
`const DATA = ...;` dentro do HTML.

Codificação de ranks por ciclo (uma posição por ciclo, começando em "Atual"):
  >=0 = índice em HIERARQUIA · -1 = reserva (inativo) · -2 = ainda não ingressou

Uso:  python gerar_animacao_spread.py   (a partir da raiz do repositório)
"""
import json
import re
from datetime import datetime

import pandas as pd
from dateutil.relativedelta import relativedelta

import teste5 as t5
from teste5 import HIERARQUIA, TEMPO_MINIMO, POSTOS_COM_EXCEDENTE, VAGAS_QOA, get_anos
import analise_spread as asp

NIVEL = {p: i for i, p in enumerate(HIERARQUIA)}

DATA_ALVO = pd.Timestamp('2063-12-31')   # horizonte: carreira completa da turma C
TEMPO_APO, IDADE_APO = 35, 63
ANOS_FOCO = [1994, 2002, 2006, 2010, 2018, 2023]   # turmas reais (letra por ordem cronológica)

ENTRADA_C = pd.Timestamp('2028-06-26')   # ciclo em que a turma C ingressa como SD 1
N_C = 100
NASC_C = pd.Timestamp('2003-06-26')      # ~25 anos no ingresso

ARQ_HTML = 'spread_animacao.html'


def montar_turma_c():
    df = pd.DataFrame([{
        'Matricula': 9001 + i,
        'Pos_Hierarquica': pd.NA,        # como o restante do arquivo (antiguidade = ordem)
        'Posto_Graduacao': 'SD 1',
        'Data_Admissao': ENTRADA_C,
        'Data_Nascimento': NASC_C,
        'Ultima_promocao': ENTRADA_C,
        'Excedente': '',
    } for i in range(N_C)])
    df.index = range(1_000_000, 1_000_000 + N_C)   # índices que não colidem
    return df


def simular(df_input, vagas_base, vagas_extras_dict, df_c):
    """Cópia de analise_spread.simular_com_snapshots + injeção da turma C."""
    df = df_input.copy()
    data_atual = pd.to_datetime(datetime.now().strftime('%d/%m/%Y'), dayfirst=True)

    datas_ciclo = []
    for ano in range(data_atual.year, DATA_ALVO.year + 1):
        for mes, dia in [(6, 26), (11, 29)]:
            d = pd.Timestamp(year=ano, month=mes, day=dia)
            if data_atual <= d <= DATA_ALVO:
                datas_ciclo.append(d)
    datas_ciclo.sort()

    injetado = False
    snapshots = {}
    for data_ref in datas_ciclo:
        if not injetado and data_ref >= ENTRADA_C:
            df = pd.concat([df, df_c])
            injetado = True

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
        mask_apo = (idade >= IDADE_APO) | (servico >= TEMPO_APO)
        if mask_apo.any():
            df = df[~mask_apo].copy()

        snapshots[data_ref] = dict(zip(df['Matricula'], df['Posto_Graduacao']))

    return snapshots, datas_ciclo


def main():
    df_ativo = t5.carregar_dados('militares.xlsx')
    assert df_ativo is not None, 'militares.xlsx não encontrado (rode da raiz do repo)'

    mapa, info = asp.montar_turmas_foco(df_ativo, ANOS_FOCO)
    letra_c = asp.letra(len(ANOS_FOCO))      # próxima letra após as turmas reais
    df_c = montar_turma_c()
    for i in range(N_C):
        mapa[9001 + i] = {'letra': letra_c, 'antig': i + 1}
    info.append({'letra': letra_c, 'rotulo': str(ENTRADA_C.year), 'n': N_C})

    df_cond = t5.carregar_dados('condutores.xlsx')
    df_mus = t5.carregar_dados('musicos.xlsx')
    vagas_extras = asp.vagas_migradas_qoa(df_cond, df_mus, DATA_ALVO, TEMPO_APO, IDADE_APO)

    print(f'Simulando (fiel a teste5.py, com turma {letra_c} teórica)...')
    snapshots, datas_ciclo = simular(df_ativo, VAGAS_QOA, vagas_extras, df_c)

    snap_inicial = dict(zip(df_ativo['Matricula'], df_ativo['Posto_Graduacao']))
    colunas = [('Atual', None, snap_inicial)] + \
              [(d.strftime('%d/%m/%Y'), d, snapshots[d]) for d in datas_ciclo]

    membros = []
    for mat, m in mapa.items():
        ranks = []
        for _, d, snap in colunas:
            if m['letra'] == letra_c and (d is None or d < ENTRADA_C):
                ranks.append(-2)                       # ainda não ingressou
            elif mat in snap:
                ranks.append(NIVEL[snap[mat]])
            else:
                ranks.append(-1)                       # reserva
        membros.append({'mat': int(mat), 'turma': m['letra'],
                        'antig': int(m['antig']), 'ranks': ranks})
    membros.sort(key=lambda x: (x['turma'], x['antig']))

    data = {
        'hierarquia': HIERARQUIA,
        'ciclos': [c[0] for c in colunas],
        'turmas': [{'letra': t['letra'], 'rotulo': t['rotulo'], 'n': t['n']} for t in info],
        'membros': membros,
    }

    html = open(ARQ_HTML, encoding='utf-8').read()
    js = json.dumps(data, ensure_ascii=False, separators=(', ', ': '))
    novo, n = re.subn(r'^const DATA = .*?;$', lambda _: f'const DATA = {js};',
                      html, count=1, flags=re.M)
    assert n == 1, f'linha `const DATA = ...;` não encontrada em {ARQ_HTML}'
    open(ARQ_HTML, 'w', encoding='utf-8').write(novo)
    print(f'{ARQ_HTML} atualizado: {len(data["ciclos"])} ciclos '
          f'(até {data["ciclos"][-1]}), turmas ' +
          ', '.join(f"{t['letra']}={t['n']}" for t in data['turmas']))


if __name__ == '__main__':
    main()
