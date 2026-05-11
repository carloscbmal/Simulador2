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

                        df_turma['Idade_Calc'] = df_turma['Data_Nascimento'].apply(lambda x: get_anos(data_referencia, x))
                        df_turma = df_turma[ (anos_servico >= tempo_aposentadoria - 3) | (df_turma['Idade_Calc'] > idade_aposentadoria) ]

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
                if posto_atual in POSTOS_COM_EXCEDENTE and anos_no_posto >= 6:
                    df.at[idx, 'Posto_Graduacao'] = proximo_posto
                    df.at[idx, 'Ultima_promocao'] = data_referencia
                    df.at[idx, 'Excedente'] = "x"
                    promoveu = True
                elif anos_no_posto >= TEMPO_MINIMO.get(posto_atual, 99) and vagas_disponiveis > 0:
                    df.at[idx, 'Posto_Graduacao'] = proximo_posto
                    df.at[idx, 'Ultima_promocao'] = data_referencia
                    df.at[idx, 'Excedente'] = ""
                    vagas_disponiveis -= 1
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

        data_alvo_input = st.sidebar.date_input("Data Alvo (Limite):", value=datetime(2030, 12, 31), max_value=datetime(2060, 12, 31))
        
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
                    # Roda os dois cenários
                    df_fin_A, df_in_A, hist_A, _, log_A, tempo_log_A = rodar_cenario(tipo_simulacao, df_ativo, df_condutores, df_musicos, data_alvo, tempo_a, idade_a, matriculas_foco, usar_quantico, perc_quantico)
                    df_fin_B, df_in_B, hist_B, _, log_B, tempo_log_B = rodar_cenario(tipo_simulacao, df_ativo, df_condutores, df_musicos, data_alvo, tempo_b, idade_b, matriculas_foco, usar_quantico, perc_quantico)
                    
                    st.success("Análise Comparativa Concluída!")
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.subheader(f"🔴 Cenário A ({tempo_a} anos sv / {idade_a} idade)")
                        renderizar_kpis(df_fin_A, df_in_A, log_A)
                        plotar_heatmap_log(log_A, 'vagas_iniciais', "Vagas Ociosas", "Blues", "Vagas")
                        plotar_heatmap_log(log_A, 'excedentes', "Acúmulo de Excedentes", "Reds", "Excedentes")
                        plotar_piramide(df_fin_A, data_alvo)

                    with col2:
                        st.subheader(f"🔵 Cenário B ({tempo_b} anos sv / {idade_b} idade)")
                        renderizar_kpis(df_fin_B, df_in_B, log_B)
                        plotar_heatmap_log(log_B, 'vagas_iniciais', "Vagas Ociosas", "Blues", "Vagas")
                        plotar_heatmap_log(log_B, 'excedentes', "Acúmulo de Excedentes", "Reds", "Excedentes")
                        plotar_piramide(df_fin_B, data_alvo)

                else:
                    # Roda cenário único
                    df_final, df_inativos, historicos, _, log_mapas, tempos_log = rodar_cenario(tipo_simulacao, df_ativo, df_condutores, df_musicos, data_alvo, tempo_a, idade_a, matriculas_foco, usar_quantico, perc_quantico)
                    
                    st.success("Simulação Estratégica Concluída!")
                    
                    # Painel de KPIs Superior
                    st.markdown("### 📊 Panorama Geral ao Final da Simulação")
                    renderizar_kpis(df_final, df_inativos, log_mapas)
                    st.markdown("---")

                    aba_hist, aba_vagas, aba_excedentes, aba_promocoes, aba_gargalos, aba_piramide = st.tabs([
                        "👤 Histórico Individual", "🟦 Mapa de Claros", "🟥 Mapa de Excedentes", 
                        "🟩 Volume de Promoções", "⏳ Gargalos de Carreira", "📈 Distribuição do Efetivo"
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

    else:
        st.error("Arquivos Excel não encontrados.")

if __name__ == "__main__":
    main()
