"""
Geração de relatórios mensais em Excel e PDF.
"""
import io
from datetime import date
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart

import queries
from utils import fmt_data_col, fmt_texto_col

MESES_PT_FULL = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio", 6: "Junho",
    7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
}


def mes_label_pt(ano_mes: str) -> str:
    """Converte 'AAAA-MM' em 'Mês/AAAA' por extenso (ex: 'Agosto/2026')."""
    try:
        ano, mes = ano_mes.split("-")
        return f"{MESES_PT_FULL[int(mes)]}/{ano}"
    except Exception:
        return ano_mes


def _grafico_barras(labels, valores, titulo="", largura=460, altura=190, cor="#2E5B4C"):
    """Monta um gráfico de barras simples (reportlab.graphics) para embutir no PDF."""
    d = Drawing(largura, altura + 25)
    chart = VerticalBarChart()
    chart.x = 45
    chart.y = 15
    chart.height = altura - 45
    chart.width = largura - 70
    chart.data = [[float(v) for v in valores]]
    chart.categoryAxis.categoryNames = [
        (lbl if len(str(lbl)) <= 16 else str(lbl)[:14] + "…") for lbl in labels
    ]
    chart.categoryAxis.labels.angle = 25
    chart.categoryAxis.labels.dy = -8
    chart.categoryAxis.labels.dx = -4
    chart.categoryAxis.labels.fontSize = 7
    chart.valueAxis.valueMin = 0
    chart.bars[0].fillColor = colors.HexColor(cor)
    d.add(chart)
    if titulo:
        d.add(String(largura / 2, altura + 8, titulo, fontSize=10, textAnchor="middle"))
    return d


def gerar_excel_estoque_atual() -> bytes:
    saldo = queries.saldo_por_item()
    lotes = queries.todos_lotes_com_item()
    lotes = lotes[lotes["quantidade"] > 0]

    saldo_fmt = fmt_data_col(saldo, "proxima_validade")
    lotes_fmt = fmt_texto_col(fmt_data_col(lotes, "validade", "data_entrada"), "numero_lote", "observacao")

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        saldo_fmt.rename(columns={
            "nome": "Item", "apresentacao": "Apresentação", "unidade_medida": "Unidade de Análise",
            "categoria": "Categoria", "saldo_total": "Saldo Total", "estoque_minimo": "Estoque Mínimo",
            "dias_alerta_validade": "Alerta de Vencimento (dias)", "proxima_validade": "Próxima Validade"
        }).drop(columns=["item_id"]).to_excel(writer, sheet_name="Estoque Atual", index=False)

        lotes_fmt[["item_nome", "numero_lote", "quantidade", "validade", "nota_empenho",
                    "valor_unitario", "data_entrada", "observacao"]].rename(columns={
            "item_nome": "Item", "numero_lote": "Lote", "quantidade": "Quantidade",
            "validade": "Validade", "nota_empenho": "Nota de Empenho",
            "valor_unitario": "Valor Unitário", "data_entrada": "Data Entrada",
            "observacao": "Observação"
        }).to_excel(writer, sheet_name="Lotes", index=False)
    buffer.seek(0)
    return buffer.getvalue()


def gerar_excel_movimentos(df_movimentos: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_movimentos.to_excel(writer, sheet_name="Movimentações", index=False)
    buffer.seek(0)
    return buffer.getvalue()


def gerar_pdf_relatorio_mensal(ano_mes: str = None) -> bytes:
    """Gera o PDF do relatório mensal. `ano_mes` no formato 'AAAA-MM' filtra as
    movimentações (entradas/saídas e ranking de consumo) daquele mês específico;
    se não for informado, usa o mês atual. Itens vencidos/a vencer refletem
    sempre a situação atual do estoque (não dependem do mês escolhido)."""
    if not ano_mes:
        ano_mes = date.today().strftime("%Y-%m")
    mes_label = mes_label_pt(ano_mes)

    saldo = queries.saldo_por_item()
    vencidos, a_vencer = queries.alertas_validade()
    vencidos = fmt_texto_col(fmt_data_col(vencidos, "validade"), "numero_lote")
    a_vencer = fmt_texto_col(fmt_data_col(a_vencer, "validade"), "numero_lote")
    top_mes = queries.materiais_mais_utilizados_periodo(ano_mes, 10)
    totais_mes = queries.resumo_movimentos_mes(ano_mes)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                             topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f"Relatório de Estoque - {mes_label}", styles["Title"]))
    elements.append(Paragraph(f"Gerado em {date.today().strftime('%d/%m/%Y')}", styles["Normal"]))
    elements.append(Spacer(1, 0.5 * cm))

    elements.append(Paragraph("Resumo Geral (situação atual do estoque)", styles["Heading2"]))
    resumo_data = [
        ["Indicador", "Valor"],
        ["Total de itens cadastrados", str(len(saldo))],
        ["Quantidade total em estoque", str(int(saldo["saldo_total"].sum()) if not saldo.empty else 0)],
        ["Itens vencidos (lotes)", str(len(vencidos))],
        ["Itens próximos do vencimento (conforme alerta de cada item)", str(len(a_vencer))],
        ["Itens com estoque baixo", str(len(saldo[saldo["saldo_total"] <= saldo["estoque_minimo"]]))],
    ]
    t = Table(resumo_data, colWidths=[12 * cm, 6 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E5B4C")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 0.7 * cm))

    elements.append(Paragraph(f"Movimentação em {mes_label}", styles["Heading2"]))
    elements.append(_grafico_barras(
        ["Entradas", "Saídas"], [totais_mes["ENTRADA"], totais_mes["SAIDA"]],
        titulo=f"Entradas x Saídas - {mes_label}"
    ))
    elements.append(Spacer(1, 0.7 * cm))

    elements.append(Paragraph(f"Top 10 Materiais Mais Utilizados em {mes_label}", styles["Heading2"]))
    if not top_mes.empty:
        elements.append(_grafico_barras(
            top_mes["item"].tolist(), top_mes["total_saida"].tolist(),
            titulo="Consumo por item (unidades)", cor="#3E7C63"
        ))
        elements.append(Spacer(1, 0.4 * cm))
        top_data = [["Item", "Total de Saídas"]] + top_mes.values.tolist()
        t2 = Table(top_data, colWidths=[12 * cm, 4 * cm])
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E5B4C")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
        ]))
        elements.append(t2)
    else:
        elements.append(Paragraph("Nenhuma saída registrada nesse mês.", styles["Normal"]))

    elements.append(Spacer(1, 0.7 * cm))
    elements.append(Paragraph("Itens Vencidos (situação atual)", styles["Heading2"]))
    if not vencidos.empty:
        estilo_cel = styles["Normal"].clone("celula")
        estilo_cel.fontSize = 8
        estilo_cel.leading = 10
        vd = [
            [Paragraph(str(row["item_nome"]), estilo_cel), row["numero_lote"],
             row["quantidade"], row["validade"]]
            for _, row in vencidos.iterrows()
        ]
        t3 = Table([["Item", "Lote", "Quantidade", "Validade"]] + vd,
                    colWidths=[11 * cm, 3 * cm, 3 * cm, 3 * cm])
        t3.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#8B2E2E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(t3)
    else:
        elements.append(Paragraph("Nenhum item vencido.", styles["Normal"]))

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()
