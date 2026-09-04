"""
Módulo de banco de dados para o Sistema de Controle de Estoque.

Suporta dois modos, escolhidos automaticamente:

- **Banco externo (Postgres)**: usado sempre que a variável de ambiente
  DATABASE_URL ou o segredo st.secrets["DATABASE_URL"] estiver configurado.
  Esse é o modo recomendado em produção (Streamlit Cloud), porque os dados
  ficam guardados fora do container do app - não se perdem quando o app
  reinicia, dorme ou é redeployado.

- **SQLite local (arquivo data/estoque.db)**: usado automaticamente quando
  nenhum banco externo está configurado. Útil para rodar o projeto na sua
  própria máquina sem precisar de um banco Postgres.

O restante do sistema (queries.py, app.py) não precisa saber qual dos dois
está em uso: as duas conexões oferecem a mesma "API" (métodos .execute(),
.executemany(), .commit(), .close(), cursores com .fetchone()/.fetchall(),
linhas acessíveis como dicionário e cur.lastrowid após um INSERT).
"""
import sqlite3
import hashlib
import os
import re
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


# ---------------------- Detecção do backend (Postgres externo x SQLite local) ----------------------

def _get_database_url():
    """Procura a string de conexão do banco externo, nessa ordem:
    1) variável de ambiente DATABASE_URL (útil para testes locais)
    2) st.secrets["DATABASE_URL"] (usado no Streamlit Cloud)
    Se nenhuma existir, retorna None e o sistema usa SQLite local.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        import streamlit as st
        return st.secrets.get("DATABASE_URL")
    except Exception:
        return None


DATABASE_URL = _get_database_url()
USANDO_POSTGRES = bool(DATABASE_URL)


# ---------------------- Camada de compatibilidade para Postgres ----------------------
# Faz o psycopg2 se comportar como o sqlite3 nos pontos que queries.py e db.py usam:
# placeholders "?", conn.execute()/executemany() como atalho, linhas tipo dicionário,
# e cur.lastrowid após um INSERT.

if USANDO_POSTGRES:
    import psycopg2
    import psycopg2.extras

    _INSERT_RE = re.compile(r"^\s*INSERT\s+INTO", re.IGNORECASE)

    def _traduzir(query: str) -> str:
        """Troca os placeholders '?' (estilo SQLite) por '%s' (estilo psycopg2)."""
        return query.replace("?", "%s")

    class _PGCursor:
        def __init__(self, cur):
            self._cur = cur
            self.lastrowid = None

        def execute(self, query, params=()):
            query_traduzida = _traduzir(query)
            eh_insert = bool(_INSERT_RE.match(query)) and "RETURNING" not in query.upper()
            if eh_insert:
                query_traduzida = query_traduzida.rstrip().rstrip(";") + " RETURNING id"
            self._cur.execute(query_traduzida, params)
            if eh_insert:
                row = self._cur.fetchone()
                self.lastrowid = row["id"] if row else None
            return self

        def executemany(self, query, seq_of_params):
            self._cur.executemany(_traduzir(query), seq_of_params)
            return self

        def fetchone(self):
            return self._cur.fetchone()

        def fetchall(self):
            return self._cur.fetchall()

        def __iter__(self):
            return iter(self._cur)

    class _PGConnection:
        def __init__(self, conn):
            self._conn = conn

        def cursor(self):
            return _PGCursor(self._conn.cursor())

        def execute(self, query, params=()):
            # Atalho equivalente ao sqlite3.Connection.execute(): abre um cursor,
            # executa e devolve o cursor (para permitir .fetchone()/.fetchall() em cadeia).
            cur = self.cursor()
            cur.execute(query, params)
            return cur

        def executemany(self, query, seq_of_params):
            cur = self.cursor()
            cur.executemany(query, seq_of_params)
            return cur

        def commit(self):
            self._conn.commit()

        def close(self):
            self._conn.close()

    def get_conn():
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return _PGConnection(conn)

else:
    def get_conn():
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def read_sql(query, params=None):
    """Executa uma consulta SELECT e devolve um pandas DataFrame, funcionando
    igual nos dois backends (evita depender de pd.read_sql_query, que não
    reconhece a conexão psycopg2 diretamente)."""
    import pandas as pd
    conn = get_conn()
    try:
        cur = conn.execute(query, params or ())
        linhas = cur.fetchall()
        return pd.DataFrame([dict(r) for r in linhas])
    finally:
        conn.close()


def hash_senha(senha: str) -> str:
    return hashlib.sha256(senha.encode("utf-8")).hexdigest()


# ---------------------- Criação e migração do esquema ----------------------

def _sql_criar_tabelas():
    """Monta o SQL de criação das tabelas, ajustando a coluna de auto-incremento
    conforme o backend (SERIAL no Postgres, AUTOINCREMENT no SQLite)."""
    pk = "SERIAL PRIMARY KEY" if USANDO_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

    return [
        f"""
        CREATE TABLE IF NOT EXISTS usuarios (
            id {pk},
            username TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            nome TEXT NOT NULL,
            papel TEXT NOT NULL CHECK(papel IN ('Administrador','Estoque','Consulta')),
            ativo INTEGER NOT NULL DEFAULT 1
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS itens (
            id {pk},
            nome TEXT UNIQUE NOT NULL,
            apresentacao TEXT,
            unidade_medida TEXT DEFAULT 'Unidade',
            categoria TEXT DEFAULT 'Outros',
            estoque_minimo INTEGER DEFAULT 5,
            dias_alerta_validade INTEGER DEFAULT 120,
            ativo INTEGER NOT NULL DEFAULT 1
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS lotes (
            id {pk},
            item_id INTEGER NOT NULL REFERENCES itens(id),
            numero_lote TEXT,
            quantidade INTEGER NOT NULL DEFAULT 0,
            validade TEXT,
            nota_empenho TEXT,
            valor_unitario REAL,
            data_entrada TEXT,
            observacao TEXT
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS movimentos (
            id {pk},
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
        """,
    ]


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    for stmt in _sql_criar_tabelas():
        cur.execute(stmt)

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
    # (só roda se a tabela de itens estiver totalmente vazia - ver reimportar_estoque_csv()
    # para forçar uma atualização depois que o banco já foi criado)
    cur.execute("SELECT COUNT(*) as c FROM itens")
    if cur.fetchone()["c"] == 0 and os.path.exists(SEED_CSV):
        _seed_from_csv(conn)

    conn.close()


def _colunas_existentes_itens(conn):
    """Lista os nomes das colunas já existentes na tabela itens, em qualquer
    um dos dois backends."""
    cur = conn.cursor()
    if USANDO_POSTGRES:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'itens'"
        )
        return {row["column_name"] for row in cur.fetchall()}
    else:
        return {row["name"] for row in cur.execute("PRAGMA table_info(itens)")}


def _migrar_colunas(conn):
    """Adiciona colunas novas em bancos já existentes (instalações antigas),
    sem perder os dados já cadastrados."""
    cur = conn.cursor()
    colunas_existentes = _colunas_existentes_itens(conn)

    if "unidade_medida" not in colunas_existentes:
        cur.execute("ALTER TABLE itens ADD COLUMN unidade_medida TEXT DEFAULT 'Unidade'")
        # tenta deduzir a unidade a partir da apresentação já cadastrada
        cur.execute("SELECT id, apresentacao FROM itens")
        for row in cur.fetchall():
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


# ---------------------- Reimportação / reset do estoque inicial ----------------------

def contar_registros():
    """Retorna quantos itens, lotes e movimentos existem hoje no banco -
    usado para mostrar um resumo antes de um reset."""
    conn = get_conn()
    cur = conn.cursor()
    itens = cur.execute("SELECT COUNT(*) as c FROM itens").fetchone()["c"]
    lotes = cur.execute("SELECT COUNT(*) as c FROM lotes").fetchone()["c"]
    movimentos = cur.execute("SELECT COUNT(*) as c FROM movimentos").fetchone()["c"]
    conn.close()
    return {"itens": itens, "lotes": lotes, "movimentos": movimentos}


def reimportar_estoque_csv(modo="atualizar"):
    """Recarrega o estoque a partir do estoque_inicial.csv, mesmo que o banco
    já tenha itens cadastrados.

    modo="atualizar": mantém itens, lotes e movimentações já existentes.
        Para cada item do CSV:
          - se o item ainda não existe, cria ele normalmente;
          - se o item já existe, adiciona um novo lote com a diferença entre
            a quantidade do CSV e a quantidade já cadastrada nos lotes atuais
            (registrado como um lote de "Ajuste de importação"), sem apagar
            nada do que já estava lá. Se a diferença for zero, não faz nada.
        NÃO apaga entradas/saídas já registradas manualmente no app.

    modo="substituir": apaga TODOS os itens, lotes e movimentações e recria
        o estoque do zero, exatamente como veio do CSV. Os usuários (login)
        não são afetados. Use apenas se ainda não tiver movimentações
        importantes registradas no sistema.

    Retorna um dicionário com um resumo do que foi feito.
    """
    if not os.path.exists(SEED_CSV):
        raise FileNotFoundError(f"Arquivo não encontrado: {SEED_CSV}")

    conn = get_conn()
    cur = conn.cursor()

    resumo = {"itens_criados": 0, "itens_ajustados": 0, "itens_sem_alteracao": 0}

    if modo == "substituir":
        cur.execute("DELETE FROM movimentos")
        cur.execute("DELETE FROM lotes")
        cur.execute("DELETE FROM itens")
        conn.commit()
        _seed_from_csv(conn)
        with open(SEED_CSV, encoding="utf-8") as f:
            resumo["itens_criados"] = sum(1 for _ in csv.DictReader(f))
        conn.close()
        return resumo

    # modo == "atualizar"
    with open(SEED_CSV, encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    # soma as quantidades do CSV por item (pode haver várias linhas/lotes do mesmo item)
    totais_csv = {}
    apresentacoes_csv = {}
    for row in reader:
        nome = row["item"].strip()
        qtd = int(row.get("quantidade") or 0)
        totais_csv[nome] = totais_csv.get(nome, 0) + qtd
        apresentacoes_csv[nome] = row.get("apresentacao", "Unidade").strip() or "Unidade"

    for nome, qtd_csv in totais_csv.items():
        cur.execute("SELECT id FROM itens WHERE nome = ?", (nome,))
        r = cur.fetchone()

        if not r:
            apres = apresentacoes_csv[nome]
            cur.execute(
                """INSERT INTO itens (nome, apresentacao, unidade_medida, categoria,
                                       estoque_minimo, dias_alerta_validade)
                   VALUES (?,?,?,?,?,?)""",
                (nome, apres, _deduzir_unidade(apres), "Outros", 5, DIAS_ALERTA_PADRAO),
            )
            item_id = cur.lastrowid
            cur.execute(
                """INSERT INTO lotes (item_id, quantidade, data_entrada, observacao)
                   VALUES (?,?,?,?)""",
                (item_id, qtd_csv, date.today().isoformat(), "Item novo importado da planilha"),
            )
            resumo["itens_criados"] += 1
            continue

        item_id = r["id"]
        qtd_atual = cur.execute(
            "SELECT COALESCE(SUM(quantidade),0) as s FROM lotes WHERE item_id = ?", (item_id,)
        ).fetchone()["s"]

        diferenca = qtd_csv - qtd_atual
        if diferenca == 0:
            resumo["itens_sem_alteracao"] += 1
            continue

        cur.execute(
            """INSERT INTO lotes (item_id, quantidade, data_entrada, observacao)
               VALUES (?,?,?,?)""",
            (item_id, diferenca, date.today().isoformat(),
             f"Ajuste de importação da planilha (saldo anterior: {qtd_atual}, planilha: {qtd_csv})"),
        )
        cur.execute(
            """INSERT INTO movimentos (tipo, item_id, quantidade, data, observacao, usuario)
               VALUES ('AJUSTE', ?, ?, ?, ?, ?)""",
            (item_id, diferenca, date.today().isoformat(),
             f"Ajuste automático via reimportação de planilha (de {qtd_atual} para {qtd_csv})",
             "sistema"),
        )
        resumo["itens_ajustados"] += 1

    conn.commit()
    conn.close()
    return resumo


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
    linhas = conn.execute("SELECT id, username, nome, papel, ativo FROM usuarios").fetchall()
    conn.close()
    return [dict(r) for r in linhas]


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
