import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import io

def simulador_promocao():
    st.set_page_config(page_title="Simulador CBM", layout="wide")
    st.title("🎖️ Simulador de Promoção Militar")

    # 1. Carga de Dados Automática
    try:
        df_base = pd.read_excel('militares.xlsx')
    except Exception as e:
        st.error(f"Erro: O arquivo 'militares.xlsx' não foi encontrado no repositório. {e}")
        return

    # Formatação Inicial
    df_base['Matricula'] = pd.to_numeric(df_base['Matricula'], errors='coerce')
    df_base['Pos_Hierarquica'] = pd.to_numeric(df_base['Pos_Hierarquica'], errors='coerce')
    df_base['Ultima_promocao'] = pd.to_datetime(df_base['Ultima_promocao'], dayfirst=True)
    df_base['Data_Admissao'] = pd.to_datetime(df_base['Data_Admissao'], dayfirst=True)
    df_base['Data_Nascimento'] = pd.to_datetime(df_base['Data_Nascimento'], dayfirst=True)
    df_base['Excedente'] = df_base.get('Excedente', "").fillna("")

    # 2. Parâmetros na Barra Lateral
    st.sidebar.header("⚙️ Parâmetros da Simulação")
    
    lista_matriculas = sorted(df_base['Matricula'].dropna().unique().astype(int))
    matriculas_foco = st.sidebar.multiselect(
        "Selecione de 1 a 5 matrículas para acompanhar:",
        options=lista_matriculas,
        max_selections=5,
        default=lista_matriculas[0] if lista_matriculas else None
    )

    data_alvo_input = st.sidebar.date_input(
        "Data Alvo (Limite: 31/12/2060):", 
        value=datetime(2030, 12, 31),
        min_value=datetime.today(),
        max_value=datetime(2060, 12, 31)
    )

    tempo_servico_limite = st.sidebar.slider(
        "Tempo de serviço para aposentadoria:",
        min_value=31, max_value=35, value=35, step=1
    )

    botao_simular = st.sidebar.button("🚀 Executar Simulação")

    if botao_simular:
        if not matriculas_foco:
            st.warning("Por favor, selecione pelo menos uma matrícula.")
            return

        df = df_base.copy()
        data_alvo = pd.to_datetime(data_alvo_input)
        data_atual = pd.to_datetime(datetime.now().strftime('%d/%m/%Y'), dayfirst=True)

        # Configurações de Regras
        hierarquia = ['SD 1', 'CB', '3º SGT', '2º SGT', '1º SGT', 'SUB TEN', '2º TEN', '1º TEN', 'CAP', 'MAJ', 'TEN CEL', 'CEL']
        vagas_limite = {'SD 1': 600, 'CB': 600, '3º SGT': 573, '2º SGT': 409, '1º SGT': 245, 'SUB TEN': 96, '2º TEN': 34, '1º TEN': 29, 'CAP': 24, 'MAJ': 10, 'TEN CEL': 3, 'CEL': 9999}
        tempo_minimo = {'SD 1': 5, 'CB': 3, '3º SGT': 3, '2º SGT': 3, '1º SGT': 2, 'SUB TEN': 2, '2º TEN': 3, '1º TEN': 3, 'CAP': 3, 'MAJ': 3, 'TEN CEL': 30}
        postos_com_excedente = ['CB', '3º SGT', '2º SGT', '2º TEN', '1º TEN', 'CAP']

        # Geração do Ciclo
        datas_ciclo = []
        for ano in range(data_atual.year, data_alvo.year + 1):
            for mes, dia in [(6, 26), (11, 29)]:
                d = pd.Timestamp(year=ano, month=mes, day=dia)
                if data_atual <= d <= data_alvo:
                    datas_ciclo.append(d)
        datas_ciclo.sort()

        historicos = {m: [] for m in matriculas_foco}
        df_inativos = pd.DataFrame()

        progress_bar = st.progress(0)
        status_text = st.empty()

        # 3. Loop de Simulação
        for idx_ciclo, data_referencia in enumerate(datas_ciclo):
            status_text.text(f"Simulando ciclo: {data_referencia.strftime('%d/%m/%Y')}")
            progress_bar.progress((idx_ciclo + 1) / len(datas_ciclo))

            # A) Promoções (Lógica Ajustada: Excedente promove direto se houver vaga superior)
            for i in range(len(hierarquia) - 2, -1, -1):
                posto_atual = hierarquia[i]
                proximo_posto = hierarquia[i+1]
                
                # Candidatos ordenados por antiguidade, independente de serem excedentes ou não
                candidatos = df[df['Posto_Graduacao'] == posto_atual].sort_values('Pos_Hierarquica')
                
                for idx, militar in candidatos.iterrows():
                    anos_no_posto = relativedelta(data_referencia, militar['Ultima_promocao']).years
                    
                    # Vagas disponíveis no posto de cima
                    ocupados_superior = len(df[(df['Posto_Graduacao'] == proximo_posto) & (df['Excedente'] != "x")])
                    tem_vaga_superior = ocupados_superior < vagas_limite[proximo_posto]
                    
                    promoveu = False
                    
                    # 1. Regra de Promoção Automática por Tempo (Excedente de 6 anos)
                    if posto_atual in postos_com_excedente and anos_no_posto >= 6:
                        df.at[idx, 'Posto_Graduacao'] = proximo_posto
                        df.at[idx, 'Ultima_promocao'] = data_referencia
                        df.at[idx, 'Excedente'] = "x"
                        promoveu = True
                    
                    # 2. Promoção Normal (Havendo vaga superior e tempo mínimo)
                    # Note que aqui não importa se ele é excedente 'x' ou comum '' no posto atual
                    elif anos_no_posto >= tempo_minimo[posto_atual] and tem_vaga_superior:
                        df.at[idx, 'Posto_Graduacao'] = proximo_posto
                        df.at[idx, 'Ultima_promocao'] = data_referencia
                        df.at[idx, 'Excedente'] = ""
                        promoveu = True

                    if promoveu and militar['Matricula'] in matriculas_foco:
                        historicos[militar['Matricula']].append(f"✅ {data_referencia.strftime('%d/%m/%Y')}: Promovido a {proximo_posto}")

            # B) Absorção
            for posto in hierarquia:
                ativos_normais = len(df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] != "x")])
                vagas_abertas = vagas_limite.get(posto, 0) - ativos_normais
                if vagas_abertas > 0:
                    excedentes = df[(df['Posto_Graduacao'] == posto) & (df['Excedente'] == "x")].sort_values('Pos_Hierarquica')
                    for idx_exc in excedentes.head(int(vagas_abertas)).index:
                        df.at[idx_exc, 'Excedente'] = ""
                        if df.at[idx_exc, 'Matricula'] in matriculas_foco:
                            historicos[df.at[idx_exc, 'Matricula']].append(f"ℹ️ {data_referencia.strftime('%d/%m/%Y')}: Ocupou vaga comum em {posto}")

    
            # C) APOSENTADORIA
                # Função auxiliar para calcular anos (evita erro com datas vazias/NaT)
                def get_anos(data_ref, data_origem):
                    if pd.isna(data_origem): 
                        return 0
                    return relativedelta(data_ref, data_origem).years

                # Calcula a diferença em anos para cada linha
                idade = df['Data_Nascimento'].apply(lambda x: get_anos(data_referencia, x))
                servico = df['Data_Admissao'].apply(lambda x: get_anos(data_referencia, x))
                
                # Define o limite (caso a variável não esteja definida no seu código, use 35)
                tempo_servico_limite = 35 

                # Agora a comparação é entre Inteiro e Inteiro
                mask_apo = (idade >= 63) | (servico >= tempo_servico_limite)
                
                if mask_apo.any():
                    # Verifica se o foco se aposentou
                    if matricula_foco in df[mask_apo]['Matricula'].values:
                        historico_foco.append(f"🛑 {data_referencia.strftime('%d/%m/%Y')}: APOSENTADO")
                    
                    inativos_do_ciclo = df[mask_apo].copy()
                    df_inativos = pd.concat([df_inativos, inativos_do_ciclo], ignore_index=True)
                    df = df[~mask_apo].copy()
          

        # 4. Exibição dos Resultados
        st.divider()
        st.header("📊 Resultados da Visualização")
        abas = st.tabs([f"Matrícula {m}" for m in matriculas_foco])
        
        for i, m_foco in enumerate(matriculas_foco):
            with abas[i]:
                if not historicos[m_foco]:
                    st.info("Nenhuma alteração registrada.")
                else:
                    for evento in historicos[m_foco]:
                        st.write(evento)
                
                if m_foco in df['Matricula'].values:
                    res = df[df['Matricula'] == m_foco].iloc[0]
                    st.success(f"**Status Final:** {res['Posto_Graduacao']} ({'EXCEDENTE' if res['Excedente'] == 'x' else 'ATIVO'})")
                else:
                    st.warning("**Status Final:** INATIVO/RESERVA")

        # Downloads
        st.divider()
        def to_excel_bytes(dataframe):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                dataframe.to_excel(writer, index=False)
            return output.getvalue()

        col1, col2 = st.columns(2)
        with col1:
            st.download_button("📥 Baixar Ativos Final", data=to_excel_bytes(df), file_name="Ativos_Final.xlsx")
        with col2:
            st.download_button("📥 Baixar Inativos Final", data=to_excel_bytes(df_inativos), file_name="Inativos_Final.xlsx")

if __name__ == "__main__":
    simulador_promocao()
