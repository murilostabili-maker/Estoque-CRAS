"""
Funções utilitárias de formatação (datas em padrão brasileiro dd/mm/aaaa).
Usadas em todas as abas para manter a exibição de datas consistente.
"""
import pandas as pd

FORMATO_DATA_INPUT = "DD/MM/YYYY"  # usado em todos os st.date_input do app

MESES_PT = {
    1: "Jan", 2: "Fev", 3: "Mar", 4: "Abr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Ago", 9: "Set", 10: "Out", 11: "Nov", 12: "Dez",
}


def fmt_data_br(valor) -> str:
    """Converte uma data (string ISO 'AAAA-MM-DD', date ou datetime) para 'dd/mm/aaaa'."""
    if valor is None or valor == "" or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    try:
        return pd.to_datetime(valor).strftime("%d/%m/%Y")
    except Exception:
        return str(valor)


def fmt_data_col(df: pd.DataFrame, *colunas: str) -> pd.DataFrame:
    """Retorna cópia do DataFrame com as colunas de data informadas formatadas em dd/mm/aaaa."""
    df = df.copy()
    for col in colunas:
        if col in df.columns:
            df[col] = df[col].apply(fmt_data_br)
    return df


def fmt_mes_br(ano_mes: str) -> str:
    """Converte 'AAAA-MM' (ou 'AAAA-WW' semana ISO) para um rótulo amigável, ex: 'Jan/2026'."""
    if not ano_mes:
        return ""
    try:
        ano, mes = ano_mes.split("-")
        return f"{MESES_PT[int(mes)]}/{ano}"
    except Exception:
        return ano_mes


def fmt_semana_br(ano_semana: str) -> str:
    """Converte 'AAAA-WW' (semana ISO, formato %Y-%W) para o rótulo 'dd/mm - Sem WW/AAAA'."""
    if not ano_semana:
        return ""
    try:
        ano, semana = ano_semana.split("-")
        # segunda-feira da semana (formato %Y-%W usa domingo como base; %w=1 = segunda)
        inicio = pd.to_datetime(f"{ano}-{semana}-1", format="%Y-%W-%w")
        return f"{inicio.strftime('%d/%m')} (Sem {int(semana):02d}/{ano})"
    except Exception:
        return ano_semana


def mes_atual_iso() -> str:
    return pd.Timestamp.today().strftime("%Y-%m")


def fmt_texto_col(df: pd.DataFrame, *colunas: str, default: str = "-") -> pd.DataFrame:
    """Substitui valores nulos/NaN por um texto padrão em colunas de texto (ex: número de lote),
    evitando que apareça 'nan' ou 'None' nas tabelas e nos relatórios exportados."""
    df = df.copy()
    for col in colunas:
        if col in df.columns:
            df[col] = df[col].fillna(default).replace({"": default, "None": default})
    return df
