# 📦 Sistema de Controle de Estoque — CRAS

Aplicativo em Streamlit desenvolvido a partir do checklist de levantamento de requisitos
e da planilha de estoque atual (dados de Junho/2026 já carregados como estoque inicial).

## O que o sistema já entrega

- **Dashboard**: itens cadastrados, quantidade total, itens vencidos/a vencer, estoque baixo,
  ranking de consumo, entradas x saídas por mês, evolução do estoque.
- **Estoque atual**: saldo por item (somando todos os lotes), filtro por categoria e busca,
  detalhamento por lote (validade controlada por lote, como pedido no checklist).
- **Cadastro de itens**: nome livre (não precisa ser igual à planilha), apresentação/unidade
  variável por item, categoria (Descartável, Permanente, EPI, Odontológico, Limpeza,
  Escritório, Outros — editável no código) e estoque mínimo para alerta.
- **Entrada de materiais**: item, quantidade, data, validade, lote, nota de empenho, valor,
  observação.
- **Saída de materiais**: item, quantidade, setor, profissional, motivo, e campo específico
  para marcar e justificar perdas. A baixa é feita automaticamente pelo lote que vence
  primeiro (FEFO), já que o controle de lote é só por validade.
- **Histórico**: todas as movimentações, com filtro por período, tipo e item; exportável
  em Excel.
- **Alertas de validade**: itens vencidos e próximos do vencimento (120 dias, conforme
  combinado). Ao vencer, o sistema apenas mostra o alerta — a baixa/descarte formal é
  feita como uma saída normal com motivo "Descarte".
- **Relatórios**: exportação em Excel (estoque atual + lotes) e PDF (resumo mensal com
  indicadores, ranking de consumo e itens vencidos).
- **Configurações / usuários**: 3 níveis de acesso (Administrador, Estoque, Consulta),
  criação de usuários, ativar/desativar e redefinir senha. Cada pessoa tem seu próprio
  login, como combinado (4 pessoas usarão o sistema).

## Usuários de demonstração (altere as senhas após o primeiro acesso)

| Usuário    | Senha         | Papel          |
|------------|---------------|----------------|
| admin      | admin123      | Administrador  |
| thereza    | estoque123    | Estoque        |
| consulta   | consulta123   | Consulta       |

- **Administrador**: acesso total, inclusive gestão de usuários.
- **Estoque**: cadastra itens e registra entradas/saídas (papel da Thereza no dia a dia).
- **Consulta**: só visualiza dashboard, estoque, histórico, alertas e relatórios.

## Como rodar

1. Tenha o Python 3.10+ instalado.
2. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```
3. Rode o aplicativo:
   ```bash
   streamlit run app.py
   ```
4. O navegador abrirá automaticamente em `http://localhost:8501`.

Na primeira execução, o sistema cria o arquivo `data/estoque.db` (SQLite) e já carrega
automaticamente **todos os itens e saldos da última planilha (Junho/2026)** como estoque
inicial — não é preciso digitar tudo de novo. As entradas/saídas registradas depois disso
ficam guardadas nesse mesmo arquivo, entre uma sessão e outra.

## Pontos que ficaram em aberto no checklist (para validar com a Thereza)

- **Correção de diferenças de inventário**: a pergunta ficou sem resposta no checklist.
  Hoje, ajustes podem ser feitos como uma saída com motivo "Ajuste de inventário" — se
  quiser um fluxo dedicado, é uma tela pequena para adicionar depois.
- **Categorias**: usei uma lista inicial (Descartável, Permanente, EPI, Odontológico,
  Limpeza, Escritório, Outros) já que os itens vieram sem categoria da planilha. Todos
  entraram como "Outros" — vale um mutirão rápido de reclassificação pela Thereza na tela
  de Cadastro de Itens.
- **Estoque mínimo por item**: veio um valor padrão (5) para todos os itens migrados,
  já que a planilha não tinha essa informação. Pode ser ajustado item a item.

## Estrutura dos arquivos

```
app.py                → interface (telas) do Streamlit
db.py                 → conexão com o banco e autenticação
queries.py            → regras de negócio (itens, lotes, movimentações, dashboard)
reports.py            → geração dos relatórios Excel/PDF
estoque_inicial.csv   → estoque extraído da planilha (usado só na primeira execução)
data/estoque.db       → banco de dados (criado automaticamente)
```
