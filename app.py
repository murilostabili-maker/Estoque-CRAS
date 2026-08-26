import streamlit as st
import pandas as pd
import os
import glob
from datetime import date, datetime, timedelta

import db
import queries
import reports
from utils import fmt_data_br, fmt_data_col, fmt_mes_br, fmt_semana_br, fmt_texto_col, FORMATO_DATA_INPUT

st.set_page_config(page_title="Controle de Estoque", page_icon="📦", layout="wide")
db.init_db()

# Caminho absoluto da pasta assets, para funcionar independente de onde o
# processo do Streamlit é iniciado (evita erro de caminho relativo em produção/Cloud).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")


def _achar_logo(chaves):
    extensoes_validas = (".png", ".jpg", ".jpeg", ".gif", ".webp")
    pastas_busca = [ASSETS_DIR, BASE_DIR]
    for pasta in pastas_busca:
        if not os.path.isdir(pasta):
            continue
        for caminho in sorted(glob.glob(os.path.join(pasta, "*"))):
            nome_lower = os.path.basename(caminho).lower()
            if not nome_lower.endswith(extensoes_validas):
                continue
            if any(chave in nome_lower for chave in chaves):
                return caminho
    return None


LOGO_CRAS = _achar_logo(["cras"])
LOGO_GESP = _achar_logo(["gesp", "captura"])


def logo(caminho, **kwargs):
    if caminho and os.path.isfile(caminho):
        st.image(caminho, **kwargs)

# ---------------------- Autenticação ----------------------

def tela_login():
    # 1. Define a largura da área central inteira (Aumente o 3 se quiser mais largo)
    col_esq, col_centro, col_dir = st.columns([1, 3, 1]) 
    
    with col_centro:
        # 2. Centralizando a Logo Principal
        col_logo_esq, col_logo_centro, col_logo_dir = st.columns([2, 1, 2])
        with col_logo_centro:
            logo(LOGO_CRAS, width=150)

        # 3. Textos (O HTML já cuida da centralização perfeitamente)
        st.markdown(
            "<h1 style='text-align:center;'>Sistema de Controle de Estoque</h1>",
            unsafe_allow_html=True
        )
        st.markdown(
            "<p style='text-align:center; color:gray;'>Faça login para continuar</p>",
            unsafe_allow_html=True
        )

        # 4. Centralizando o Formulário dentro da área central
        col_form_esq, col_form_centro, col_form_dir = st.columns([1, 4, 1])
        with col_form_centro:
            with st.form("login_form"):
                username = st.text_input("Usuário")
                senha = st.text_input("Senha", type="password")
                # use_container_width=True já faz o botão esticar e ficar centralizado
                entrar = st.form_submit_button("Entrar", use_container_width=True) 

            if entrar:
                user = db.autenticar(username, senha)
                if user:
                    st.session_state["usuario"] = user
                    st.rerun()
                else:
                    st.error("Usuário ou senha inválidos.")

        # 5. Rodapé
        st.markdown("<hr style='margin-top:2rem;'>", unsafe_allow_html=True)
        
        # Texto do rodapé centralizado
        st.markdown(
            "<p style='text-align:center; color:gray; font-size:0.8rem; margin-bottom: 0;'>Desenvolvido por</p>",
            unsafe_allow_html=True
        )
        
        # Centralizando a Logo do Rodapé (Removido o [1, 4] assimétrico)
        col_foot_esq, col_foot_centro, col_foot_dir = st.columns([3, 1, 3])
        with col_foot_centro:
            logo(LOGO_GESP, width=70)
            
def logout_button():
    with st.sidebar:
        st.markdown("---")
        u = st.session_state["usuario"]
        st.caption(f"Logado como **{u['nome']}** ({u['papel']})")
        if st.button("Sair", use_container_width=True):
            del st.session_state["usuario"]
            st.rerun()


# ---------------------- Páginas ----------------------

def pagina_dashboard():
    st.header("📊 Dashboard")
    k = queries.kpis_dashboard()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Itens cadastrados", k["total_itens"])
    c2.metric("Quantidade total em estoque", k["qtd_total"])
    c3.metric("Itens vencidos (lotes)", k["itens_vencidos"], delta_color="inverse")
    c4.metric("Próximos do vencimento", k["itens_a_vencer"], delta_color="inverse")

    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📈 Entradas x Saídas por mês")
        mov = queries.entradas_saidas_por_mes(12)
        if not mov.empty:
            mov_fmt = mov.copy()
            mov_fmt.index = [fmt_mes_br(m) for m in mov_fmt.index]
            st.bar_chart(mov_fmt)
        else:
            st.caption("Ainda não há movimentações registradas.")

    with col2:
        st.subheader("🏆 Ranking de consumo (Top 10)")
        top = queries.materiais_mais_utilizados(10)
        if not top.empty:
            st.dataframe(top, use_container_width=True, hide_index=True)
        else:
            st.caption("Ainda não há saídas registradas.")

    col3, col4 = st.columns(2)
    with col3:
        st.subheader("📉 Evolução do estoque (saldo acumulado)")
        evo = queries.evolucao_estoque(12)
        if not evo.empty:
            evo_fmt = evo.copy()
            evo_fmt["mes"] = evo_fmt["mes"].apply(fmt_mes_br)
            st.line_chart(evo_fmt.set_index("mes")["saldo_acumulado"])
        else:
            st.caption("Ainda não há dados suficientes.")

    with col4:
        st.subheader("⚠️ Itens com estoque baixo")
        baixo = k["estoque_baixo_df"]
        if not baixo.empty:
            st.dataframe(
                baixo[["nome", "apresentacao", "saldo_total", "estoque_minimo"]]
                .rename(columns={"nome": "Item", "apresentacao": "Apresentação",
                                  "saldo_total": "Saldo", "estoque_minimo": "Mínimo"}),
                use_container_width=True, hide_index=True
            )
        else:
            st.success("Nenhum item abaixo do estoque mínimo. ✅")


def pagina_estoque_atual():
    st.header("📦 Estoque Atual")
    saldo = queries.saldo_por_item()

    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        # Usa a lista padrão de categorias (não só as que já aparecem nos itens),
        # para que seja possível filtrar mesmo antes de reclassificar itens antigos.
        categorias = ["Todas"] + sorted(set(db.CATEGORIAS_PADRAO) | set(queries.categorias_existentes()))
        cat_sel = st.selectbox("Filtrar por categoria", categorias)
    with col2:
        unidades = ["Todas"] + sorted(saldo["unidade_medida"].dropna().unique().tolist())
        unidade_sel = st.selectbox("Filtrar por unidade de análise", unidades)
    with col3:
        busca = st.text_input("Buscar item pelo nome")

    df = saldo.copy()
    if cat_sel != "Todas":
        df = df[df["categoria"] == cat_sel]
    if unidade_sel != "Todas":
        df = df[df["unidade_medida"] == unidade_sel]
    if busca:
        df = df[df["nome"].str.contains(busca, case=False, na=False)]

    if (saldo["categoria"] == "Outros").all():
        st.caption(
            "ℹ️ Todos os itens ainda estão como categoria **Outros** (herdado da planilha original). "
            "Use a reclassificação em massa abaixo, ou edite item a item em **Cadastro de Itens**."
        )

    def status(row):
        if row["saldo_total"] <= row["estoque_minimo"]:
            return "🔴 Baixo"
        return "🟢 OK"

    if not df.empty:
        df_view = fmt_data_col(df.copy(), "proxima_validade")
        df_view["Status"] = df_view.apply(status, axis=1)
        df_view = df_view.rename(columns={
            "nome": "Item", "apresentacao": "Apresentação", "unidade_medida": "Unidade de Análise",
            "categoria": "Categoria", "saldo_total": "Saldo Total", "estoque_minimo": "Mínimo",
            "proxima_validade": "Próxima Validade"
        })[["Item", "Apresentação", "Unidade de Análise", "Categoria", "Saldo Total", "Mínimo",
            "Próxima Validade", "Status"]]
        st.dataframe(df_view, use_container_width=True, hide_index=True, height=500)
        st.caption(f"Exibindo {len(df_view)} de {len(saldo)} itens.")
    else:
        st.info("Nenhum item encontrado com esse filtro.")

    with st.expander("🔎 Ver lotes detalhados de um item"):
        st.caption(
            "Um mesmo item pode ter vários lotes com validades diferentes — cada entrada "
            "gera um novo lote e não sobrepõe os anteriores."
        )
        item_nome = st.selectbox("Selecione o item", [""] + saldo["nome"].tolist())
        if item_nome:
            item = queries.buscar_item_por_nome(item_nome)
            lotes = queries.lotes_do_item(item["id"], apenas_com_saldo=False)
            lotes_view = fmt_texto_col(fmt_data_col(lotes, "validade", "data_entrada"), "numero_lote")
            st.dataframe(
                lotes_view[["numero_lote", "quantidade", "validade", "nota_empenho",
                            "valor_unitario", "data_entrada", "observacao"]].rename(columns={
                    "numero_lote": "Lote", "quantidade": "Quantidade", "validade": "Validade",
                    "nota_empenho": "Nota de Empenho", "valor_unitario": "Valor Unitário",
                    "data_entrada": "Data de Entrada", "observacao": "Observação"
                }),
                use_container_width=True, hide_index=True
            )

    papel = st.session_state["usuario"]["papel"]
    if papel in ("Administrador", "Estoque"):
        with st.expander("🏷️ Reclassificar itens em massa (categoria)"):
            st.caption(
                "Selecione vários itens e aplique uma categoria de uma vez — útil para "
                "organizar os itens que vieram da planilha original como 'Outros'."
            )
            itens_sel = st.multiselect("Itens", saldo["nome"].tolist())
            nova_cat = st.selectbox("Nova categoria", db.CATEGORIAS_PADRAO, key="cat_massa")
            if st.button("Aplicar categoria aos itens selecionados", disabled=not itens_sel):
                ids = saldo[saldo["nome"].isin(itens_sel)]["item_id"].tolist()
                queries.reclassificar_categoria_em_massa(ids, nova_cat)
                st.success(f"{len(ids)} item(ns) reclassificado(s) como '{nova_cat}'.")
                st.rerun()


def pagina_cadastro_itens():
    st.header("📝 Cadastro de Itens")

    tab1, tab2 = st.tabs(["Novo item", "Itens cadastrados"])

    with tab1:
        with st.form("novo_item_form", clear_on_submit=True):
            nome = st.text_input("Nome do item *")
            colA, colB = st.columns(2)
            with colA:
                unidade_sel = st.selectbox("Unidade de análise *", db.UNIDADES_PADRAO,
                                            help="Padroniza a forma como o item é contado (Unidade, Caixa, Pacote...).")
                unidade_custom = ""
                if unidade_sel == "Outro (personalizar)":
                    unidade_custom = st.text_input("Especifique a unidade")
            with colB:
                detalhe = st.text_input("Detalhamento (opcional)",
                                         placeholder="Ex: com 100, 5 ml, 4g...")
            categoria = st.selectbox("Categoria", db.CATEGORIAS_PADRAO)
            col1, col2 = st.columns(2)
            with col1:
                estoque_minimo = st.number_input("Estoque mínimo (alerta de estoque baixo)",
                                                   min_value=0, value=5, step=1)
            with col2:
                dias_alerta = st.number_input(
                    "Dias de antecedência para alerta de vencimento",
                    min_value=1, value=db.DIAS_ALERTA_PADRAO, step=1,
                    help="Quantos dias antes do vencimento este item deve aparecer como "
                         "'próximo do vencimento'. Pode ser diferente para cada item."
                )
            salvar = st.form_submit_button("Cadastrar item", use_container_width=True)

        if salvar:
            unidade_final = unidade_custom.strip() if unidade_sel == "Outro (personalizar)" else unidade_sel
            apresentacao = f"{unidade_final} {detalhe.strip()}".strip() if detalhe else unidade_final
            if not nome or not unidade_final:
                st.error("Preencha o nome do item e a unidade de análise.")
            elif queries.buscar_item_por_nome(nome.strip()):
                st.error("Já existe um item cadastrado com esse nome.")
            else:
                queries.criar_item(nome, apresentacao, categoria, estoque_minimo,
                                    unidade_medida=unidade_final, dias_alerta_validade=int(dias_alerta))
                st.success(f"Item '{nome}' cadastrado com sucesso!")
                st.rerun()

    with tab2:
        itens = queries.listar_itens()
        st.dataframe(
            itens[["nome", "apresentacao", "unidade_medida", "categoria", "estoque_minimo",
                   "dias_alerta_validade"]].rename(columns={
                "nome": "Item", "apresentacao": "Apresentação", "unidade_medida": "Unidade de Análise",
                "categoria": "Categoria", "estoque_minimo": "Estoque Mínimo",
                "dias_alerta_validade": "Alerta de Vencimento (dias)"
            }),
            use_container_width=True, hide_index=True, height=400
        )

        st.markdown("##### ✏️ Editar item")
        item_nome = st.selectbox("Selecione um item para editar", [""] + itens["nome"].tolist())
        if item_nome:
            item = queries.buscar_item_por_nome(item_nome)
            with st.form("editar_item_form"):
                novo_nome = st.text_input("Nome", value=item["nome"])
                nova_apres = st.text_input("Apresentação (texto completo)", value=item["apresentacao"])
                idx_un = (db.UNIDADES_PADRAO.index(item["unidade_medida"])
                          if item["unidade_medida"] in db.UNIDADES_PADRAO else len(db.UNIDADES_PADRAO) - 1)
                nova_unidade = st.selectbox("Unidade de análise", db.UNIDADES_PADRAO, index=idx_un)
                idx_cat = db.CATEGORIAS_PADRAO.index(item["categoria"]) if item["categoria"] in db.CATEGORIAS_PADRAO else 0
                nova_cat = st.selectbox("Categoria", db.CATEGORIAS_PADRAO, index=idx_cat)
                col1, col2 = st.columns(2)
                with col1:
                    novo_min = st.number_input("Estoque mínimo", min_value=0, value=item["estoque_minimo"])
                with col2:
                    novo_dias_alerta = st.number_input(
                        "Dias de antecedência para alerta de vencimento",
                        min_value=1, value=item["dias_alerta_validade"] or db.DIAS_ALERTA_PADRAO, step=1
                    )
                ativo = st.checkbox("Item ativo", value=bool(item["ativo"]))
                atualizar = st.form_submit_button("Salvar alterações")
            if atualizar:
                queries.atualizar_item(item["id"], novo_nome, nova_apres, nova_cat, novo_min,
                                        int(ativo), unidade_medida=nova_unidade,
                                        dias_alerta_validade=int(novo_dias_alerta))
                st.success("Item atualizado!")
                st.rerun()


def pagina_entrada_saida():
    st.header("🔄 Entrada e Saída de Materiais")
    usuario = st.session_state["usuario"]["nome"]
    itens = queries.listar_itens()

    tab_entrada, tab_saida = st.tabs(["⬆️ Entrada", "⬇️ Saída"])

    with tab_entrada:
        with st.form("entrada_form", clear_on_submit=True):
            item_nome = st.selectbox("Item *", itens["nome"].tolist())
            col1, col2, col3 = st.columns(3)
            with col1:
                quantidade = st.number_input("Quantidade *", min_value=1, value=1, step=1)
            with col2:
                data_entrada = st.date_input("Data de entrada *", value=date.today(),
                                              format=FORMATO_DATA_INPUT)
            with col3:
                validade = st.date_input("Validade (se aplicável)", value=None,
                                          format=FORMATO_DATA_INPUT)

            col4, col5, col6 = st.columns(3)
            with col4:
                numero_lote = st.text_input("Lote")
            with col5:
                nota_empenho = st.text_input("Nota de Empenho")
            with col6:
                valor = st.number_input("Valor unitário (R$)", min_value=0.0, step=0.01, format="%.2f")

            observacao = st.text_area("Observação")
            confirmar = st.form_submit_button("Registrar entrada", use_container_width=True)

        if confirmar:
            item = queries.buscar_item_por_nome(item_nome)
            queries.registrar_entrada(
                item["id"], int(quantidade), data_entrada.isoformat(),
                validade.isoformat() if validade else None,
                numero_lote, nota_empenho, valor if valor else None,
                observacao, usuario
            )
            st.success(f"Entrada de {quantidade} unidade(s) de '{item_nome}' registrada!")
            st.rerun()

    with tab_saida:
        item_nome_s = st.selectbox("Item *", itens["nome"].tolist(), key="saida_item")
        item_s = queries.buscar_item_por_nome(item_nome_s) if item_nome_s else None
        saldo_disp = 0
        if item_s:
            lotes = queries.lotes_do_item(item_s["id"])
            saldo_disp = int(lotes["quantidade"].sum()) if not lotes.empty else 0
            st.caption(f"Saldo disponível: **{saldo_disp}** {item_s['apresentacao']}")

        with st.form("saida_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                quantidade_s = st.number_input("Quantidade *", min_value=1, value=1, step=1, key="qtd_saida")
            with col2:
                data_saida = st.date_input("Data de saída *", value=date.today(), key="data_saida",
                                            format=FORMATO_DATA_INPUT)

            col3, col4 = st.columns(2)
            with col3:
                setor = st.text_input("Setor *")
            with col4:
                profissional = st.text_input("Profissional *")

            motivo = st.text_input("Motivo *", placeholder="Ex: Uso em atendimento, reposição de kit...")

            perda = st.checkbox("Esta saída é referente a uma perda/descarte?")
            justificativa_perda = ""
            if perda:
                justificativa_perda = st.text_area("Justificativa da perda *",
                                                     placeholder="Ex: Item vencido, dano, quebra...")

            confirmar_s = st.form_submit_button("Registrar saída", use_container_width=True)

        if confirmar_s:
            if not setor or not profissional or not motivo:
                st.error("Preencha setor, profissional e motivo.")
            elif perda and not justificativa_perda:
                st.error("Informe a justificativa da perda.")
            else:
                try:
                    queries.registrar_saida(
                        item_s["id"], int(quantidade_s), data_saida.isoformat(),
                        setor, profissional, motivo, perda, justificativa_perda, usuario
                    )
                    st.success(f"Saída de {quantidade_s} unidade(s) de '{item_nome_s}' registrada!")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def pagina_historico():
    st.header("🕘 Histórico de Movimentações")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        data_ini = st.date_input("De", value=date.today() - timedelta(days=30),
                                  format=FORMATO_DATA_INPUT)
    with col2:
        data_fim = st.date_input("Até", value=date.today(), format=FORMATO_DATA_INPUT)
    with col3:
        tipo = st.selectbox("Tipo", ["Todos", "ENTRADA", "SAIDA"])
    with col4:
        itens = queries.listar_itens()
        item_filtro = st.selectbox("Item", ["Todos"] + itens["nome"].tolist())

    df = queries.historico_movimentos(
        data_ini.isoformat(), data_fim.isoformat(),
        None if tipo == "Todos" else tipo,
        None if item_filtro == "Todos" else item_filtro
    )

    df_view = fmt_data_col(df, "data")
    st.dataframe(
        df_view.rename(columns={
            "tipo": "Tipo", "item": "Item", "quantidade": "Quantidade", "data": "Data",
            "setor": "Setor", "profissional": "Profissional", "motivo": "Motivo",
            "perda": "Perda?", "justificativa_perda": "Justificativa da Perda",
            "nota_empenho": "N. Empenho", "valor_unitario": "Valor Unit.",
            "observacao": "Observação", "usuario": "Registrado por"
        }),
        use_container_width=True, hide_index=True, height=500
    )
    st.caption(f"{len(df)} movimentações no período selecionado.")

    if not df.empty:
        excel_bytes = reports.gerar_excel_movimentos(df_view)
        st.download_button("⬇️ Exportar histórico (Excel)", excel_bytes,
                            file_name=f"historico_{date.today().isoformat()}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def pagina_alertas():
    st.header("⏰ Alertas de Validade")
    st.caption(
        "Cada item tem seu próprio prazo de antecedência para o alerta de vencimento "
        f"(padrão: {db.DIAS_ALERTA_PADRAO} dias). Ajuste em **Cadastro de Itens › Editar item**."
    )

    vencidos, a_vencer = queries.alertas_validade()

    colunas_exibir = ["item_nome", "apresentacao", "numero_lote", "quantidade", "validade",
                       "dias_alerta_validade"]
    renomear = {
        "item_nome": "Item", "apresentacao": "Apresentação", "numero_lote": "Lote",
        "quantidade": "Quantidade", "validade": "Validade",
        "dias_alerta_validade": "Alerta de Vencimento (dias)"
    }

    st.subheader("🔴 Itens vencidos")
    if not vencidos.empty:
        vencidos_view = fmt_texto_col(fmt_data_col(vencidos, "validade"), "numero_lote")
        st.dataframe(
            vencidos_view[colunas_exibir].rename(columns=renomear),
            use_container_width=True, hide_index=True
        )
        st.warning("Providencie o descarte apropriado desses itens, acionando o setor responsável.")
    else:
        st.success("Nenhum item vencido no momento. ✅")

    st.subheader("🟡 Próximos do vencimento")
    if not a_vencer.empty:
        a_vencer_view = fmt_texto_col(fmt_data_col(a_vencer, "validade"), "numero_lote")
        st.dataframe(
            a_vencer_view[colunas_exibir].rename(columns=renomear),
            use_container_width=True, hide_index=True
        )
    else:
        st.info("Nenhum item próximo do vencimento.")


def pagina_consumo():
    st.header("📈 Consumo por Item")
    st.caption("Acompanhe o comportamento de consumo (saídas) de cada item, por semana ou por mês.")

    itens = queries.listar_itens()
    if itens.empty:
        st.info("Nenhum item cadastrado ainda.")
        return

    col1, col2 = st.columns([2, 1])
    with col1:
        item_nome = st.selectbox("Item", itens["nome"].tolist())
    with col2:
        periodicidade = st.radio("Periodicidade", ["Semanal", "Mensal"], horizontal=True)

    item = queries.buscar_item_por_nome(item_nome)
    df = queries.consumo_por_item(item["id"], periodicidade)

    if df.empty:
        st.info(f"Ainda não há saídas registradas para '{item_nome}'.")
        return

    df_view = df.copy()
    if periodicidade == "Semanal":
        df_view["Período"] = df_view["periodo"].apply(fmt_semana_br)
    else:
        df_view["Período"] = df_view["periodo"].apply(fmt_mes_br)

    st.bar_chart(df_view.set_index("Período")["total_saida"])

    st.dataframe(
        df_view[["Período", "total_saida"]].rename(columns={"total_saida": "Quantidade Consumida"}),
        use_container_width=True, hide_index=True
    )
    media = df_view["total_saida"].mean()
    st.caption(f"Consumo médio por período: **{media:.1f}** {item['apresentacao']}.")


def pagina_relatorios():
    st.header("📄 Relatórios")
    st.caption("Geração de relatórios para exportação em Excel ou PDF.")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📊 Estoque atual (Excel)")
        st.write("Inclui o saldo consolidado por item e o detalhamento por lote (situação de agora).")
        excel_bytes = reports.gerar_excel_estoque_atual()
        st.download_button("⬇️ Baixar Excel", excel_bytes,
                            file_name=f"estoque_atual_{date.today().isoformat()}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True)

    with col2:
        st.subheader("📑 Relatório mensal (PDF)")
        st.write("Resumo com indicadores, gráficos de entradas x saídas, ranking de consumo "
                  "e itens vencidos.")
        meses = queries.meses_disponiveis()
        mes_sel = st.selectbox("Mês de referência", meses, format_func=fmt_mes_br)
        pdf_bytes = reports.gerar_pdf_relatorio_mensal(mes_sel)
        st.download_button("⬇️ Baixar PDF", pdf_bytes,
                            file_name=f"relatorio_mensal_{mes_sel}.pdf",
                            mime="application/pdf",
                            use_container_width=True)

def pagina_configuracoes():
    st.header("⚙️ Configurações")
    usuario = st.session_state["usuario"]

    tab1, tab2, tab3 = st.tabs(["Usuários e acesso", "Minha conta", "Importar planilha"])

    with tab1:
        if usuario["papel"] != "Administrador":
            st.warning("Apenas administradores podem gerenciar usuários.")
        else:
            st.subheader("Usuários do sistema")
            usuarios = db.listar_usuarios()
            df = pd.DataFrame(usuarios)
            st.dataframe(
                df.rename(columns={"username": "Usuário", "nome": "Nome", "papel": "Papel",
                                    "ativo": "Ativo"}),
                use_container_width=True, hide_index=True
            )

            st.markdown("##### ➕ Novo usuário")
            with st.form("novo_usuario_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    novo_username = st.text_input("Nome de usuário (login)")
                    novo_nome = st.text_input("Nome completo")
                with col2:
                    nova_senha = st.text_input("Senha", type="password")
                    novo_papel = st.selectbox("Nível de acesso",
                                               ["Administrador", "Estoque", "Consulta"])
                criar = st.form_submit_button("Criar usuário")
            if criar:
                if not novo_username or not nova_senha or not novo_nome:
                    st.error("Preencha todos os campos.")
                else:
                    try:
                        db.criar_usuario(novo_username, nova_senha, novo_nome, novo_papel)
                        st.success("Usuário criado com sucesso!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao criar usuário: {e}")

            st.markdown("##### 🔧 Ativar/Desativar usuário")
            opcoes = {f"{u['nome']} ({u['username']})": u for u in usuarios}
            sel = st.selectbox("Selecione o usuário", [""] + list(opcoes.keys()))
            if sel:
                u = opcoes[sel]
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Desativar" if u["ativo"] else "Ativar"):
                        db.alterar_status_usuario(u["id"], 0 if u["ativo"] else 1)
                        st.rerun()
                with col2:
                    nova_senha_reset = st.text_input("Nova senha (redefinir)", type="password",
                                                       key="reset_senha")
                    if st.button("Redefinir senha") and nova_senha_reset:
                        db.redefinir_senha(u["id"], nova_senha_reset)
                        st.success("Senha redefinida.")

    with tab2:
        st.write(f"**Nome:** {usuario['nome']}")
        st.write(f"**Usuário:** {usuario['username']}")
        st.write(f"**Papel:** {usuario['papel']}")
        with st.form("trocar_senha_form"):
            nova = st.text_input("Nova senha", type="password")
            trocar = st.form_submit_button("Alterar minha senha")
        if trocar and nova:
            db.redefinir_senha(usuario["id"], nova)
            st.success("Senha alterada com sucesso!")

    with tab3:
        if usuario["papel"] != "Administrador":
            st.warning("Apenas administradores podem reimportar a planilha.")
        else:
            st.subheader("📥 Atualizar estoque a partir do arquivo estoque_inicial.csv")
            st.write(
                "Use isso depois de substituir o arquivo `estoque_inicial.csv` no repositório "
                "do GitHub (por exemplo, com os dados de um novo mês da planilha). O sistema "
                "**não** recarrega esse arquivo sozinho depois da primeira execução — é preciso "
                "clicar em um dos botões abaixo."
            )

            contagem = db.contar_registros()
            col1, col2, col3 = st.columns(3)
            col1.metric("Itens no banco hoje", contagem["itens"])
            col2.metric("Lotes no banco hoje", contagem["lotes"])
            col3.metric("Movimentações registradas", contagem["movimentos"])

            st.markdown("---")
            st.markdown("##### Opção 1 · Atualizar (recomendado)")
            st.caption(
                "Mantém tudo que já foi cadastrado e todo o histórico de entradas/saídas. "
                "Para itens já existentes, ajusta o saldo para bater com a planilha nova "
                "(registrando a diferença como um lote de ajuste). Itens novos da planilha "
                "são cadastrados automaticamente."
            )
            if st.button("🔄 Atualizar estoque a partir da planilha", use_container_width=True):
                try:
                    resumo = db.reimportar_estoque_csv(modo="atualizar")
                    st.success(
                        f"Concluído! {resumo['itens_criados']} item(ns) novo(s) criado(s), "
                        f"{resumo['itens_ajustados']} item(ns) com saldo ajustado, "
                        f"{resumo['itens_sem_alteracao']} sem alteração."
                    )
                    st.rerun()
                except FileNotFoundError as e:
                    st.error(str(e))

            st.markdown("---")
            st.markdown("##### Opção 2 · Substituir tudo (cuidado)")
            st.caption(
                "Apaga TODOS os itens, lotes e movimentações (entradas/saídas) já registrados "
                "e recria o estoque do zero, exatamente como está na planilha. Os usuários de "
                "login não são afetados. Só use se ainda não houver movimentações importantes "
                "no sistema."
            )
            confirmar_reset = st.checkbox(
                "Sim, entendo que isso vai apagar todo o histórico de entradas e saídas "
                "já registrado e quero recomeçar do zero com a planilha atual."
            )
            if st.button("🗑️ Substituir tudo pela planilha", use_container_width=True,
                         disabled=not confirmar_reset):
                try:
                    resumo = db.reimportar_estoque_csv(modo="substituir")
                    st.success(f"Estoque recriado do zero com {resumo['itens_criados']} itens da planilha.")
                    st.rerun()
                except FileNotFoundError as e:
                    st.error(str(e))


# ---------------------- Roteamento principal ----------------------

PAGINAS_POR_PAPEL = {
    "Administrador": ["Dashboard", "Estoque Atual", "Cadastro de Itens", "Entrada e Saída",
                       "Histórico", "Alertas de Validade", "Consumo por Item", "Relatórios",
                       "Configurações"],
    "Estoque": ["Dashboard", "Estoque Atual", "Cadastro de Itens", "Entrada e Saída",
                "Histórico", "Alertas de Validade", "Consumo por Item", "Relatórios",
                "Configurações"],
    "Consulta": ["Dashboard", "Estoque Atual", "Histórico", "Alertas de Validade",
                 "Consumo por Item", "Relatórios", "Configurações"],
}

ICONES = {
    "Dashboard": "📊", "Estoque Atual": "📦", "Cadastro de Itens": "📝",
    "Entrada e Saída": "🔄", "Histórico": "🕘", "Alertas de Validade": "⏰",
    "Consumo por Item": "📈", "Relatórios": "📄", "Configurações": "⚙️"
}


def main():
    if "usuario" not in st.session_state:
        tela_login()
        return

    papel = st.session_state["usuario"]["papel"]
    paginas = PAGINAS_POR_PAPEL[papel]

    with st.sidebar:
        col_a, col_b, col_c = st.columns([1, 2, 1])
        with col_b:
            logo(LOGO_CRAS, width=110)
        st.markdown(
            "<p style='text-align:center; font-weight:600; margin-top:0.3rem;'></p>",
            unsafe_allow_html=True
        )
        pagina = st.radio("Navegação", paginas,
                           format_func=lambda p: f"{ICONES.get(p, '')}  {p}")
    logout_button()

    with st.sidebar:
        st.markdown("<div style='margin-top:2rem;'></div>", unsafe_allow_html=True)
        col_x, col_y, col_z = st.columns([1, 1, 1])
        with col_y:
            st.markdown(
                "<p style='text-align:center; color:gray; font-size:0.7rem; margin-bottom:0.2rem;'>Desenvolvido por</p>",
                unsafe_allow_html=True
            )
            sub_esq, sub_dir = st.columns([1, 1])
            with sub_dir:
                logo(LOGO_GESP, width=55)

    if pagina == "Dashboard":
        pagina_dashboard()
    elif pagina == "Estoque Atual":
        pagina_estoque_atual()
    elif pagina == "Cadastro de Itens":
        pagina_cadastro_itens()
    elif pagina == "Entrada e Saída":
        pagina_entrada_saida()
    elif pagina == "Histórico":
        pagina_historico()
    elif pagina == "Alertas de Validade":
        pagina_alertas()
    elif pagina == "Consumo por Item":
        pagina_consumo()
    elif pagina == "Relatórios":
        pagina_relatorios()
    elif pagina == "Configurações":
        pagina_configuracoes()


if __name__ == "__main__":
    main()
