"""
Importação direta da planilha mensal de estoque (.xlsx) para dentro do sistema.

Diferente da reimportação simples via estoque_inicial.csv (que só ajusta o saldo
final de cada item), este módulo lê a aba do mês escolhido na planilha original
e registra as ENTRADAS e SAÍDAS de cada lote como movimentações reais - por
isso elas aparecem corretamente nos gráficos do Dashboard (Entradas x Saídas
por mês, Ranking de consumo, Evolução do estoque) e no Histórico.
"""
import re
import unicodedata
from datetime import date, datetime
import openpyxl

from db import get_conn, _parse_validade, _deduzir_unidade, DIAS_ALERTA_PADRAO

MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _sem_acento(txt):
    nfkd = unicodedata.normalize("NFKD", txt)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _extrair_validade_raw(val):
    """Normaliza a célula de validade para o formato texto 'MM/AAAA', esteja
    ela guardada como texto ou como uma data de verdade do Excel (algumas
    linhas da planilha vêm assim, por formatação inconsistente da célula -
    tratar isso como 'sem validade' juntaria lotes diferentes em um só)."""
    if val is None:
        return ""
    if isinstance(val, (date, datetime)):
        return f"{val.month:02d}/{val.year}"
    if isinstance(val, str):
        return val.strip()
    return ""


def _parse_nome_aba(nome):
    """Tenta extrair (ano, mes) do nome de uma aba como 'Setembro 2026'.
    Devolve None se o nome não seguir esse padrão (assim, abas extras que a
    planilha venha a ter - um resumo, por exemplo - são ignoradas)."""
    m = re.match(r"\s*([A-Za-zÀ-ÿ]+)\s+(\d{4})\s*$", nome.strip())
    if not m:
        return None
    mes_nome = _sem_acento(m.group(1)).lower()
    ano = int(m.group(2))
    mes = MESES_PT.get(mes_nome)
    if not mes:
        return None
    return (ano, mes)


def listar_meses_da_planilha(arquivo):
    """Lê os nomes das abas de um arquivo .xlsx e devolve uma lista de
    (nome_aba, ano, mes), da mais recente para a mais antiga."""
    wb = openpyxl.load_workbook(arquivo, data_only=True, read_only=True)
    meses = []
    for nome_aba in wb.sheetnames:
        info = _parse_nome_aba(nome_aba)
        if info:
            ano, mes = info
            meses.append((nome_aba, ano, mes))
    wb.close()
    meses.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return meses


def _limpar_nome_item(valor):
    """Junta quebras de linha internas e remove espaços duplicados - o mesmo
    tipo de problema que já corrigimos manualmente em planilhas anteriores."""
    nome = str(valor).strip()
    nome = " ".join(nome.splitlines())
    nome = " ".join(nome.split())
    return nome


def _ler_linhas_aba(arquivo, nome_aba):
    wb = openpyxl.load_workbook(arquivo, data_only=True)
    ws = wb[nome_aba]
    linhas = []
    for row in ws.iter_rows(values_only=True):
        if len(row) < 6:
            continue
        item, apres, saldo_ini, entrada, saida, saldo_fim = row[0], row[1], row[2], row[3], row[4], row[5]
        val = row[6] if len(row) > 6 else None
        if not item:
            continue
        # Algumas abas têm uma linha de cabeçalho (ITEM, APRESENTAÇÃO, SALDO...)
        # dentro da própria área de dados - pula essa linha silenciosamente.
        try:
            saldo_ini_num = int(saldo_ini) if saldo_ini else 0
            entrada_num = int(entrada) if entrada else 0
            saida_num = int(saida) if saida else 0
            saldo_fim_num = int(saldo_fim) if saldo_fim else 0
        except (TypeError, ValueError):
            continue
        linhas.append({
            "item": _limpar_nome_item(item),
            "apresentacao": (apres or "Unidade").strip() if isinstance(apres, str) else "Unidade",
            "saldo_inicial": saldo_ini_num,
            "entrada": entrada_num,
            "saida": saida_num,
            "saldo_final": saldo_fim_num,
            "validade_raw": _extrair_validade_raw(val),
        })
    wb.close()
    return linhas


def importar_mes(arquivo, nome_aba, usuario="admin"):
    """
    Lê a aba indicada do arquivo .xlsx e, para cada item/lote da planilha:
    - cria o item se for a primeira vez que ele aparece no sistema;
    - localiza o lote correspondente pela validade (ou cria um novo lote,
      se for a primeira vez que essa validade aparece para esse item);
    - ajusta a quantidade do lote para o saldo final que está na planilha;
    - registra a entrada e a saída da planilha como movimentações reais,
      para que contem nos gráficos do Dashboard, no Histórico e nos
      Relatórios (diferente da simples reimportação de CSV, que só ajustava
      o saldo sem deixar rastro de movimentação).

    Como a planilha não tem a data exata de cada entrada/saída dentro do mês,
    todas as movimentações desse mês são registradas no dia 1º do mês de
    referência - isso não afeta nenhuma das telas atuais, que agrupam por
    mês, mas significa que a visão "Consumo por Item" semanal não vai
    refletir a semana exata dentro do mês para dados importados assim.

    Retorna um resumo do que foi feito, incluindo avisos quando o saldo
    inicial da planilha não batia com o saldo que já estava no sistema
    (sinal de que algo mudou por fora da planilha entre as duas datas).
    """
    linhas = _ler_linhas_aba(arquivo, nome_aba)
    info_mes = _parse_nome_aba(nome_aba)
    if not info_mes:
        raise ValueError(f"Não foi possível identificar o mês/ano a partir do nome da aba '{nome_aba}'.")
    ano, mes = info_mes
    data_mov = date(ano, mes, 1).isoformat()

    conn = get_conn()
    cur = conn.cursor()

    resumo = {
        "mes_label": nome_aba,
        "itens_novos": [],
        "lotes_criados": 0,
        "lotes_atualizados": 0,
        "lotes_sem_alteracao": 0,
        "total_entradas": 0,
        "total_saidas": 0,
        "avisos": [],
    }

    itens_na_planilha = set()
    lotes_tocados = set()

    for linha in linhas:
        nome = linha["item"]
        cur.execute("SELECT id FROM itens WHERE nome = ?", (nome,))
        r = cur.fetchone()

        if not r:
            cur.execute(
                """INSERT INTO itens (nome, apresentacao, unidade_medida, categoria,
                                       estoque_minimo, dias_alerta_validade)
                   VALUES (?,?,?,?,?,?)""",
                (nome, linha["apresentacao"], _deduzir_unidade(linha["apresentacao"]),
                 "Outros", 5, DIAS_ALERTA_PADRAO),
            )
            item_id = cur.lastrowid
            resumo["itens_novos"].append(nome)
        else:
            item_id = r["id"]

        itens_na_planilha.add(item_id)

        validade_iso = _parse_validade(linha["validade_raw"])
        if validade_iso and int(validade_iso[:4]) < 2024:
            resumo["avisos"].append(
                f"{nome}: a validade lida da planilha foi '{linha['validade_raw']}', que parece "
                f"implausível (ano muito antigo) — pode ser um erro de formatação da célula na "
                f"planilha original. Confira esse item manualmente depois de importar."
            )

        cur.execute("SELECT id, quantidade, validade FROM lotes WHERE item_id = ?", (item_id,))
        lotes_existentes = cur.fetchall()
        lote_match = next((l for l in lotes_existentes if l["validade"] == validade_iso), None)

        if lote_match is None:
            cur.execute(
                """INSERT INTO lotes (item_id, quantidade, validade, data_entrada, observacao)
                   VALUES (?,?,?,?,?)""",
                (item_id, linha["saldo_final"], validade_iso, data_mov,
                 f"Importado da planilha ({nome_aba})"),
            )
            lote_id = cur.lastrowid
            resumo["lotes_criados"] += 1
        else:
            lote_id = lote_match["id"]
            saldo_atual = lote_match["quantidade"]
            if saldo_atual != linha["saldo_inicial"]:
                resumo["avisos"].append(
                    f"{nome} (validade: {linha['validade_raw'] or 'sem validade'}) — o saldo no "
                    f"sistema era {saldo_atual}, mas a planilha esperava {linha['saldo_inicial']} "
                    f"no início de {nome_aba}. O saldo final da planilha foi aplicado mesmo assim."
                )
            cur.execute("UPDATE lotes SET quantidade = ? WHERE id = ?",
                        (linha["saldo_final"], lote_id))
            if linha["entrada"] > 0 or linha["saida"] > 0:
                resumo["lotes_atualizados"] += 1
            else:
                resumo["lotes_sem_alteracao"] += 1

        lotes_tocados.add(lote_id)

        if linha["entrada"] > 0:
            cur.execute(
                """INSERT INTO movimentos (tipo, item_id, lote_id, quantidade, data,
                                            observacao, usuario)
                   VALUES ('ENTRADA', ?, ?, ?, ?, ?, ?)""",
                (item_id, lote_id, linha["entrada"], data_mov,
                 f"Importado da planilha ({nome_aba})", usuario),
            )
            resumo["total_entradas"] += linha["entrada"]

        if linha["saida"] > 0:
            cur.execute(
                """INSERT INTO movimentos (tipo, item_id, lote_id, quantidade, data,
                                            setor, profissional, motivo, usuario)
                   VALUES ('SAIDA', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_id, lote_id, linha["saida"], data_mov,
                 "Não informado (importado da planilha)",
                 "Não informado (importado da planilha)",
                 f"Importado da planilha ({nome_aba})", usuario),
            )
            resumo["total_saidas"] += linha["saida"]

    # Avisa sobre lotes que já existiam no sistema, de itens que apareceram
    # nesta planilha, mas que nenhuma linha do mês referenciou (mesma validade
    # batendo) - o saldo desses lotes continua sendo somado no total do item,
    # mas pode já não refletir a realidade (item todo consumido, batch
    # descartado, ou a planilha simplesmente parou de rastrear aquela validade).
    for item_id in itens_na_planilha:
        cur.execute(
            "SELECT nome FROM itens WHERE id = ?", (item_id,)
        )
        nome_item = cur.fetchone()["nome"]
        cur.execute(
            "SELECT id, quantidade, validade FROM lotes WHERE item_id = ? AND quantidade > 0",
            (item_id,),
        )
        for lote in cur.fetchall():
            if lote["id"] not in lotes_tocados:
                resumo["avisos"].append(
                    f"{nome_item} (validade: {lote['validade'] or 'sem validade'}) — tem {lote['quantidade']} "
                    f"unidade(s) no sistema de uma importação anterior, mas nenhuma linha de "
                    f"{nome_aba} bateu com esse lote (pode ser que a validade tenha sido "
                    f"digitada diferente, ou que esse saldo já não exista de verdade). Esse "
                    f"saldo NÃO foi alterado — confira manualmente se ele ainda é válido."
                )

    conn.commit()
    conn.close()
    return resumo
