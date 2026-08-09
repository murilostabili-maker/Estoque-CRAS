"""
Módulo de banco de dados para o Sistema de Controle de Estoque.
Usa SQLite (arquivo local estoque.db) - simples, sem necessidade de servidor.
"""
import sqlite3
import hashlib
import os
import csv
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "estoque.db")
SEED_CSV = os.path.join(os.path.dirname(__file__), "estoque_inicial.csv")

CATEGORIAS_PADRAO = ["Descartável", "Permanente", "EPI", "Odontológico", "Limpeza", "Escritório", "Outros"]

# Unidades de análise padronizadas para o cadastro de itens (lista suspensa).
# Baseada nas apresentações mais usadas na planilha original do CRAS.
UNIDADES_PADRAO = [
    "Unidade", "Caixa", "Pacote", "Frasco", "Par", "Litro", "Rolo",
    "Galão", "Seringa", "Bisnaga", "Sachê", "Pote", "Kit", "Kg", "Metro",
    "Outro (personalizar)",
]

DIAS_ALERTA_PADRAO = 120


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_senha(senha: str) -> str:
    return hashlib.sha256(senha.encode("utf-8")).hexdigest()


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            nome TEXT NOT NULL,
            papel TEXT NOT NULL CHECK(papel IN ('Administrador','Estoque','Consulta')),
            ativo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL,
            apresentacao TEXT,
            unidade_medida TEXT DEFAULT 'Unidade',
            categoria TEXT DEFAULT 'Outros',
            estoque_minimo INTEGER DEFAULT 5,
            dias_alerta_validade INTEGER DEFAULT 120,
            ativo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES itens(id),
            numero_lote TEXT,
            quantidade INTEGER NOT NULL DEFAULT 0,
            validade TEXT,
            nota_empenho TEXT,
            valor_unitario REAL,
            data_entrada TEXT,
            observacao TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS movimentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL CHECK(tipo IN ('ENTRADA','SAIDA','AJUSTE')),
            item_id INTEGER NOT NULL REFERENCES itens(id),
            lote_id INTEGER REFERENCES lotes(id),
            quantidade INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT,
            profissional TEXT,
            motivo TEXT,
            perda INTEGER DEFAULT 0,
            justificativa_perda TEXT,
            nota_empenho TEXT,
            valor_unitario REAL,
            observacao TEXT,
            usuario TEXT
        )
    """)

    conn.commit()

    _migrar_colunas(conn)

    # Cria usuário admin padrão se não existir nenhum usuário
    cur.execute("SELECT COUNT(*) as c FROM usuarios")
    if cur.fetchone()["c"] == 0:
        usuarios_padrao = [
            ("admin", "admin123", "Administrador(a)", "Administrador"),
            ("thereza", "estoque123", "Thereza", "Estoque"),
            ("consulta", "consulta123", "Consulta", "Consulta"),
        ]
        for u, s, n, p in usuarios_padrao:
            cur.execute(
                "INSERT INTO usuarios (username, senha_hash, nome, papel) VALUES (?,?,?,?)",
                (u, hash_senha(s), n, p),
            )
        conn.commit()

    # Semeia estoque inicial a partir do CSV extraído da planilha, apenas uma vez
    cur.execute("SELECT COUNT(*) as c FROM itens")
    if cur.fetchone()["c"] == 0 and os.path.exists(SEED_CSV):
        _seed_from_csv(conn)

    conn.close()


def _migrar_colunas(conn):
    """Adiciona colunas novas em bancos já existentes (instalações antigas),
    sem perder os dados já cadastrados."""
    cur = conn.cursor()
    colunas_existentes = {row["name"] for row in cur.execute("PRAGMA table_info(itens)")}

    if "unidade_medida" not in colunas_existentes:
        cur.execute("ALTER TABLE itens ADD COLUMN unidade_medida TEXT DEFAULT 'Unidade'")
        # tenta deduzir a unidade a partir da apresentação já cadastrada
        for row in cur.execute("SELECT id, apresentacao FROM itens").fetchall():
            cur.execute(
                "UPDATE itens SET unidade_medida = ? WHERE id = ?",
                (_deduzir_unidade(row["apresentacao"]), row["id"]),
            )

    if "dias_alerta_validade" not in colunas_existentes:
        cur.execute(
            f"ALTER TABLE itens ADD COLUMN dias_alerta_validade INTEGER DEFAULT {DIAS_ALERTA_PADRAO}"
        )
        cur.execute(
            "UPDATE itens SET dias_alerta_validade = ? WHERE dias_alerta_validade IS NULL",
            (DIAS_ALERTA_PADRAO,),
        )

    conn.commit()


def _deduzir_unidade(apresentacao: str) -> str:
    """Tenta identificar a unidade padronizada a partir de um texto livre de apresentação
    (usado na migração e na carga inicial da planilha)."""
    if not apresentacao:
        return "Unidade"
    texto = apresentacao.strip().lower()
    for unidade in UNIDADES_PADRAO[:-1]:  # ignora "Outro (personalizar)"
        base = unidade.lower().rstrip("s")  # "par" cobre "pares", "seringa" cobre "seringas"
        if texto.startswith(base):
            return unidade
    return "Outro (personalizar)"


def _parse_validade(val: str):
    """Converte MM/AAAA em uma data (último dia do mês) ou None."""
    if not val:
        return None
    val = val.strip()
    try:
        mes, ano = val.split("/")
        mes, ano = int(mes), int(ano)
        # último dia aproximado do mês (dia 28 para segurança)
        return date(ano, mes, 28).isoformat()
    except Exception:
        return None


def _seed_from_csv(conn):
    cur = conn.cursor()
    with open(SEED_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nome = row["item"].strip()
            apres = row.get("apresentacao", "Unidade").strip() or "Unidade"
            qtd = int(row.get("quantidade") or 0)
            validade = _parse_validade(row.get("validade", ""))

            cur.execute("SELECT id FROM itens WHERE nome = ?", (nome,))
            r = cur.fetchone()
            if r:
                item_id = r["id"]
            else:
                cur.execute(
                    """INSERT INTO itens (nome, apresentacao, unidade_medida, categoria,
                                           estoque_minimo, dias_alerta_validade)
                       VALUES (?,?,?,?,?,?)""",
                    (nome, apres, _deduzir_unidade(apres), "Outros", 5, DIAS_ALERTA_PADRAO),
                )
                item_id = cur.lastrowid

            cur.execute(
                """INSERT INTO lotes (item_id, quantidade, validade, data_entrada, observacao)
                   VALUES (?,?,?,?,?)""",
                (item_id, qtd, validade, date.today().isoformat(), "Carga inicial (migração da planilha)"),
            )
    conn.commit()


# ---------------------- Funções de autenticação ----------------------

def autenticar(username: str, senha: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM usuarios WHERE username = ? AND ativo = 1", (username.strip().lower(),)
    )
    row = cur.fetchone()
    conn.close()
    if row and row["senha_hash"] == hash_senha(senha):
        return dict(row)
    return None


def listar_usuarios():
    conn = get_conn()
    df = conn.execute("SELECT id, username, nome, papel, ativo FROM usuarios").fetchall()
    conn.close()
    return [dict(r) for r in df]


def criar_usuario(username, senha, nome, papel):
    conn = get_conn()
    conn.execute(
        "INSERT INTO usuarios (username, senha_hash, nome, papel) VALUES (?,?,?,?)",
        (username.strip().lower(), hash_senha(senha), nome, papel),
    )
    conn.commit()
    conn.close()


def alterar_status_usuario(user_id, ativo):
    conn = get_conn()
    conn.execute("UPDATE usuarios SET ativo=? WHERE id=?", (ativo, user_id))
    conn.commit()
    conn.close()


def redefinir_senha(user_id, nova_senha):
    conn = get_conn()
    conn.execute("UPDATE usuarios SET senha_hash=? WHERE id=?", (hash_senha(nova_senha), user_id))
    conn.commit()
    conn.close()
