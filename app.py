from datetime import date, datetime
import io
import sqlite3
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="PAINEL DE GESTÃO",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- CONTROLE DE NAVEGAÇÃO ENTRE TELAS ---
if "tela_ativa" not in st.session_state:
  st.session_state.tela_ativa = "INICIO"

# --- CSS RESPONSIVO DE ALTO CONTRASTE (GRADE 2x2 NO MOBILE) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    /* Oculta a barra padrão superior do Streamlit para ganhar tela limpa */
    header[data-testid="stHeader"] {
        display: none !important;
    }

    /* Espaçamento geral da tela */
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
    }

    /* Botão do Título Principal (Voltar ao Início) */
    div[data-testid="stButton"].header-btn > button {
        background: #0f172a;
        color: #ffffff;
        font-size: 16px;
        font-weight: 800;
        letter-spacing: 0.8px;
        border-radius: 8px;
        border: 1px solid #1e293b;
        padding: 12px;
        width: 100%;
        margin-bottom: 8px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.1);
    }

    /* Títulos de Seção */
    .section-title {
        font-size: 15px !important;
        font-weight: 700 !important;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        color: #0f172a;
        text-align: center;
        margin-bottom: 12px;
    }

    /* Botões Principais */
    div.stButton > button {
        background-color: #1e293b;
        color: #ffffff;
        font-weight: 700;
        font-size: 13px;
        letter-spacing: 0.5px;
        padding: 12px 14px;
        border-radius: 8px;
        border: 1px solid #334155;
        width: 100%;
        transition: all 0.2s ease-in-out;
    }

    /* Cards de Métricas com Contraste e Fonte Legível */
    div[data-testid="stMetric"] {
        background: #f8fafc;
        border: 1px solid #cbd5e1;
        padding: 10px 8px;
        border-radius: 8px;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    div[data-testid="stMetricLabel"] {
        font-weight: 700 !important;
        color: #334155 !important; /* Cor escura com alto contraste */
        font-size: 10px !important;
        text-transform: uppercase;
        letter-spacing: 0.3px;
        display: flex;
        justify-content: center;
    }
    div[data-testid="stMetricValue"] {
        color: #0f172a !important;
        font-weight: 800 !important;
        font-size: 17px !important;
        text-align: center;
    }

    /* REGRAS ESPECÍFICAS PARA CELULAR: Grade 2x2 para os Cards */
    @media (max-width: 768px) {
        /* Reduz o gap entre os 3 botões de ação */
        div[data-testid="stHorizontalBlock"]:has(> div > div.stButton) {
            gap: 6px !important;
        }

        /* Transforma as colunas dos cards em grade de 2 por linha */
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) {
            display: flex !important;
            flex-wrap: wrap !important;
            gap: 8px !important;
        }
        div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]) > div[data-testid="column"] {
            flex: 1 1 calc(50% - 8px) !important;
            min-width: calc(50% - 8px) !important;
            margin-bottom: 0px !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# --- BANCO DE DADOS LOCAL (SQLite) ---
def get_db():
  conn = sqlite3.connect("gestao_vendas.db", check_same_thread=False)
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS produtos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            custo_unitario REAL,
            custo_total_real REAL,
            preco_venda_sugerido REAL,
            estoque INTEGER,
            data_entrada DATE
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER,
            nome_produto TEXT,
            canal_venda TEXT,
            quantidade INTEGER,
            preco_vendido REAL,
            custo_total REAL,
            lucro_liquido REAL,
            data_venda DATE
        )
    """)
  conn.commit()
  return conn


conn = get_db()


# --- FUNÇÕES DE PROCESSAMENTO ---
def processar_nfe(xml_bytes, taxa_canal, margem_lucro, embalagem):
  root = ET.fromstring(xml_bytes)
  ns = {"nfe": "http://www.portalfiscal.inf.br/nfe"}

  dhEmi_raw = root.findtext(
      ".//nfe:ide/nfe:dhEmi", default="", namespaces=ns
  ) or root.findtext(".//nfe:ide/nfe:dEmi", default="", namespaces=ns)
  data_entrada = dhEmi_raw[:10] if dhEmi_raw else date.today().isoformat()

  vFrete = float(
      root.findtext(
          ".//nfe:total/nfe:ICMSTot/nfe:vFrete", default="0", namespaces=ns
      )
      or 0
  )
  vOutro = float(
      root.findtext(
          ".//nfe:total/nfe:ICMSTot/nfe:vOutro", default="0", namespaces=ns
      )
      or 0
  )
  vProd_total = float(
      root.findtext(
          ".//nfe:total/nfe:ICMSTot/nfe:vProd", default="1", namespaces=ns
      )
      or 1
  )

  fator_rateio = (vFrete + vOutro) / vProd_total if vProd_total > 0 else 0
  itens_inseridos = 0

  cursor = conn.cursor()
  for det in root.findall(".//nfe:det", ns):
    nome = det.findtext(
        "nfe:prod/nfe:xProd", default="Item sem nome", namespaces=ns
    ).strip()
    qtd_nova = float(det.findtext("nfe:prod/nfe:qCom", default="1", namespaces=ns))
    vUn = float(det.findtext("nfe:prod/nfe:vUnCom", default="0", namespaces=ns))

    custo_real_novo = vUn * (1 + fator_rateio)

    cursor.execute(
        "SELECT id, custo_total_real, estoque FROM produtos WHERE LOWER(nome) ="
        " LOWER(?)",
        (nome,),
    )
    item_existente = cursor.fetchone()

    divisor = 1 - ((taxa_canal / 100) + (margem_lucro / 100))

    if item_existente:
      prod_id, custo_antigo, estoque_antigo = item_existente
      estoque_total = estoque_antigo + int(qtd_nova)
      custo_medio = (
          ((estoque_antigo * custo_antigo) + (qtd_nova * custo_real_novo))
          / estoque_total
          if estoque_total > 0
          else custo_real_novo
      )
      novo_preco = (
          (custo_medio + embalagem) / divisor
          if divisor > 0
          else custo_medio * 1.5
      )

      cursor.execute(
          """
                UPDATE produtos 
                SET estoque = ?, custo_total_real = ?, preco_venda_sugerido = ?, data_entrada = ?
                WHERE id = ?
            """,
          (
              estoque_total,
              round(custo_medio, 2),
              round(novo_preco, 2),
              data_entrada,
              prod_id,
          ),
      )
    else:
      preco_sugerido = (
          (custo_real_novo + embalagem) / divisor
          if divisor > 0
          else custo_real_novo * 1.5
      )
      cursor.execute(
          """
                INSERT INTO produtos (nome, custo_unitario, custo_total_real, preco_venda_sugerido, estoque, data_entrada)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
          (
              nome,
              round(vUn, 2),
              round(custo_real_novo, 2),
              round(preco_sugerido, 2),
              int(qtd_nova),
              data_entrada,
          ),
      )

    itens_inseridos += 1

  conn.commit()
  return itens_inseridos, data_entrada


def cadastrar_produto_manual(
    nome,
    custo_base,
    frete_rateado,
    qtd,
    taxa_canal,
    margem_lucro,
    embalagem,
    data_entrada,
):
  custo_real = custo_base + frete_rateado
  divisor = 1 - ((taxa_canal / 100) + (margem_lucro / 100))
  preco_sugerido = (
      (custo_real + embalagem) / divisor if divisor > 0 else custo_real * 1.5
  )

  cursor = conn.cursor()
  cursor.execute(
      "SELECT id, custo_total_real, estoque FROM produtos WHERE LOWER(nome) ="
      " LOWER(?)",
      (nome.strip(),),
  )
  item_existente = cursor.fetchone()

  if item_existente:
    prod_id, custo_antigo, estoque_antigo = item_existente
    estoque_total = estoque_antigo + int(qtd)
    custo_medio = (
        ((estoque_antigo * custo_antigo) + (qtd * custo_real)) / estoque_total
        if estoque_total > 0
        else custo_real
    )
    novo_preco = (
        (custo_medio + embalagem) / divisor if divisor > 0 else custo_medio * 1.5
    )

    cursor.execute(
        """
            UPDATE produtos 
            SET estoque = ?, custo_total_real = ?, preco_venda_sugerido = ?, data_entrada = ?
            WHERE id = ?
        """,
        (
            estoque_total,
            round(custo_medio, 2),
            round(novo_preco, 2),
            data_entrada,
            prod_id,
        ),
    )
  else:
    cursor.execute(
        """
            INSERT INTO produtos (nome, custo_unitario, custo_total_real, preco_venda_sugerido, estoque, data_entrada)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            nome.strip(),
            round(custo_base, 2),
            round(custo_real, 2),
            round(preco_sugerido, 2),
            int(qtd),
            data_entrada,
        ),
    )

  conn.commit()


# --- 1) TÍTULO CLICÁVEL: RETORNA À PÁGINA INICIAL ---
col_header = st.columns(1)[0]
with col_header:
  st.markdown('<div class="header-btn">', unsafe_allow_html=True)
  if st.button("PAINEL DE GESTÃO", key="btn_home", use_container_width=True):
    st.session_state.tela_ativa = "INICIO"
    st.rerun()
  st.markdown("</div>", unsafe_allow_html=True)

st.write("")

# --- NAVEGAÇÃO PRINCIPAL ---
col_btn1, col_btn2, col_btn3 = st.columns(3)

with col_btn1:
  if st.button("CADASTRAR PRODUTO", use_container_width=True):
    st.session_state.tela_ativa = "CADASTRO"

with col_btn2:
  if st.button("REGISTRAR VENDA", use_container_width=True):
    st.session_state.tela_ativa = "VENDA"

with col_btn3:
  if st.button("RELATÓRIOS", use_container_width=True):
    st.session_state.tela_ativa = "RELATORIOS"

st.write("")

# --- TELAS CONFORME A NAVEGAÇÃO ---

# TELA 1: CADASTRAR PRODUTO
if st.session_state.tela_ativa == "CADASTRO":
  with st.container(border=True):
    st.markdown(
        '<div class="section-title">CADASTRAR PRODUTO</div>',
        unsafe_allow_html=True,
    )

    tipo_entrada = st.radio(
        "MÉTODO DE ENTRADA:",
        ["IMPORTAR ARQUIVO XML", "CADASTRAR MANUALMENTE"],
        horizontal=True,
    )

    if tipo_entrada == "IMPORTAR ARQUIVO XML":
      c_cfg1, c_cfg2, c_cfg3 = st.columns(3)
      with c_cfg1:
        taxa = st.number_input(
            "TAXA ESTIMADA DE VENDA (%)", value=16.0, step=0.5, key="t_xml"
        )
      with c_cfg2:
        margem = st.number_input(
            "MARGEM LÍQUIDA DESEJADA (%)", value=25.0, step=1.0, key="m_xml"
        )
      with c_cfg3:
        custo_emb = st.number_input(
            "CUSTO FIXO EMBALAGEM (R$)", value=3.0, step=0.5, key="e_xml"
        )

      arquivo_xml = st.file_uploader("SELECIONE O ARQUIVO XML", type=["xml"])
      if arquivo_xml and st.button(
          "PROCESSAR E CADASTRAR", type="primary", use_container_width=True
      ):
        total, data_nf = processar_nfe(
            arquivo_xml.read(), taxa, margem, custo_emb
        )
        st.success(f"{total} PRODUTOS REGISTRADOS COM SUCESSO! DATA: {data_nf}")
        st.rerun()

    else:
      cm1, cm2 = st.columns([3, 1])
      with cm1:
        nome_manual = st.text_input(
            "DESCRIÇÃO DO PRODUTO:", placeholder="Ex: Tênis Branco Tam 37"
        )
      with cm2:
        data_manual = st.date_input("DATA DA COMPRA:", value=date.today())

      cv1, cv2, cv3 = st.columns(3)
      with cv1:
        custo_pago = st.number_input(
            "CUSTO PAGO UNITÁRIO (R$)", min_value=0.0, value=35.0, step=1.0
        )
      with cv2:
        frete_por_peca = st.number_input(
            "FRETE RATEADO POR PEÇA (R$)", min_value=0.0, value=0.0, step=0.5
        )
      with cv3:
        qtd_manual = st.number_input(
            "QUANTIDADE COMPRADA", min_value=1, value=1, step=1
        )

      cp1, cp2, cp3 = st.columns(3)
      with cp1:
        taxa_man = st.number_input(
            "TAXA ESTIMADA DE VENDA (%)", value=16.0, step=0.5, key="t_man"
        )
      with cp2:
        margem_man = st.number_input(
            "MARGEM LÍQUIDA DESEJADA (%)", value=25.0, step=1.0, key="m_man"
        )
      with cp3:
        emb_man = st.number_input(
            "CUSTO EMBALAGEM (R$)", value=3.0, step=0.5, key="e_man"
        )

      custo_real_preview = custo_pago + frete_por_peca
      div_preview = 1 - ((taxa_man / 100) + (margem_man / 100))
      preco_sug_preview = (
          (custo_real_preview + emb_man) / div_preview
          if div_preview > 0
          else custo_real_preview * 1.5
      )
      lucro_prev = (preco_sug_preview * (1 - (taxa_man / 100))) - custo_real_preview

      st.info(
          f"PREÇO SUGERIDO: R$ {preco_sug_preview:.2f} | LUCRO LÍQUIDO"
          f" PREVISTO: R$ {lucro_prev:.2f}"
      )

      if st.button(
          "SALVAR NO ESTOQUE", type="primary", use_container_width=True
      ):
        if nome_manual.strip():
          cadastrar_produto_manual(
              nome_manual,
              custo_pago,
              frete_por_peca,
              qtd_manual,
              taxa_man,
              margem_man,
              emb_man,
              data_manual.isoformat(),
          )
          st.success("PRODUTO SALVO COM SUCESSO!")
          st.rerun()
        else:
          st.warning("INFORME A DESCRIÇÃO DO PRODUTO.")

# TELA 2: REGISTRAR VENDA
elif st.session_state.tela_ativa == "VENDA":
  with st.container(border=True):
    st.markdown(
        '<div class="section-title">REGISTRAR VENDA</div>',
        unsafe_allow_html=True,
    )

    produtos_disp = pd.read_sql_query(
        "SELECT id, nome, estoque, preco_venda_sugerido, custo_total_real FROM"
        " produtos WHERE estoque > 0",
        conn,
    )

    if produtos_disp.empty:
      st.info("NENHUM PRODUTO EM ESTOQUE NO MOMENTO.")
    else:
      col_m, col_d = st.columns([2, 1])
      with col_m:
        modo_busca = st.radio(
            "MÉTODO DE LOCALIZAÇÃO:",
            ["DIGITAR CÓDIGO (ID)", "PESQUISAR NA LISTA"],
            horizontal=True,
        )
      with col_d:
        data_venda_input = st.date_input("DATA DA VENDA:", value=date.today())

      prod_selecionado = None

      if modo_busca == "DIGITAR CÓDIGO (ID)":
        id_busca = st.number_input(
            "CÓDIGO (ID):", min_value=1, step=1, value=1
        )
        item = produtos_disp[produtos_disp["id"] == id_busca]
        if not item.empty:
          prod_selecionado = item.iloc[0]
          st.success(
              f"SELECIONADO: [{prod_selecionado['id']}]"
              f" {prod_selecionado['nome']} (ESTOQUE:"
              f" {prod_selecionado['estoque']} UN)"
          )
        else:
          st.warning("CÓDIGO NÃO ENCONTRADO NO ESTOQUE ATIVO.")
      else:
        opcoes = {
            f"[{row['id']}] {row['nome']} | ESTOQUE: {row['estoque']} UN": row
            for _, row in produtos_disp.iterrows()
        }
        escolha = st.selectbox("PRODUTO:", list(opcoes.keys()))
        prod_selecionado = opcoes[escolha]

      if prod_selecionado is not None:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
          canal_venda = st.selectbox(
              "CANAL:",
              [
                  "INSTAGRAM / DIRECT",
                  "MERCADO LIVRE",
                  "SHOPEE",
                  "WHATSAPP",
                  "PRESENCIAL",
                  "OUTRO",
              ],
          )
        with c2:
          qtd_venda = st.number_input(
              "QUANTIDADE",
              min_value=1,
              max_value=int(prod_selecionado["estoque"]),
              value=1,
              key=f"qv_{prod_selecionado['id']}",
          )
        with c3:
          preco_cobrado = st.number_input(
              "PREÇO COBRADO (R$)",
              value=float(prod_selecionado["preco_venda_sugerido"]),
              step=1.0,
              key=f"pc_{prod_selecionado['id']}",
          )
        with c4:
          taxa_venda = st.number_input(
              "TAXA CANAL (%)",
              value=16.0,
              step=0.5,
              key=f"tc_{prod_selecionado['id']}",
          )

        custo_tot = prod_selecionado["custo_total_real"] * qtd_venda
        rec_liq = (preco_cobrado * qtd_venda) * (1 - (taxa_venda / 100))
        lucro_tot = rec_liq - custo_tot

        st.caption(
            f"LUCRO LÍQUIDO REAL: R$ {lucro_tot:.2f} | CUSTO TOTAL:"
            f" R$ {custo_tot:.2f}"
        )

        if st.button(
            "CONFIRMAR VENDA E ATUALIZAR ESTOQUE",
            type="primary",
            use_container_width=True,
        ):
          cursor = conn.cursor()
          cursor.execute(
              "UPDATE produtos SET estoque = estoque - ? WHERE id = ?",
              (qtd_venda, int(prod_selecionado["id"])),
          )
          cursor.execute(
              """
                    INSERT INTO vendas (produto_id, nome_produto, canal_venda, quantidade, preco_vendido, custo_total, lucro_liquido, data_venda)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
              (
                  int(prod_selecionado["id"]),
                  prod_selecionado["nome"],
                  canal_venda,
                  qtd_venda,
                  preco_cobrado,
                  custo_tot,
                  round(lucro_tot, 2),
                  data_venda_input.isoformat(),
              ),
          )
          conn.commit()
          st.success("VENDA REGISTRADA!")
          st.rerun()

# TELA 3: RELATÓRIOS
elif st.session_state.tela_ativa == "RELATORIOS":
  with st.container(border=True):
    st.markdown(
        '<div class="section-title">RELATÓRIOS DE VENDAS</div>',
        unsafe_allow_html=True,
    )

    df_vendas_all = pd.read_sql_query(
        """
            SELECT id, data_venda, nome_produto, canal_venda, quantidade, preco_vendido, custo_total, lucro_liquido 
            FROM vendas ORDER BY data_venda DESC, id DESC
        """,
        conn,
    )

    if df_vendas_all.empty:
      st.info("NENHUMA VENDA REALIZADA ATÉ O MOMENTO.")
    else:
      df_vendas_all["AnoMes"] = pd.to_datetime(
          df_vendas_all["data_venda"]
      ).dt.strftime("%Y-%m")
      meses = ["TODOS OS MESES"] + sorted(
          list(df_vendas_all["AnoMes"].unique()), reverse=True
      )

      mes_sel = st.selectbox("FILTRAR POR MÊS:", meses)
      df_f = (
          df_vendas_all
          if mes_sel == "TODOS OS MESES"
          else df_vendas_all[df_vendas_all["AnoMes"] == mes_sel]
      )

      df_show = df_f[[
          "data_venda",
          "nome_produto",
          "canal_venda",
          "quantidade",
          "preco_vendido",
          "lucro_liquido",
      ]].rename(
          columns={
              "data_venda": "DATA",
              "nome_produto": "PRODUTO",
              "canal_venda": "CANAL",
              "quantidade": "QTD",
              "preco_vendido": "VALOR VENDA (R$)",
              "lucro_liquido": "LUCRO (R$)",
          }
      )
      st.dataframe(df_show, use_container_width=True, hide_index=True)

      buffer = io.BytesIO()
      with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_f.to_excel(writer, index=False, sheet_name="VENDAS")
      st.download_button(
          label="EXPORTAR RELATÓRIO EM EXCEL",
          data=buffer.getvalue(),
          file_name=f"relatorio_vendas_{mes_sel}.xlsx",
          mime=(
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          ),
      )

st.write("")

# --- 3) CARDS DE MÉTRICAS INFERIORES COM "MARGEM %" ---
df_produtos_geral = pd.read_sql_query(
    "SELECT COUNT(id) as total_modelos, SUM(estoque) as total_pecas FROM"
    " produtos",
    conn,
)
df_vendas_metricas = pd.read_sql_query(
    "SELECT SUM(preco_vendido * quantidade) as faturamento_total,"
    " SUM(lucro_liquido) as lucro_total FROM vendas",
    conn,
)

total_modelos = df_produtos_geral["total_modelos"].iloc[0] or 0
total_pecas = df_produtos_geral["total_pecas"].iloc[0] or 0
faturamento_acumulado = (
    df_vendas_metricas["faturamento_total"].iloc[0] or 0.0
)
lucro_acumulado = df_vendas_metricas["lucro_total"].iloc[0] or 0.0

margem_percentual = (
    (lucro_acumulado / faturamento_acumulado * 100)
    if faturamento_acumulado > 0
    else 0.0
)

card_col1, card_col2, card_col3, card_col4 = st.columns(4)
card_col1.metric("MODELOS CADASTRADOS", f"{int(total_modelos)} TIPOS")
card_col2.metric("TOTAL EM ESTOQUE", f"{int(total_pecas)} PEÇAS")
card_col3.metric("LUCRO LÍQUIDO REAL", f"R$ {lucro_acumulado:,.2f}")
card_col4.metric("MARGEM REAL", f"{margem_percentual:.1f}%")
