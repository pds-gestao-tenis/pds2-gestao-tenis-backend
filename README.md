# Clube de Tênis — API

## Executar com Docker Compose

Requer Docker Desktop/Engine com Compose v2 e acesso à internet para baixar imagens e pacotes. Na raiz do projeto, em PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build -d app
```

O Compose inicia o PostgreSQL, executa `alembic upgrade head` no serviço `migrate` e, após a migration terminar, inicia a API.

- API: `http://localhost:8000/api/v1`.
- Swagger UI: `http://localhost:8000/docs`.
- ReDoc: `http://localhost:8000/redoc`.
- Contrato OpenAPI: `http://localhost:8000/openapi.json`.
- Saúde: `http://localhost:8000/up` — verifica se a aplicação responde, sem consultar o banco.

O PostgreSQL fica disponível em `localhost:5433`, com as credenciais do `.env`. Dentro do Docker, a API usa o host `db`. O volume `postgres_data` preserva os dados ao parar os containers. As credenciais de exemplo destinam-se a desenvolvimento local.

```powershell
docker compose logs -f app migrate
docker compose stop
```

O Dockerfile inclui as dependências de desenvolvimento para executar os testes. As versões permitidas estão em `pyproject.toml`; esta entrega ainda não inclui um lock das dependências resolvidas.

## Executar com Python local

Requer Python 3.13+ e PostgreSQL acessível nas credenciais configuradas no `.env`. O Python 3.14 também é aceito, desde que as versões resolvidas das dependências ofereçam suporte.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --no-proxy-headers
```

Para usar somente o PostgreSQL pelo Docker: `docker compose up -d db`. A aplicação monta a URL de conexão a partir das variáveis `DB_*`, incluindo o escape correto de caracteres especiais na senha.

## Notificações por e-mail (US15-US18)

A API avisa por e-mail, pelo [Resend](https://resend.com):

| Quando | Quem recebe |
|---|---|
| Reserva confirmada (no pedido ou quando a fila de espera libera a vaga) | Quem reservou |
| Jogador incluído em uma reserva | O jogador convidado |
| Reserva cancelada (por quem reservou, pela administração ou por bloqueio da quadra) | Os demais envolvidos |
| Reserva remarcada | Os demais envolvidos |
| Lembrete, `REMINDER_HOURS_BEFORE` horas antes (padrão 24) | Quem reservou e quem não recusou a presença |

O texto é montado durante a requisição e o envio acontece depois da resposta: uma falha no Resend
fica no log e não afeta a reserva. Sem `RESEND_API_KEY`, os e-mails só aparecem no log.

Os lembretes saem pela rota interna `POST /api/v1/internal/reminders`, que exige o cabeçalho
`X-Cron-Token` igual a `CRON_TOKEN` e envia um único lembrete por horário (remarcar gera um novo). O
workflow `.github/workflows/reminders.yml` chama a rota de hora em hora, das 07h às 22h de Brasília
(assim a API dorme de madrugada e poupa as horas gratuitas do Render); ele precisa do secret
`CRON_TOKEN` e, se a API não estiver no endereço padrão, da variável `API_URL`. Em forks, workflows
agendados precisam ser habilitados na aba Actions.

| Variável | Uso |
|---|---|
| `RESEND_API_KEY` | Chave do Resend |
| `MAIL_FROM` | Remetente, de um domínio verificado no Resend |
| `APP_URL` | Endereço do frontend, para os links dos e-mails |
| `REMINDER_HOURS_BEFORE` | Antecedência do lembrete, em horas |
| `CRON_TOKEN` | Token da rota de lembretes |

## Taxas e pagamentos (US19-US22)

Cada taxa pertence a um cadastro de membro (US03). O jogador vê as taxas do membro que tem o
mesmo e-mail da conta dele. "Atrasada" = pendente com vencimento antes de hoje, no fuso do clube.

| Endpoint | Quem | Descrição |
|---|---|---|
| `POST /fees` | Admin | Lança uma taxa: `member_id`, `description`, `amount`, `due_date` |
| `GET /fees` | Admin | Lista por vencimento; filtros `member_id`, `status`, `overdue=true` |
| `PATCH /fees/{id}` | Admin | Corrige descrição, valor ou vencimento (só pendentes) |
| `DELETE /fees/{id}` | Admin | Exclui (só pendentes) |
| `POST /fees/{id}/payment` | Admin | Registra pagamento recebido: `method` (`cash`, `pix`, `card`, `transfer`) e `paid_at` opcional |
| `GET /fees/pending-members` | Admin | Membros com pendências: quantidade, total, atrasadas e vencimento mais antigo |
| `GET /fees/mine` | Jogador | Taxas pagas e pendentes da própria conta, com totais |
| `POST /fees/mine/{id}/pay` | Jogador | Paga uma taxa própria por `pix` ou `card` |

O pagamento pelo sistema ainda não usa um provedor de pagamentos: ele é aprovado na hora e fica
registrado como `paid_via: "online"`. A integração com um gateway entra em `PayOwnFeeHandler`
(`app/handlers/fees.py`).

## Perfil de jogo e parceiros (US23-US24)

| Endpoint | Descrição |
|---|---|
| `GET /players/me/profile` | Nível e disponibilidade da própria conta |
| `PUT /players/me/profile` | `skill_level` (`beginner`, `intermediate`, `advanced`, `competitive` ou `null`) e `availability`: lista de `{weekday: 0-6, period: morning\|afternoon\|evening}` (0 = segunda-feira) |
| `GET /players/partners` | Jogadores de nível igual ou vizinho; com disponibilidade informada, só os que têm horário em comum, mais horários em comum primeiro. Sem nível informado: `409` |

A lista de parceiros mostra nome, nível e horários em comum, nunca o e-mail. Para convidar um
parceiro (US25), quem organiza inclui o jogador na reserva com `PATCH /bookings/{id}`
(`player_ids`), e o convidado recebe o convite por e-mail.

## Administração da agenda (US26-US30)

- **Agenda centralizada e histórico (US26, US29):** `GET /bookings` devolve todas as reservas
  para administradores, com filtros `court_id`, `status`, `starts_from`, `starts_to` e
  `scope=upcoming|past`.
- **Cancelar ou alterar (US27):** `POST /bookings/{id}/cancel` e `PATCH /bookings/{id}` aceitam
  administradores; os envolvidos são avisados por e-mail.
- **Bloquear horários (US28):** `POST /courts/{id}/maintenance` aceita `kind`: `maintenance`
  (padrão) ou `event` (torneio, aula, evento do clube). Os dois bloqueiam a agenda.
- **Indicadores (US30):** `GET /reports/occupancy?from=AAAA-MM-DD&to=AAAA-MM-DD` (admin, até 92
  dias; padrão: últimos 30). Ocupação = horas reservadas confirmadas / horas disponíveis
  (07:00-22:00 menos bloqueios), no total, por quadra, por dia da semana e por hora.

## Organização

```text
app/
  controllers/    Rotas, entrada HTTP e respostas
  schemas/        Validação Pydantic e contratos públicos
  data/           Dados tipados do caso de uso
  handlers/       Caso de uso de cadastro
  repositories/   Contrato de persistência e implementação SQLAlchemy
  domain/         Entidades e exceções sem dependência de framework
  db/             Modelo SQLAlchemy e base declarativa
  core/           Configuração e limite de requisições
  dependencies.py Injeção de sessões, repository e hasher
  main.py         Aplicação, ciclo de vida e tratamento de erros
migrations/       Histórico Alembic
tests/
  unit/           Handler e limite de requisições
  api/            Contrato HTTP e validação, com handler substituído
  integration/    Cadastro e restrições no PostgreSQL real
```

Fluxo: controller → handler → contrato repository → SQLAlchemy → PostgreSQL. O handler recebe o hasher por injeção; o repository recebe apenas o hash da senha. As rotas de cadastro são síncronas e executadas pelo FastAPI no pool de threads, compatível com o driver SQLAlchemy síncrono.

As migrations são explícitas: não há criação automática de tabelas durante a inicialização da API. Para criar uma próxima migration:

```powershell
alembic revision --autogenerate -m "descricao"
alembic upgrade head
```

## Referências

- [FastAPI — dependências](https://fastapi.tiangolo.com/tutorial/dependencies/)
- [SQLAlchemy — PostgreSQL e psycopg](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg)
- [Alembic — migrations](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [pwdlib — hash de senhas](https://frankie567.github.io/pwdlib/)
