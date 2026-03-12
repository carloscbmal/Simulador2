import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import io
import math
import os

# ==========================================
# CONFIGURAÇÕES E CONSTANTES
# ==========================================

HIERARQUIA = ['SD 1', 'CB', '3º SGT', '2º SGT', '1º SGT', 'SUB TEN', 
              '2º TEN', '1º TEN', 'CAP', 'MAJ', 'TEN CEL', 'CEL']

TEMPO_MINIMO = {
    'SD 1': 5, 'CB': 3, '3º SGT': 3, '2º SGT': 3, '1º SGT': 2,
    'SUB TEN': 2, '2º TEN': 2, '1º TEN': 3, 'CAP': 3, 'MAJ': 2, 'TEN CEL': 30
}

POSTOS_COM_EXCEDENTE = ['CB', '3º SGT', '2º SGT', '2º TEN', '1º TEN', 'CAP']

VAGAS_QOA = {
    'SD 1': 600, 'CB': 600, '3º SGT': 573, '2º SGT': 409, '1º SGT': 245,
    'SUB TEN': 96, '2º TEN': 65, '1º TEN': 55, 'CAP': 42, 'MAJ': 20, 'TEN CEL': 5, 'CEL': 9999
}

VAGAS_QOMT = {
    'SD 1': 30, 'CB': 30, '3º SGT': 30,
    '2º SGT': 68, '1º SGT': 49, 'SUB TEN': 19, 
    '2º TEN': 14, '1º TEN': 11, 'CAP': 8, 'MAJ': 4, 'TEN CEL': 2, 'CEL': 0
}

VAGAS_QOM = {
    'SD 1': 30, 'CB': 30,
    '3º SGT': 1, '2º SGT': 13, '1º SGT': 10, 'SUB TEN': 5, 
    '2º TEN': 11, '1º TEN': 9, 'CAP': 6, 'MAJ': 4, 'TEN CEL': 2, 'CEL': 0
}

# ==========================================
# FUNÇÕES DE LÓGICA
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
    
    turmas_processadas_quantico = set()

    for data_referencia in datas_ciclo:
        extras_hoje = (vagas_extras_dict or {}).get(data_referencia, {})

        # --- CAMADA DE SEGURANÇA: IDENTIFICAÇÃO DE VAGAS EXCESSIVAS ---
        vagas_abertas_simultaneas = 0
        for posto in HIERARQUIA:
            limite = vagas_limite_base.get(posto, 0) + extras_hoje.get(posto, 0)
            if limite < 9999: # Ignoramos o posto CEL que tem vagas "infinitas"
                ocupados = len(df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] != "x")])
                vagas_abertas_simultaneas += max(0, limite - ocupados)
        
        # Limite arbitrário de segurança (ajuste conforme necessário para a sua realidade)
        if vagas_abertas_simultaneas > 5000:
            st.warning(f"⚠️ **Alerta de Inconsistência:** Na data {data_referencia.strftime('%d/%m/%Y')}, o sistema identificou {vagas_abertas_simultaneas} vagas abertas simultaneamente. O cenário pode estar distorcido e o cálculo para este ciclo pode não refletir a realidade.")

        # --- 1.1 NOVA LÓGICA: GERADOR QUÂNTICO (COM PROTEÇÕES DINÂMICAS) ---
        if usar_quantico:
            turmas = df['Data_Admissao'].dropna().unique()
            militares_para_remover_indices = []
            
            for turma_data in turmas:
                anos_servico = relativedelta(data_referencia, turma_data).years
                
                # Dinâmico: avalia os militares que estão a 3 anos ou menos do tempo máximo escolhido
                if anos_servico in [tempo_aposentadoria - 3, tempo_aposentadoria - 2, tempo_aposentadoria - 1]:
                    chave_controle = (turma_data, anos_servico)
                    
                    if chave_controle not in turmas_processadas_quantico:
                        mask_turma = (df['Data_Admissao'] == turma_data)
                        df_turma = df[mask_turma].copy()
                        
                        if matriculas_foco:
                            df_turma = df_turma[~df_turma['Matricula'].isin(matriculas_foco)]

                        df_turma['Idade_Calc'] = df_turma['Data_Nascimento'].apply(lambda x: get_anos(data_referencia, x))
                        
                        # Filtro dinâmico com a nova idade
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
        
        # A) PROMOÇÕES
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
                
                if promoveu and militar['Matricula'] in historicos:
                    historicos[militar['Matricula']].append(f"✅ {data_referencia.strftime('%d/%m/%Y')}: Promovido a {proximo_posto}")

            try:
                sobras_deste_ciclo[proximo_posto] = int(vagas_disponiveis)
            except:
                sobras_deste_ciclo[proximo_posto] = 0
        
        sobras_por_ciclo[data_referencia] = sobras_deste_ciclo

        # B) ABSORÇÃO
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

        # C) APOSENTADORIA DINÂMICA
        idade = pd.to_numeric(df['Data_Nascimento'].apply(lambda x: get_anos(data_referencia, x)))
        servico = pd.to_numeric(df['Data_Admissao'].apply(lambda x: get_anos(data_referencia, x)))
        
        # Uso dinâmico das variáveis da interface
        mask_apo = (idade >= idade_aposentadoria) | (servico >= tempo_aposentadoria)
        
        if mask_apo.any():
            militares_aposentando = df[mask_apo]
            for m_foco in historicos:
                if m_foco in militares_aposentando['Matricula'].values:
                    historicos[m_foco].append(f"🛑 {data_referencia.strftime('%d/%m/%Y')}: APOSENTADO (Tempo/Idade)")
            df_inativos = pd.concat([df_inativos, militares_aposentando.copy()], ignore_index=True)
            df = df[~mask_apo].copy()

    return df, df_inativos, historicos, sobras_por_ciclo

# ==========================================
# INTERFACE STREAMLIT
# ==========================================

def main():
    st.set_page_config(page_title="Simulador de Promoções", layout="wide")
    st.title("🎖️ Simulador de Promoção Militar")

    df_militares = carregar_dados('militares.xlsx')
    df_condutores = carregar_dados('condutores.xlsx')
    df_musicos = carregar_dados('musicos.xlsx')

    st.sidebar.header("⚙️ Configuração")
    tipo_simulacao = st.sidebar.radio("Quadro:", ("QOA/QPC (Administrativo)", "QOMT/QPMT (Condutores)", "QOM/QPM (Músicos)"))

    if tipo_simulacao == "QOA/QPC (Administrativo)":
        df_ativo = df_militares
    elif tipo_simulacao == "QOMT/QPMT (Condutores)":
        df_ativo = df_condutores
    else:
        df_ativo = df_musicos

    if df_ativo is not None:
        lista_matriculas = sorted(df_ativo['Matricula'].dropna().unique().astype(int))
        matriculas_foco = st.sidebar.multiselect(
            "Matrículas para acompanhar:",
            options=lista_matriculas,
            max_selections=5
        )

        data_alvo_input = st.sidebar.date_input(
            "Data Alvo:", 
            value=datetime(2030, 12, 31),
            max_value=datetime(2060, 12, 31)
        )
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("🕒 Regras de Aposentadoria")
        
        # Filtros novos em formato numérico
        idade_aposentadoria = st.sidebar.number_input("Idade Máxima (Anos):", min_value=62, max_value=70, value=63, step=1)
        tempo_aposentadoria = st.sidebar.number_input("Tempo de Serviço (Anos):", min_value=32, max_value=45, value=35, step=1)
        
        st.sidebar.markdown("---")
        usar_quantico = st.sidebar.checkbox("Ativar Gerador Quântico")
        perc_quantico = 0
        if usar_quantico:
            perc_quantico = st.sidebar.slider(
                "Geradores de Números Aleatórios Quânticos", 
                min_value=15, 
                max_value=30, 
                value=15,
                help="Antecipa aposentadorias de forma estatística."
            )

        if st.sidebar.button("🚀 Iniciar Simulação"):
            data_alvo = pd.to_datetime(data_alvo_input)
            
            with st.spinner('Simulando...'):
                if tipo_simulacao == "QOA/QPC (Administrativo)":
                    vagas_migradas = {}
                    if df_condutores is not None:
                        _, _, _, s_cond = executar_simulacao_quadro(df_condutores, VAGAS_QOMT, data_alvo, tempo_aposentadoria, idade_aposentadoria, [], usar_quantico=usar_quantico, perc_quantico=perc_quantico)
                        for d, v in s_cond.items():
                            vagas_migradas[d] = v
                    if df_musicos is not None:
                        _, _, _, s_mus = executar_simulacao_quadro(df_musicos, VAGAS_QOM, data_alvo, tempo_aposentadoria, idade_aposentadoria, [], usar_quantico=usar_quantico, perc_quantico=perc_quantico)
                        for d, v in s_mus.items():
                            if d not in vagas_migradas: vagas_migradas[d] = {}
                            for p, q in v.items():
                                mq = q if p in ['SD 1', 'CB', '3º SGT', '2º SGT', '1º SGT', 'SUB TEN'] else math.ceil(q/2)
                                vagas_migradas[d][p] = vagas_migradas[d].get(p, 0) + mq
                    
                    df_final, df_inativos, historicos, _ = executar_simulacao_quadro(df_ativo, VAGAS_QOA, data_alvo, tempo_aposentadoria, idade_aposentadoria, matriculas_foco, vagas_migradas, usar_quantico=usar_quantico, perc_quantico=perc_quantico)
                
                else:
                    vagas_base = VAGAS_QOMT if "Condutores" in tipo_simulacao else VAGAS_QOM
                    df_final, df_inativos, historicos, _ = executar_simulacao_quadro(df_ativo, vagas_base, data_alvo, tempo_aposentadoria, idade_aposentadoria, matriculas_foco, usar_quantico=usar_quantico, perc_quantico=perc_quantico)

                st.success("Simulação Concluída!")

                if matriculas_foco:
                    st.subheader("📊 Histórico Individual")
                    abas = st.tabs([str(m) for m in matriculas_foco])
                    for i, m in enumerate(matriculas_foco):
                        with abas[i]:
                            if not historicos[m]:
                                st.info("Sem alterações relevantes no período.")
                            for evento in historicos[m]:
                                st.write(evento)
                            
                            if m in df_final['Matricula'].values:
                                status = df_final[df_final['Matricula'] == m].iloc[0]
                                st.success(f"Status Final: {status['Posto_Graduacao']} {'(Excedente)' if status['Excedente'] == 'x' else ''}")
                            elif m in df_inativos['Matricula'].values:
                                st.warning("Status Final: Aposentado / Reserva")
                            else:
                                st.error("Status Final: Não encontrado (verifique dados)")

                def to_excel(df):
                    out = io.BytesIO()
                    df.to_excel(out, index=False, engine='xlsxwriter')
                    return out.getvalue()
                
                c1, c2 = st.columns(2)
                c1.download_button("📥 Baixar Ativos", to_excel(df_final), "Ativos_Final.xlsx")
                c2.download_button("📥 Baixar Inativos", to_excel(df_inativos), "Inativos_Final.xlsx")
    else:
        st.error("Arquivos Excel não encontrados. Certifique-se de que os arquivos .xlsx estão na pasta.")

if __name__ == "__main__":
    main()
