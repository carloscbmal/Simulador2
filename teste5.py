import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import io
import math
import os
import seaborn as sns
import matplotlib.pyplot as plt
import numpy as np

# ==========================================
# CONFIGURAÇÕES E CONSTANTES
# ==========================================

HIERARQUIA = ['SD 1', 'CB', '3º SGT', '2º SGT', '1º SGT', 'SUB TEN', 
              '2º TEN', '1º TEN', 'CAP', 'MAJ', 'TEN CEL', 'CEL']

POSTOS_MAPA = ['1º SGT', 'SUB TEN', '2º TEN', '1º TEN', 'CAP', 'MAJ', 'TEN CEL']

TEMPO_MINIMO = {
    'SD 1': 5, 'CB': 3, '3º SGT': 3, '2º SGT': 3, '1º SGT': 2,
    'SUB TEN': 2, '2º TEN': 2, '1º TEN': 3, 'CAP': 3, 'MAJ': 2, 'TEN CEL': 30
}

POSTOS_COM_EXCEDENTE = ['CB', '3º SGT', '2º SGT', '2º TEN', '1º TEN', 'CAP']

VAGAS_QOA = {
    'SD 1': 550, 'CB': 410, '3º SGT': 397, '2º SGT': 369, '1º SGT': 356,
    'SUB TEN': 150, '2º TEN': 65, '1º TEN': 55, 'CAP': 42, 'MAJ': 20, 'TEN CEL': 5, 'CEL': 9999
}

VAGAS_QOMT = {
    'SD 1': 0, 'CB': 0, '3º SGT': 3,
    '2º SGT': 14, '1º SGT': 14, 'SUB TEN': 19, 
    '2º TEN': 14, '1º TEN': 11, 'CAP': 8, 'MAJ': 4, 'TEN CEL': 2, 'CEL': 0
}

VAGAS_QOM = {
    'SD 1': 0, 'CB': 0,
    '3º SGT': 0, '2º SGT': 6, '1º SGT': 10, 'SUB TEN': 5, 
    '2º TEN': 11, '1º TEN': 9, 'CAP': 6, 'MAJ': 4, 'TEN CEL': 2, 'CEL': 0
}

# ==========================================
# FUNÇÕES DE LÓGICA E SIMULAÇÃO
# ==========================================

def carregar_dados(nome_arquivo):
    if not os.path.exists(nome_arquivo):
        return None
    try:
        df = pd.read_excel(nome_arquivo)
        cols_numericas = ['Matricula', 'Pos_Hierarquica']
        for col in cols_numericas:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        cols_datas = ['Ultima_promocao', 'Data_Admissao', 'Data_Nascimento']
        for col in cols_datas:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], dayfirst=True)
        if 'Excedente' not in df.columns:
            df['Excedente'] = ""
        df['Excedente'] = df['Excedente'].fillna("")
        return df
    except Exception as e:
        st.error(f"Erro ao ler {nome_arquivo}: {e}")
        return None

def get_anos(data_ref, data_origem):
    if pd.isna(data_origem): return 0
    return relativedelta(data_ref, data_origem).years

def executar_simulacao_quadro(df_input, vagas_limite_base, data_alvo, tempo_aposentadoria, 
                              idade_aposentadoria, matriculas_foco, vagas_extras_dict=None, 
                              usar_quantico=False, perc_quantico=0):
    df = df_input.copy()
    data_atual = pd.to_datetime(datetime.now().strftime('%d/%m/%Y'), dayfirst=True)
    
    datas_ciclo = []
    for ano in range(data_atual.year, data_alvo.year + 1):
        for mes, dia in [(6, 26), (11, 29)]:
            d = pd.Timestamp(year=ano, month=mes, day=dia)
            if data_atual <= d <= data_alvo:
                datas_ciclo.append(d)
    datas_ciclo.sort()

    historicos = {m: [] for m in matriculas_foco} if matriculas_foco else {}
    df_inativos = pd.DataFrame()
    sobras_por_ciclo = {}
    
    log_geral_mapas = {}
    tempos_promocao_log = {p: [] for p in HIERARQUIA} # NOVO: Rastreio de gargalos
    
    turmas_processadas_quantico = set()

    for data_referencia in datas_ciclo:
        extras_hoje = (vagas_extras_dict or {}).get(data_referencia, {})

        # --- LOG INICIAL: Vagas Abertas ---
        vagas_iniciais_log = {}
        for posto in HIERARQUIA:
            limite = vagas_limite_base.get(posto, 9999) + extras_hoje.get(posto, 0)
            ocupados = len(df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] != "x")])
            vagas_iniciais_log[posto] = max(0, limite - ocupados)

        # --- GERADOR QUÂNTICO ---
        if usar_quantico:
            turmas = df['Data_Admissao'].dropna().unique()
            militares_para_remover_indices = []
            
            for turma_data in turmas:
                anos_servico = relativedelta(data_referencia, turma_data).years
                if anos_servico in [tempo_aposentadoria - 3, tempo_aposentadoria - 2, tempo_aposentadoria - 1]:
                    chave_controle = (turma_data, anos_servico)
                    if chave_controle not in turmas_processadas_quantico:
                        mask_turma = (df['Data_Admissao'] == turma_data)
                        df_turma = df[mask_turma].copy()
                        
                        if matriculas_foco:
                            df_turma = df_turma[~df_turma['Matricula'].isin(matriculas_foco)]

                        # A turma já está restrita à faixa de serviço (32/33/34 anos) pelo 'if' acima.
                        # O corte do Gerador Quântico é estatístico sobre a turma; a idade não entra
                        # como critério adicional aqui (o filtro anterior por idade era inócuo, pois
                        # 'anos_servico >= tempo-3' já é sempre verdadeiro nesta faixa).
                        if not df_turma.empty:
                            qtd_remover = math.ceil(len(df_turma) * (perc_quantico / 100.0))
                            if qtd_remover > 0:
                                removidos = df_turma.sample(n=min(qtd_remover, len(df_turma)))
                                militares_para_remover_indices.extend(removidos.index.tolist())
                                turmas_processadas_quantico.add(chave_controle)

            if militares_para_remover_indices:
                militares_para_remover_indices = list(set(militares_para_remover_indices))
                df_removidos = df.loc[militares_para_remover_indices].copy()
                for idx, row in df_removidos.iterrows():
                    m_id = row['Matricula']
                    asv = relativedelta(data_referencia, row['Data_Admissao']).years
                    if m_id in historicos:
                        historicos[m_id].append(f"⚛️ {data_referencia.strftime('%d/%m/%Y')}: Aposentado pelo Gerador Quântico ({asv} anos sv)")
                
                df_inativos = pd.concat([df_inativos, df_removidos], ignore_index=True)
                df = df.drop(index=militares_para_remover_indices).copy()

        sobras_deste_ciclo = {}
        promocoes_ciclo_log = {p: 0 for p in HIERARQUIA}
        
        # --- A) PROMOÇÕES ---
        for i in range(len(HIERARQUIA) - 1):
            posto_atual = HIERARQUIA[i]
            proximo_posto = HIERARQUIA[i+1]
            candidatos = df[df['Posto_Graduacao'] == posto_atual].sort_values('Pos_Hierarquica')
            limite_atual = vagas_limite_base.get(proximo_posto, 9999) + extras_hoje.get(proximo_posto, 0)
            ocupados_reais = len(df[(df['Posto_Graduacao'] == proximo_posto) & (df['Excedente'] != "x")])
            vagas_disponiveis = max(0, limite_atual - ocupados_reais)
            
            for idx, militar in candidatos.iterrows():
                anos_no_posto = relativedelta(data_referencia, militar['Ultima_promocao']).years
                promoveu = False
                # Vaga real tem prioridade: como os candidatos são percorridos por
                # antiguidade (Pos_Hierarquica), o mais antigo apto ocupa a vaga aberta.
                # Só depois de esgotadas as vagas reais os ≥6 anos restantes viram excedente.
                if anos_no_posto >= TEMPO_MINIMO.get(posto_atual, 99) and vagas_disponiveis > 0:
                    df.at[idx, 'Posto_Graduacao'] = proximo_posto
                    df.at[idx, 'Ultima_promocao'] = data_referencia
                    df.at[idx, 'Excedente'] = ""
                    vagas_disponiveis -= 1
                    promoveu = True
                elif posto_atual in POSTOS_COM_EXCEDENTE and anos_no_posto >= 6:
                    df.at[idx, 'Posto_Graduacao'] = proximo_posto
                    df.at[idx, 'Ultima_promocao'] = data_referencia
                    df.at[idx, 'Excedente'] = "x"
                    promoveu = True
                
                if promoveu:
                    promocoes_ciclo_log[proximo_posto] += 1
                    tempos_promocao_log[proximo_posto].append(anos_no_posto) # Registra o gargalo
                    if militar['Matricula'] in historicos:
                        historicos[militar['Matricula']].append(f"✅ {data_referencia.strftime('%d/%m/%Y')}: Promovido a {proximo_posto}")

            sobras_deste_ciclo[proximo_posto] = int(vagas_disponiveis)
        sobras_por_ciclo[data_referencia] = sobras_deste_ciclo

        # --- B) ABSORÇÃO ---
        for posto in HIERARQUIA:
            limite_atual = vagas_limite_base.get(posto, 9999) + extras_hoje.get(posto, 0)
            vagas_abertas = limite_atual - len(df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] != "x")])
            if vagas_abertas > 0:
                excedentes = df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] == "x")].sort_values('Pos_Hierarquica')
                for idx_exc in excedentes.head(int(vagas_abertas)).index:
                    df.at[idx_exc, 'Excedente'] = ""
                    m_id = df.at[idx_exc, 'Matricula']
                    if m_id in historicos:
                        historicos[m_id].append(f"ℹ️ {data_referencia.strftime('%d/%m/%Y')}: Ocupou vaga comum em {posto}")

        # --- LOG FINAL: Excedentes ---
        excedentes_finais_log = {}
        for posto in HIERARQUIA:
            exc_count = len(df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] == "x")])
            excedentes_finais_log[posto] = exc_count

        log_geral_mapas[data_referencia] = {
            'vagas_iniciais': vagas_iniciais_log,
            'promocoes': promocoes_ciclo_log,
            'excedentes': excedentes_finais_log
        }

        # --- C) APOSENTADORIA DINÂMICA ---
        idade = pd.to_numeric(df['Data_Nascimento'].apply(lambda x: get_anos(data_referencia, x)))
        servico = pd.to_numeric(df['Data_Admissao'].apply(lambda x: get_anos(data_referencia, x)))
        mask_apo = (idade >= idade_aposentadoria) | (servico >= tempo_aposentadoria)
        
        if mask_apo.any():
            militares_aposentando = df[mask_apo]
            for m_foco in historicos:
                if m_foco in militares_aposentando['Matricula'].values:
                    historicos[m_foco].append(f"🛑 {data_referencia.strftime('%d/%m/%Y')}: APOSENTADO (Tempo/Idade)")
            df_inativos = pd.concat([df_inativos, militares_aposentando.copy()], ignore_index=True)
            df = df[~mask_apo].copy()

        # --- LOG: Distribuição por turma (ano de admissão) × posto, após o ciclo ---
        # Alimenta a aba "Análise por Turma" (trajetória ao longo dos ciclos).
        turmas_dist = {}
        if not df.empty:
            anos_adm = df['Data_Admissao'].dt.year
            for (ano, posto), qtd in df.groupby([anos_adm, 'Posto_Graduacao']).size().items():
                if pd.notna(ano):
                    turmas_dist.setdefault(int(ano), {})[posto] = int(qtd)
        log_geral_mapas[data_referencia]['turmas_dist'] = turmas_dist

    return df, df_inativos, historicos, sobras_por_ciclo, log_geral_mapas, tempos_promocao_log

# Wrapper para rodar os cenários de forma limpa
def rodar_cenario(tipo_simulacao, df_ativo, df_condutores, df_musicos, data_alvo, tempo_apo, idade_apo, matriculas_foco, usar_quantico, perc_quantico):
    if tipo_simulacao == "QOA/QPC (Administrativo)":
        vagas_migradas = {}
        if df_condutores is not None:
            _, _, _, s_cond, _, _ = executar_simulacao_quadro(df_condutores, VAGAS_QOMT, data_alvo, tempo_apo, idade_apo, [], usar_quantico=usar_quantico, perc_quantico=perc_quantico)
            for d, v in s_cond.items(): vagas_migradas[d] = v
        if df_musicos is not None:
            _, _, _, s_mus, _, _ = executar_simulacao_quadro(df_musicos, VAGAS_QOM, data_alvo, tempo_apo, idade_apo, [], usar_quantico=usar_quantico, perc_quantico=perc_quantico)
            for d, v in s_mus.items():
                if d not in vagas_migradas: vagas_migradas[d] = {}
                for p, q in v.items():
                    mq = q if p in ['SD 1', 'CB', '3º SGT', '2º SGT', '1º SGT', 'SUB TEN'] else math.ceil(q/2)
                    vagas_migradas[d][p] = vagas_migradas[d].get(p, 0) + mq
        return executar_simulacao_quadro(df_ativo, VAGAS_QOA, data_alvo, tempo_apo, idade_apo, matriculas_foco, vagas_migradas, usar_quantico=usar_quantico, perc_quantico=perc_quantico)
    else:
        vagas_base = VAGAS_QOMT if "Condutores" in tipo_simulacao else VAGAS_QOM
        return executar_simulacao_quadro(df_ativo, vagas_base, data_alvo, tempo_apo, idade_apo, matriculas_foco, usar_quantico=usar_quantico, perc_quantico=perc_quantico)


# ==========================================
# FUNÇÕES DE PLOTAGEM (VISUALIZAÇÃO)
# ==========================================
def plotar_heatmap_log(log_dict, chave_log, titulo, cmap_color, label_barra):
    dados = []
    for d_ref, info in log_dict.items():
        nome_data = d_ref.strftime('%d/%m/%y')
        for p, q in info[chave_log].items():
            if p in POSTOS_MAPA:
                dados.append({'Data': nome_data, 'Posto/Graduação': p, 'Valor': q})
    
    df_h = pd.DataFrame(dados)
    if df_h.empty:
        st.warning("Nenhum dado encontrado.")
        return
    
    df_pivot = df_h.pivot_table(index='Posto/Graduação', columns='Data', values='Valor', sort=False)
    df_pivot = df_pivot.reindex(reversed(POSTOS_MAPA))
    datas_ordenadas = [d.strftime('%d/%m/%y') for d in sorted(log_dict.keys()) if d.strftime('%d/%m/%y') in df_pivot.columns]
    df_pivot = df_pivot[datas_ordenadas]

    fig, ax = plt.subplots(figsize=(max(8, len(datas_ordenadas) * 0.4), 5))
    sns.heatmap(df_pivot, annot=True, fmt='.0f', cmap=cmap_color, linewidths=0.5, linecolor='white', cbar_kws={'label': label_barra}, ax=ax, annot_kws={"size": 9, "weight": "bold"})
    ax.set_title(titulo, pad=15)
    ax.set_xlabel("")
    ax.set_ylabel("")
    plt.xticks(rotation=45, ha='right')
    st.pyplot(fig)

def plotar_gargalos(tempos_log):
    medias = {}
    for p in POSTOS_MAPA:
        if p in tempos_log and len(tempos_log[p]) > 0:
            medias[p] = np.mean(tempos_log[p])
    
    if not medias:
        st.info("Não houve promoções suficientes para calcular o gargalo.")
        return
        
    df_g = pd.DataFrame(list(medias.items()), columns=['Posto', 'Anos no Posto Anterior'])
    df_g['Posto'] = pd.Categorical(df_g['Posto'], categories=POSTOS_MAPA, ordered=True)
    df_g = df_g.sort_values('Posto')
    
    fig, ax = plt.subplots(figsize=(10, 4))
    sns.barplot(data=df_g, x='Posto', y='Anos no Posto Anterior', palette="magma", ax=ax)
    ax.set_title("Gargalos: Tempo Médio de Espera para Promoção")
    ax.set_ylabel("Anos")
    for container in ax.containers: ax.bar_label(container, fmt='%.1f')
    sns.despine()
    st.pyplot(fig)

def plotar_piramide(df_final, data_alvo):
    if df_final.empty: return
    anos_servico = df_final['Data_Admissao'].apply(lambda x: get_anos(data_alvo, x)).dropna()
    fig, ax = plt.subplots(figsize=(10, 4))
    sns.histplot(anos_servico, bins=range(0, 45, 2), kde=True, color='teal', ax=ax)
    ax.set_title(f"Distribuição de Tempo de Serviço no Ano {data_alvo.year}")
    ax.set_xlabel("Anos de Serviço")
    ax.set_ylabel("Quantidade de Militares")
    sns.despine()
    st.pyplot(fig)

def renderizar_kpis(df_final, df_inativos, log_mapas):
    ativos = len(df_final)
    inativos = len(df_inativos)
    vagas_abertas = 0
    if log_mapas:
        ultima_data = sorted(log_mapas.keys())[-1]
        vagas_abertas = sum(v for p, v in log_mapas[ultima_data]['vagas_iniciais'].items() if p in POSTOS_MAPA)
    
    c1, c2, c3 = st.columns(3)
    c1.metric("👤 Efetivo Ativo Restante", f"{ativos} militares")
    c2.metric("🛑 Inativos Gerados", f"{inativos} militares")
    c3.metric("🟦 Vagas Ociosas Finais (> 1º SGT)", f"{vagas_abertas} cadeiras")

def gerar_excel_bytes(df):
    """Serializa um DataFrame para bytes .xlsx (para usar em st.download_button)."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        (df if df is not None else pd.DataFrame()).to_excel(writer, index=False, sheet_name='Dados')
    return output.getvalue()

def botoes_download(df_final, df_inativos, sufixo=""):
    """Renderiza os botões de download dos efetivos ativo e inativo."""
    XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            f"⬇️ Efetivo Ativo ({len(df_final)}) .xlsx",
            data=gerar_excel_bytes(df_final),
            file_name=f"efetivo_ativo{('_'+sufixo) if sufixo else ''}.xlsx",
            mime=XLSX_MIME, use_container_width=True, key=f"dl_ativo_{sufixo}")
    with c2:
        n_inat = 0 if df_inativos is None else len(df_inativos)
        st.download_button(
            f"⬇️ Efetivo Inativo ({n_inat}) .xlsx",
            data=gerar_excel_bytes(df_inativos),
            file_name=f"efetivo_inativo{('_'+sufixo) if sufixo else ''}.xlsx",
            mime=XLSX_MIME, use_container_width=True, key=f"dl_inativo_{sufixo}")

# ==========================================
# ANÁLISE POR TURMA (ano de admissão)
# ==========================================
NIVEL_POSTO = {p: i for i, p in enumerate(HIERARQUIA)}

def _anos_turmas(df_inicial):
    return sorted({int(a) for a in df_inicial['Data_Admissao'].dt.year.dropna().unique()})

def _estado_final_por_matricula(df_final, df_inativos):
    """Mapeia Matricula -> (situacao, posto_final, excedente?) combinando ativos e inativos."""
    estado = {}
    for _, r in df_final.iterrows():
        exc = str(r.get('Excedente', '')).strip() == 'x'
        estado[r['Matricula']] = ('Ativo', r['Posto_Graduacao'], exc)
    if df_inativos is not None and not df_inativos.empty:
        for _, r in df_inativos.iterrows():
            estado.setdefault(r['Matricula'], ('Inativo', r['Posto_Graduacao'], False))
    return estado

def comparar_turmas(df_inicial, df_final, df_inativos):
    """Tabela + gráfico comparando todas as turmas (ano de admissão)."""
    estado = _estado_final_por_matricula(df_final, df_inativos)
    linhas = []
    for ano in _anos_turmas(df_inicial):
        ini = df_inicial[df_inicial['Data_Admissao'].dt.year == ano]
        total = len(ini)
        if total == 0:
            continue
        ativos = aposentados = promovidos = 0
        niveis_fim_ativos = []
        for _, r in ini.iterrows():
            niv_ini = NIVEL_POSTO.get(r['Posto_Graduacao'], 0)
            sit, posto_fim, _ = estado.get(r['Matricula'], ('Inativo', r['Posto_Graduacao'], False))
            niv_fim = NIVEL_POSTO.get(posto_fim, niv_ini)
            if niv_fim > niv_ini:
                promovidos += 1
            if sit == 'Ativo':
                ativos += 1
                niveis_fim_ativos.append(niv_fim)
            else:
                aposentados += 1
        posto_medio = HIERARQUIA[int(round(np.mean(niveis_fim_ativos)))] if niveis_fim_ativos else "—"
        linhas.append({
            'Turma': ano, 'Efetivo Inicial': total, 'Ativos': ativos,
            'Aposentados': aposentados, '% Promovidos': round(100 * promovidos / total, 1),
            'Posto Médio (ativos)': posto_medio,
        })
    if not linhas:
        st.info("Sem turmas para comparar.")
        return
    df_cmp = pd.DataFrame(linhas).sort_values('Turma')
    st.dataframe(df_cmp, hide_index=True, use_container_width=True)
    fig, ax = plt.subplots(figsize=(10, 3.5))
    sns.barplot(data=df_cmp, x='Turma', y='% Promovidos', palette='viridis', ax=ax)
    ax.set_title("% Promovidos por Turma (ano de admissão)")
    ax.set_ylabel("% promovidos")
    for c in ax.containers:
        ax.bar_label(c, fmt='%.0f%%')
    sns.despine()
    st.pyplot(fig)

def analisar_turma_snapshot(df_inicial, df_final, df_inativos, ano, mostrar_kpis=True):
    """KPIs e distribuição por posto de uma turma na data-alvo."""
    ini = df_inicial[df_inicial['Data_Admissao'].dt.year == ano]
    total = len(ini)
    if total == 0:
        st.info("Turma sem militares.")
        return
    estado = _estado_final_por_matricula(df_final, df_inativos)
    ativos = aposentados = promovidos = 0
    dist_posto = {p: {'comum': 0, 'excedente': 0} for p in HIERARQUIA}
    for _, r in ini.iterrows():
        niv_ini = NIVEL_POSTO.get(r['Posto_Graduacao'], 0)
        sit, posto_fim, exc = estado.get(r['Matricula'], ('Inativo', r['Posto_Graduacao'], False))
        if NIVEL_POSTO.get(posto_fim, niv_ini) > niv_ini:
            promovidos += 1
        if sit == 'Ativo':
            ativos += 1
            dist_posto[posto_fim]['excedente' if exc else 'comum'] += 1
        else:
            aposentados += 1
    if mostrar_kpis:
        c1, c2, c3 = st.columns(3)
        c1.metric("👥 Efetivo Inicial", total)
        c2.metric("✅ Ativos / 🛑 Aposentados", f"{ativos} / {aposentados}")
        c3.metric("⬆️ % Promovidos", f"{round(100 * promovidos / total, 1)}%")
    dados = [{'Posto': p, 'Comum': dist_posto[p]['comum'], 'Excedente': dist_posto[p]['excedente']}
             for p in HIERARQUIA if dist_posto[p]['comum'] or dist_posto[p]['excedente']]
    if not dados:
        st.info("Nenhum militar ativo desta turma na data-alvo (todos inativos).")
        return
    df_d = pd.DataFrame(dados)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(df_d['Posto'], df_d['Comum'], label='Vaga comum', color='teal')
    ax.bar(df_d['Posto'], df_d['Excedente'], bottom=df_d['Comum'], label='Excedente', color='salmon')
    ax.set_title(f"Turma {ano}: distribuição dos ativos por posto na data-alvo")
    ax.set_ylabel("Militares")
    plt.xticks(rotation=45, ha='right')
    ax.legend()
    sns.despine()
    st.pyplot(fig)

def plotar_trajetoria_turma(log_mapas, ano):
    """Heatmap posto × ciclo com a qtd de ativos da turma em cada posto."""
    datas = sorted(log_mapas.keys())
    dados = []
    for d in datas:
        for posto, q in log_mapas[d].get('turmas_dist', {}).get(ano, {}).items():
            dados.append({'Data': d.strftime('%d/%m/%y'), 'Posto': posto, 'Qtd': q})
    if not dados:
        st.info("Sem dados de trajetória para esta turma.")
        return
    df_t = pd.DataFrame(dados)
    pivot = df_t.pivot_table(index='Posto', columns='Data', values='Qtd', fill_value=0, sort=False)
    pivot = pivot.reindex([p for p in reversed(HIERARQUIA) if p in pivot.index])
    cols = [d.strftime('%d/%m/%y') for d in datas if d.strftime('%d/%m/%y') in pivot.columns]
    pivot = pivot[cols]
    fig, ax = plt.subplots(figsize=(max(8, len(cols) * 0.5), max(3, len(pivot) * 0.5)))
    sns.heatmap(pivot, annot=True, fmt='.0f', cmap='YlGnBu', linewidths=0.5, linecolor='white',
                cbar_kws={'label': 'Militares ativos'}, ax=ax, annot_kws={'size': 9})
    ax.set_title(f"Turma {ano}: trajetória por posto ao longo dos ciclos")
    ax.set_xlabel(""); ax.set_ylabel("")
    plt.xticks(rotation=45, ha='right')
    st.pyplot(fig)

def _tabela_turma(df_inicial, df_final, df_inativos, ano):
    """DataFrame da turma ordenado por antiguidade, com início→fim e situação."""
    estado = _estado_final_por_matricula(df_final, df_inativos)
    ini = df_inicial[df_inicial['Data_Admissao'].dt.year == ano]
    linhas = []
    for _, r in ini.iterrows():
        posto_ini = r['Posto_Graduacao']
        sit, posto_fim, exc = estado.get(r['Matricula'], ('Inativo', posto_ini, False))
        niv_ini = NIVEL_POSTO.get(posto_ini, 0)
        niv_fim = NIVEL_POSTO.get(posto_fim, niv_ini)
        linhas.append({
            'Matricula': int(r['Matricula']) if pd.notna(r['Matricula']) else None,
            'Antiguidade (Pos)': int(r['Pos_Hierarquica']) if pd.notna(r['Pos_Hierarquica']) else None,
            'Posto Inicial': posto_ini,
            'Posto Final': posto_fim,
            'Níveis Subidos': niv_fim - niv_ini,
            'Situação': ('Ativo' if sit == 'Ativo' else 'Aposentado') + (' (excedente)' if exc else ''),
            '_niv_fim': niv_fim, '_exc': bool(exc), '_sit': sit,
        })
    df_t = pd.DataFrame(linhas)
    if not df_t.empty:
        df_t = df_t.sort_values('Antiguidade (Pos)', na_position='last').reset_index(drop=True)
    return df_t

def _plot_dispersao_turma(df_t, ano):
    """Dispersão: antiguidade na turma (X) × posto alcançado (Y)."""
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(df_t.index + 1, df_t['_niv_fim'], color='lightgray', lw=1, zorder=1)
    for sit_raw, cor, lbl in [('Ativo', '#1f9e89', 'Ativo'), ('Inativo', '#9aa0a6', 'Aposentado')]:
        sub = df_t[df_t['_sit'] == sit_raw]
        if not sub.empty:
            ax.scatter(sub.index + 1, sub['_niv_fim'], c=cor, s=45, label=lbl, zorder=3)
    exc = df_t[df_t['_exc']]
    if not exc.empty:
        ax.scatter(exc.index + 1, exc['_niv_fim'], facecolors='none', edgecolors='red',
                   s=120, linewidths=1.5, label='Excedente', zorder=4)
    ax.set_yticks(range(len(HIERARQUIA)))
    ax.set_yticklabels(HIERARQUIA)
    ax.set_ylim(-0.5, df_t['_niv_fim'].max() + 0.8)
    ax.set_xlabel("Antiguidade na turma  (1 = mais antigo  →  mais moderno)")
    ax.set_title(f"Turma {ano}: posto alcançado por antiguidade (na data-alvo)")
    ax.annotate("⬅ mais antigo", (1, df_t.iloc[0]['_niv_fim']),
                textcoords="offset points", xytext=(6, 8), fontsize=9)
    ax.annotate("mais moderno ➡", (len(df_t), df_t.iloc[-1]['_niv_fim']),
                textcoords="offset points", xytext=(-70, -16), fontsize=9)
    ax.legend(loc='lower left', fontsize=8)
    ax.grid(axis='y', linestyle=':', alpha=0.4)
    sns.despine()
    st.pyplot(fig)

def quadro_geral_turma(df_inicial, df_final, df_inativos, ano):
    """Visão dedicada de uma turma: extremos (mais antigo/moderno), dispersão e tabela."""
    df_t = _tabela_turma(df_inicial, df_final, df_inativos, ano)
    if df_t.empty:
        st.info("Turma sem militares.")
        return
    total = len(df_t)
    ativos = int((df_t['_sit'] == 'Ativo').sum())
    promovidos = int((df_t['Níveis Subidos'] > 0).sum())
    mais_antigo, mais_moderno = df_t.iloc[0], df_t.iloc[-1]

    c1, c2, c3 = st.columns(3)
    c1.metric("👥 Efetivo Inicial", total)
    c2.metric("✅ Ativos / 🛑 Aposentados", f"{ativos} / {total - ativos}")
    c3.metric("⬆️ % Promovidos", f"{round(100 * promovidos / total, 1)}%")
    c4, c5 = st.columns(2)
    c4.metric("🥇 Mais antigo chegou a", mais_antigo['Posto Final'],
              help=f"Matrícula {mais_antigo['Matricula']} · Pos {mais_antigo['Antiguidade (Pos)']} · {mais_antigo['Situação']}")
    c5.metric("🆕 Mais moderno chegou a", mais_moderno['Posto Final'],
              help=f"Matrícula {mais_moderno['Matricula']} · Pos {mais_moderno['Antiguidade (Pos)']} · {mais_moderno['Situação']}")

    postos_presentes = [p for p in HIERARQUIA if p in set(df_t['Posto Final'])]
    if postos_presentes:
        st.caption(f"📐 Na data-alvo a turma vai de **{postos_presentes[-1]}** (topo) a **{postos_presentes[0]}** (base).")

    _plot_dispersao_turma(df_t, ano)

    cols = ['Matricula', 'Antiguidade (Pos)', 'Posto Inicial', 'Posto Final', 'Níveis Subidos', 'Situação']
    st.dataframe(df_t[cols], hide_index=True, use_container_width=True)
    st.download_button(
        f"⬇️ Quadro da Turma {ano} (.xlsx)", data=gerar_excel_bytes(df_t[cols]),
        file_name=f"turma_{ano}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"dl_turma_{ano}", use_container_width=True)

# ==========================================
# RENDERIZAÇÃO DOS RESULTADOS (a partir do estado salvo)
# ==========================================
def render_unico(res):
    data_alvo = res['data_alvo']
    df_final, df_inativos = res['df_final'], res['df_inativos']
    historicos, log_mapas, tempos_log = res['historicos'], res['log_mapas'], res['tempos_log']
    matriculas_foco, df_inicial = res['matriculas_foco'], res['df_inicial']

    st.success("Simulação Estratégica Concluída!")
    st.markdown("### 📊 Panorama Geral ao Final da Simulação")
    renderizar_kpis(df_final, df_inativos, log_mapas)
    st.markdown("---")

    aba_hist, aba_vagas, aba_excedentes, aba_promocoes, aba_gargalos, aba_piramide, aba_turmas = st.tabs([
        "👤 Histórico Individual", "🟦 Mapa de Claros", "🟥 Mapa de Excedentes",
        "🟩 Volume de Promoções", "⏳ Gargalos de Carreira", "📈 Distribuição do Efetivo",
        "🎓 Análise por Turma",
    ])

    with aba_hist:
        if matriculas_foco:
            sub_abas = st.tabs([str(m) for m in matriculas_foco])
            for i, m in enumerate(matriculas_foco):
                with sub_abas[i]:
                    if not historicos[m]: st.info("Sem alterações.")
                    for ev in historicos[m]: st.write(ev)
        else:
            st.info("Selecione matrículas na barra lateral.")
    with aba_vagas: plotar_heatmap_log(log_mapas, 'vagas_iniciais', "Vagas Ociosas por Data", "Blues", "Qtd Vagas")
    with aba_excedentes: plotar_heatmap_log(log_mapas, 'excedentes', "Excedentes por Data", "Reds", "Qtd Excedentes")
    with aba_promocoes: plotar_heatmap_log(log_mapas, 'promocoes', "Militares Promovidos por Data", "Greens", "Qtd Promovidos")
    with aba_gargalos: plotar_gargalos(tempos_log)
    with aba_piramide: plotar_piramide(df_final, data_alvo)
    with aba_turmas:
        st.markdown("#### Comparação entre turmas")
        comparar_turmas(df_inicial, df_final, df_inativos)
        st.markdown("---")
        anos = _anos_turmas(df_inicial)
        ano_sel = st.selectbox("Detalhar turma (ano de admissão):", anos, key="turma_unico")
        quadro_geral_turma(df_inicial, df_final, df_inativos, ano_sel)
        st.markdown("##### Distribuição dos ativos por posto")
        analisar_turma_snapshot(df_inicial, df_final, df_inativos, ano_sel, mostrar_kpis=False)
        st.markdown("##### Trajetória ao longo dos ciclos")
        plotar_trajetoria_turma(log_mapas, ano_sel)

    st.markdown("---")
    st.markdown("### 📥 Exportar Resultados")
    botoes_download(df_final, df_inativos, sufixo="unico")

def render_comparacao(res):
    data_alvo = res['data_alvo']
    df_fin_A, df_in_A, log_A = res['A']
    df_fin_B, df_in_B, log_B = res['B']
    df_inicial = res['df_inicial']

    st.success("Análise Comparativa Concluída!")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"🔴 Cenário A ({res['tempo_a']} anos sv / {res['idade_a']} idade)")
        renderizar_kpis(df_fin_A, df_in_A, log_A)
        plotar_heatmap_log(log_A, 'vagas_iniciais', "Vagas Ociosas", "Blues", "Vagas")
        plotar_heatmap_log(log_A, 'excedentes', "Acúmulo de Excedentes", "Reds", "Excedentes")
        plotar_piramide(df_fin_A, data_alvo)
        botoes_download(df_fin_A, df_in_A, sufixo="cenarioA")
    with col2:
        st.subheader(f"🔵 Cenário B ({res['tempo_b']} anos sv / {res['idade_b']} idade)")
        renderizar_kpis(df_fin_B, df_in_B, log_B)
        plotar_heatmap_log(log_B, 'vagas_iniciais', "Vagas Ociosas", "Blues", "Vagas")
        plotar_heatmap_log(log_B, 'excedentes', "Acúmulo de Excedentes", "Reds", "Excedentes")
        plotar_piramide(df_fin_B, data_alvo)
        botoes_download(df_fin_B, df_in_B, sufixo="cenarioB")

    st.markdown("---")
    st.markdown("### 🎓 Análise por Turma (A × B)")
    ano_sel = st.selectbox("Turma (ano de admissão):", _anos_turmas(df_inicial), key="turma_cmp")
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown(f"**🔴 Cenário A — Turma {ano_sel}**")
        analisar_turma_snapshot(df_inicial, df_fin_A, df_in_A, ano_sel)
        plotar_trajetoria_turma(log_A, ano_sel)
    with cc2:
        st.markdown(f"**🔵 Cenário B — Turma {ano_sel}**")
        analisar_turma_snapshot(df_inicial, df_fin_B, df_in_B, ano_sel)
        plotar_trajetoria_turma(log_B, ano_sel)

# ==========================================
# INTERFACE PRINCIPAL
# ==========================================
def main():
    st.set_page_config(page_title="Simulador de Promoções", layout="wide")
    st.title("🎖️ Simulador Estratégico de Promoção Militar")

    df_militares = carregar_dados('militares.xlsx')
    df_condutores = carregar_dados('condutores.xlsx')
    df_musicos = carregar_dados('musicos.xlsx')

    st.sidebar.header("⚙️ Configuração Principal")
    tipo_simulacao = st.sidebar.radio("Quadro:", ("QOA/QPC (Administrativo)", "QOMT/QPMT (Condutores)", "QOM/QPM (Músicos)"))

    df_ativo = df_militares if tipo_simulacao == "QOA/QPC (Administrativo)" else (df_condutores if "Condutores" in tipo_simulacao else df_musicos)

    if df_ativo is not None:
        matriculas_foco = st.sidebar.multiselect(
            "Matrículas para acompanhar (Histórico):",
            options=sorted(df_ativo['Matricula'].dropna().unique().astype(int)),
            max_selections=5
        )

        data_alvo_input = st.sidebar.date_input("Data Alvo (Limite):", value=datetime(2030, 12, 31), max_value=datetime(2070, 12, 31))
        
        st.sidebar.markdown("---")
        comparar_cenarios = st.sidebar.checkbox("⚖️ Ativar Modo Comparação de Cenários")
        
        if comparar_cenarios:
            st.sidebar.markdown("### 🔴 Cenário A (Atual)")
            idade_a = st.sidebar.number_input("Idade Máxima (A):", min_value=62, max_value=70, value=63, step=1)
            tempo_a = st.sidebar.number_input("Tempo de Serviço (A):", min_value=32, max_value=45, value=35, step=1)
            
            st.sidebar.markdown("### 🔵 Cenário B (Proposto)")
            idade_b = st.sidebar.number_input("Idade Máxima (B):", min_value=62, max_value=70, value=65, step=1)
            tempo_b = st.sidebar.number_input("Tempo de Serviço (B):", min_value=32, max_value=45, value=40, step=1)
        else:
            st.sidebar.subheader("🕒 Regras de Aposentadoria")
            idade_a = st.sidebar.number_input("Idade Máxima (Anos):", min_value=62, max_value=70, value=63, step=1)
            tempo_a = st.sidebar.number_input("Tempo de Serviço (Anos):", min_value=32, max_value=45, value=35, step=1)

        st.sidebar.markdown("---")
        usar_quantico = st.sidebar.checkbox("Ativar Gerador Quântico (Aposentadorias Estatísticas)")
        perc_quantico = st.sidebar.slider("Taxa de Saída Aleatória (%)", 15, 30, 15) if usar_quantico else 0

        if st.sidebar.button("🚀 Processar Simulação Estratégica", use_container_width=True):
            data_alvo = pd.to_datetime(data_alvo_input)
            with st.spinner('Processando matrizes multidimensionais...'):
                if comparar_cenarios:
                    df_fin_A, df_in_A, _, _, log_A, _ = rodar_cenario(tipo_simulacao, df_ativo, df_condutores, df_musicos, data_alvo, tempo_a, idade_a, matriculas_foco, usar_quantico, perc_quantico)
                    df_fin_B, df_in_B, _, _, log_B, _ = rodar_cenario(tipo_simulacao, df_ativo, df_condutores, df_musicos, data_alvo, tempo_b, idade_b, matriculas_foco, usar_quantico, perc_quantico)
                    st.session_state['resultado'] = {
                        'modo': 'comparar', 'data_alvo': data_alvo, 'df_inicial': df_ativo.copy(),
                        'tempo_a': tempo_a, 'idade_a': idade_a, 'tempo_b': tempo_b, 'idade_b': idade_b,
                        'A': (df_fin_A, df_in_A, log_A), 'B': (df_fin_B, df_in_B, log_B),
                    }
                else:
                    df_final, df_inativos, historicos, _, log_mapas, tempos_log = rodar_cenario(tipo_simulacao, df_ativo, df_condutores, df_musicos, data_alvo, tempo_a, idade_a, matriculas_foco, usar_quantico, perc_quantico)
                    st.session_state['resultado'] = {
                        'modo': 'unico', 'data_alvo': data_alvo, 'df_inicial': df_ativo.copy(),
                        'df_final': df_final, 'df_inativos': df_inativos, 'historicos': historicos,
                        'log_mapas': log_mapas, 'tempos_log': tempos_log, 'matriculas_foco': matriculas_foco,
                    }

        # Renderiza a partir do estado salvo: assim trocar de turma/aba ou baixar Excel
        # não reprocessa a simulação nem apaga os resultados (o botão volta a ser False no rerun).
        res = st.session_state.get('resultado')
        if res is None:
            st.info("Configure os parâmetros na barra lateral e clique em **🚀 Processar Simulação Estratégica**.")
        elif res['modo'] == 'comparar':
            render_comparacao(res)
        else:
            render_unico(res)

    else:
        st.error("Arquivos Excel não encontrados.")

if __name__ == "__main__":
    main()
