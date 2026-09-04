"""
Regras de negócio do estoque: cadastro de itens, entrada/saída de materiais,
consultas para dashboard, alertas de validade e relatórios.
"""
import pandas as pd
from datetime import date, datetime, timedelta
import db
from db import get_conn

# ---------------------- Itens ----------------------

def listar_itens(somente_ativos=True):
    q = "SELECT * FROM itens"
    if somente_ativos:
        q += " WHERE ativo = 1"
    q += " ORDER BY nome"
    return db.read_sql(q)


def buscar_item_por_nome(nome):
    conn = get_conn()
    row = conn.execute("SELECT * FROM itens WHERE nome = ?", (nome,)).fetchone()
    conn.close()
    return dict(row) if row else None


def criar_item(nome, apresentacao, categoria, estoque_minimo, unidade_medida="Unidade",
                dias_alerta_validade=120):
    conn = get_conn()
    conn.execute(
        """INSERT INTO itens (nome, apresentacao, unidade_medida, categoria, estoque_minimo,
                               dias_alerta_validade)
           VALUES (?,?,?,?,?,?)""",
        (nome.strip(), apresentacao.strip(), unidade_medida, categoria, estoque_minimo,
         dias_alerta_validade),
    )
    conn.commit()
    conn.close()


def atualizar_item(item_id, nome, apresentacao, categoria, estoque_minimo, ativo=1,
                    unidade_medida="Unidade", dias_alerta_validade=120):
    conn = get_conn()
    conn.execute(
        """UPDATE itens SET nome=?, apresentacao=?, unidade_medida=?, categoria=?,
                             estoque_minimo=?, dias_alerta_validade=?, ativo=? WHERE id=?""",
        (nome.strip(), apresentacao.strip(), unidade_medida, categoria, estoque_minimo,
         dias_alerta_validade, ativo, item_id),
    )
    conn.commit()
    conn.close()


def reclassificar_categoria_em_massa(item_ids, nova_categoria):
    """Atualiza a categoria de vários itens de uma vez (útil para corrigir itens
    importados da planilha original, que entraram todos como 'Outros')."""
    if not item_ids:
        return
    conn = get_conn()
    conn.executemany(
        "UPDATE itens SET categoria = ? WHERE id = ?",
        [(nova_categoria, item_id) for item_id in item_ids],
    )
    conn.commit()
    conn.close()


# ---------------------- Lotes / Saldo ----------------------

def saldo_por_item():
    """Retorna DataFrame com saldo total (soma dos lotes) por item."""
    q = """
        SELECT i.id as item_id, i.nome, i.apresentacao, i.unidade_medida, i.categoria,
               i.estoque_minimo, i.dias_alerta_validade,
               COALESCE(SUM(l.quantidade), 0) as saldo_total,
               MIN(CASE WHEN l.quantidade > 0 THEN l.validade END) as proxima_validade
        FROM itens i
        LEFT JOIN lotes l ON l.item_id = i.id
        WHERE i.ativo = 1
        GROUP BY i.id
        ORDER BY i.nome
    """
    return db.read_sql(q)


def lotes_do_item(item_id, apenas_com_saldo=True):
    q = "SELECT * FROM lotes WHERE item_id = ?"
    if apenas_com_saldo:
        q += " AND quantidade > 0"
    q += " ORDER BY (validade IS NULL), validade ASC"
    return db.read_sql(q, (item_id,))


def todos_lotes_com_item():
    q = """
        SELECT l.*, i.nome as item_nome, i.apresentacao, i.categoria,
               i.dias_alerta_validade
        FROM lotes l JOIN itens i ON i.id = l.item_id
        WHERE i.ativo = 1
        ORDER BY (l.validade IS NULL), l.validade ASC
    """
    return db.read_sql(q)


# ---------------------- Entrada de materiais ----------------------

def registrar_entrada(item_id, quantidade, data_entrada, validade, numero_lote,
                       nota_empenho, valor_unitario, observacao, usuario):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO lotes (item_id, numero_lote, quantidade, validade, nota_empenho,
                               valor_unitario, data_entrada, observacao)
           VALUES (?,?,?,?,?,?,?,?)""",
        (item_id, numero_lote, quantidade, validade, nota_empenho, valor_unitario,
         data_entrada, observacao),
    )
    lote_id = cur.lastrowid
    cur.execute(
        """INSERT INTO movimentos (tipo, item_id, lote_id, quantidade, data, nota_empenho,
                                    valor_unitario, observacao, usuario)
           VALUES ('ENTRADA', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, lote_id, quantidade, data_entrada, nota_empenho, valor_unitario,
         observacao, usuario),
    )
    conn.commit()
    conn.close()


# ---------------------- Saída de materiais ----------------------

def registrar_saida(item_id, quantidade, data_saida, setor, profissional, motivo,
                     perda, justificativa_perda, usuario):
    """Dá baixa nos lotes seguindo FEFO (primeiro a vencer, primeiro a sair)."""
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """SELECT id, quantidade FROM lotes WHERE item_id = ? AND quantidade > 0
           ORDER BY (validade IS NULL), validade ASC""",
        (item_id,),
    )
    lotes = cur.fetchall()
    restante = quantidade
    saldo_disponivel = sum(l["quantidade"] for l in lotes)

    if saldo_disponivel < quantidade:
        conn.close()
        raise ValueError(
            f"Saldo insuficiente. Disponível: {saldo_disponivel}, solicitado: {quantidade}."
        )

    for lote in lotes:
        if restante <= 0:
            break
        retirar = min(lote["quantidade"], restante)
        cur.execute(
            "UPDATE lotes SET quantidade = quantidade - ? WHERE id = ?",
            (retirar, lote["id"]),
        )
        cur.execute(
            """INSERT INTO movimentos (tipo, item_id, lote_id, quantidade, data, setor,
                                        profissional, motivo, perda, justificativa_perda, usuario)
               VALUES ('SAIDA', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item_id, lote["id"], retirar, data_saida, setor, profissional, motivo,
             int(perda), justificativa_perda, usuario),
        )
        restante -= retirar

    conn.commit()
    conn.close()


# ---------------------- Histórico ----------------------

def historico_movimentos(data_ini=None, data_fim=None, tipo=None, item_nome=None):
    q = """
        SELECT m.id, m.tipo, i.nome as item, m.quantidade, m.data, m.setor, m.profissional,
               m.motivo, m.perda, m.justificativa_perda, m.nota_empenho, m.valor_unitario,
               m.observacao, m.usuario
        FROM movimentos m JOIN itens i ON i.id = m.item_id
        WHERE 1=1
    """
    params = []
    if data_ini:
        q += " AND m.data >= ?"
        params.append(data_ini)
    if data_fim:
        q += " AND m.data <= ?"
        params.append(data_fim)
    if tipo:
        q += " AND m.tipo = ?"
        params.append(tipo)
    if item_nome:
        q += " AND i.nome = ?"
        params.append(item_nome)
    q += " ORDER BY m.data DESC, m.id DESC"
    return db.read_sql(q, params)


# ---------------------- Alertas de validade ----------------------

def alertas_validade():
    """Calcula itens vencidos e próximos do vencimento usando o prazo de alerta
    configurado individualmente em cada item (coluna dias_alerta_validade),
    em vez de um número fixo de dias para todos."""
    df = todos_lotes_com_item()
    df = df[df["quantidade"] > 0].copy()
    df = df[df["validade"].notna() & (df["validade"] != "")]
    hoje = date.today()

    df["validade_dt"] = pd.to_datetime(df["validade"]).dt.date
    df["dias_alerta_validade"] = df["dias_alerta_validade"].fillna(120).astype(int)
    df["limite_alerta_dt"] = df["dias_alerta_validade"].apply(
        lambda d: hoje + timedelta(days=int(d))
    )

    vencidos = df[df["validade_dt"] < hoje].sort_values("validade_dt")
    a_vencer = df[
        (df["validade_dt"] >= hoje) & (df["validade_dt"] <= df["limite_alerta_dt"])
    ].sort_values("validade_dt")
    return vencidos, a_vencer


# ---------------------- Dashboard ----------------------

def kpis_dashboard():
    saldo = saldo_por_item()
    vencidos, a_vencer = alertas_validade()

    total_itens = len(saldo)
    qtd_total = int(saldo["saldo_total"].sum()) if not saldo.empty else 0
    estoque_baixo = saldo[saldo["saldo_total"] <= saldo["estoque_minimo"]]

    return {
        "total_itens": total_itens,
        "qtd_total": qtd_total,
        "itens_vencidos": len(vencidos["item_nome"].unique()) if not vencidos.empty else 0,
        "itens_a_vencer": len(a_vencer["item_nome"].unique()) if not a_vencer.empty else 0,
        "estoque_baixo_qtd": len(estoque_baixo),
        "estoque_baixo_df": estoque_baixo,
    }


def entradas_saidas_por_mes(meses=6):
    # "data" é sempre armazenada como texto ISO 'AAAA-MM-DD', então pegar os 7
    # primeiros caracteres com substr() dá o mês e funciona igual em SQLite e Postgres.
    q = """
        SELECT substr(data,1,7) as mes, tipo, SUM(quantidade) as total
        FROM movimentos
        WHERE tipo IN ('ENTRADA','SAIDA')
        GROUP BY substr(data,1,7), tipo
        ORDER BY mes
    """
    df = db.read_sql(q)
    if df.empty:
        return df
    pivot = df.pivot(index="mes", columns="tipo", values="total").fillna(0)
    pivot = pivot.tail(meses)
    return pivot


def materiais_mais_utilizados(top_n=10):
    q = """
        SELECT i.nome as item, SUM(m.quantidade) as total_saida
        FROM movimentos m JOIN itens i ON i.id = m.item_id
        WHERE m.tipo = 'SAIDA'
        GROUP BY i.nome
        ORDER BY total_saida DESC
        LIMIT ?
    """
    return db.read_sql(q, (top_n,))


def evolucao_estoque(meses=6):
    """Evolução aproximada do saldo total ao longo dos meses, com base nas movimentações."""
    q = """
        SELECT substr(data,1,7) as mes,
               SUM(CASE WHEN tipo='ENTRADA' THEN quantidade ELSE -quantidade END) as delta
        FROM movimentos
        WHERE tipo IN ('ENTRADA','SAIDA')
        GROUP BY substr(data,1,7)
        ORDER BY mes
    """
    df = db.read_sql(q)
    if df.empty:
        return df
    df["saldo_acumulado"] = df["delta"].cumsum()
    return df.tail(meses)


# ---------------------- Consumo por item (gráfico semanal/mensal) ----------------------

def consumo_por_item(item_id, periodicidade="Mensal"):
    """Retorna o total de saídas (consumo) de um item agrupado por semana ou por mês.
    Busca as saídas em bruto e agrupa com pandas (em vez de strftime do SQLite),
    para funcionar igual em qualquer um dos dois backends."""
    q = """
        SELECT data, quantidade FROM movimentos
        WHERE tipo = 'SAIDA' AND item_id = ?
    """
    bruto = db.read_sql(q, (item_id,))
    if bruto.empty:
        return bruto

    formato = "%Y-%W" if periodicidade == "Semanal" else "%Y-%m"
    bruto["periodo"] = pd.to_datetime(bruto["data"]).dt.strftime(formato)
    df = bruto.groupby("periodo", as_index=False)["quantidade"].sum()
    df = df.rename(columns={"quantidade": "total_saida"}).sort_values("periodo")
    return df.reset_index(drop=True)


# ---------------------- Relatórios filtrados por mês ----------------------

def meses_disponiveis():
    """Lista os meses (AAAA-MM) que possuem alguma movimentação registrada, mais recente primeiro."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT substr(data,1,7) as mes FROM movimentos ORDER BY mes DESC"
    ).fetchall()
    conn.close()
    meses = [r["mes"] for r in rows if r["mes"]]
    mes_atual = date.today().strftime("%Y-%m")
    if mes_atual not in meses:
        meses = [mes_atual] + meses
    return meses


def resumo_movimentos_mes(ano_mes):
    """Total de entradas e saídas de um mês específico (AAAA-MM)."""
    q = """
        SELECT tipo, COALESCE(SUM(quantidade), 0) as total
        FROM movimentos
        WHERE substr(data,1,7) = ? AND tipo IN ('ENTRADA','SAIDA')
        GROUP BY tipo
    """
    df = db.read_sql(q, (ano_mes,))
    totais = {"ENTRADA": 0, "SAIDA": 0}
    for _, row in df.iterrows():
        totais[row["tipo"]] = int(row["total"])
    return totais


def materiais_mais_utilizados_periodo(ano_mes, top_n=10):
    """Ranking de consumo (saídas) restrito a um mês específico (AAAA-MM)."""
    q = """
        SELECT i.nome as item, SUM(m.quantidade) as total_saida
        FROM movimentos m JOIN itens i ON i.id = m.item_id
        WHERE m.tipo = 'SAIDA' AND substr(m.data,1,7) = ?
        GROUP BY i.nome
        ORDER BY total_saida DESC
        LIMIT ?
    """
    return db.read_sql(q, (ano_mes, top_n))


# ---------------------- Categorias ----------------------

def categorias_existentes():
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT categoria FROM itens WHERE categoria IS NOT NULL").fetchall()
    conn.close()
    return sorted([r["categoria"] for r in rows if r["categoria"]])
