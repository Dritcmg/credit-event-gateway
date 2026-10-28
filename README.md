# Credit Event Gateway

API de recebimento e processamento de eventos de crédito **sintéticos**, desenvolvida como projeto de portfólio de Adriano Camargo de Oliveira, com assistência de IA declarada. Demonstra Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, contratos REST, autenticação de parceiros, testes e recuperação transacional.

A hipótese de negócio é comum em integrações B2B: parceiros reenviam notificações ou entregam eventos fora de ordem. O gateway confirma o recebimento somente depois do commit e aplica cada evento em uma transação. Não concede crédito, não movimenta dinheiro e não utiliza dados pessoais reais.

## O que conferir primeiro

- [`gateway/api.py`](gateway/api.py): contrato HTTP, autorização por parceiro e limites de entrada.
- [`gateway/security.py`](gateway/security.py): HMAC-SHA256 sobre timestamp e bytes originais do corpo.
- [`gateway/service.py`](gateway/service.py): idempotência persistente, regras de transição e worker.
- [`tests/test_postgres.py`](tests/test_postgres.py): concorrência e locks com PostgreSQL real.
- [`evidence/results.json`](evidence/results.json): resultado sanitizado da execução registrada, com escopo explícito.
- [Decisões](docs/DECISIONS.md), [ameaças](docs/THREATS.md), [operação](docs/RUNBOOK.md), [assistência de IA](AI_ASSISTANCE.md).

## Escopo médio

```text
Parceiro
   │ API key + HMAC(timestamp.corpo)
   ▼
FastAPI ── commit ──► inbox PostgreSQL ──► resposta 202
   │                       │
   └── duplicata 200       ▼
                     worker SKIP LOCKED
                           │ lock por aplicação
                           ▼
                    estado + auditoria
                    em um único commit
```

Não há broker separado nem Redis obrigatório. O PostgreSQL é a fonte de verdade e oferece a fila suficiente para o escopo. Uma resposta `202` significa recebimento durável, **não** aprovação nem processamento concluído. O cliente acompanha o recibo por `GET`.

## Preparar no VS Code

Requer Python 3.12. Os comandos abaixo usam PowerShell; em Linux use `.venv/bin/python` no lugar de `.venv/Scripts/python.exe`.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/create_demo_env.py
```

A geração preserva um `.env` existente e não imprime credenciais. O arquivo é local e ignorado no Git. Ele configura um parceiro fictício e segredos aleatórios para o laboratório. Os exemplos versionados não são credenciais de produção.

Para validar regras portáveis sem Docker:

```powershell
.\.venv\Scripts\python.exe scripts/verify.py
```

Essa execução usa SQLite para API, persistência e regras. **Não valida concorrência nem locks do PostgreSQL.** A evidência declara esse limite. O CI executa também a suíte PostgreSQL real.

## Executar com PostgreSQL

```powershell
docker compose up --build -d
```

API disponível somente no loopback `http://127.0.0.1:8002`; documentação em `/docs`. O Compose sobe banco, aplica migrations pela API e inicia o worker após a API estar pronta. Para depurar localmente, suba só o banco, carregue o `.env`, rode `alembic upgrade head` e use as configurações de `.vscode/launch.json`.

Os testes PostgreSQL exigem uma base isolada com nome terminado em `_test`. O Compose cria `credit_gateway_test` no primeiro volume inicializado; em um volume antigo confira sua existência antes de testar. Nunca aponte testes a uma base de produção.

```powershell
# Carregue a URL de testes local sem imprimir sua senha.
$env:TEST_DATABASE_URL = 'postgresql+psycopg://gateway:SENHA_LOCAL@127.0.0.1:54362/credit_gateway_test'
.\.venv\Scripts\python.exe scripts/verify.py --postgres
```

Cada teste PostgreSQL cria um schema `test_gateway_<uuid>` e remove somente esse schema no encerramento. Não limpa tabelas de uma base compartilhada.

## Contrato de integração

`POST /v1/events` exige `X-Api-Key`, `X-Webhook-Timestamp` (segundos Unix) e `X-Webhook-Signature`. O parceiro não envia `tenant_id`: seu escopo é resolvido pela credencial configurada no servidor.

```json
{
  "event_id": "synthetic-event-1",
  "application_id": "synthetic-application-1",
  "sequence": 1,
  "event_type": "submitted",
  "occurred_at": "2026-10-28T12:00:00Z"
}
```

Assinatura: `v1=` + hexadecimal de `HMAC-SHA256(secret, timestamp_ascii + b'.' + body_original)`. O remetente deve assinar exatamente os bytes que transmite. A janela padrão é de cinco minutos para o passado ou futuro. `occurred_at` descreve o evento de negócio; a janela verifica o timestamp de transporte.

| Operação | Resultado |
| --- | --- |
| Novo `(tenant, event_id)` | `202`, recibo persistido com status `queued` |
| Reenvio do mesmo evento sem alteração semântica | `200`, mesmo recibo e estado atual |
| Mesmo identificador com outro payload | `409`, sem sobrescrever o original |
| Credencial/assinatura inválida ou fora da janela | `401` |
| Campo desconhecido, tipo incorreto, data sem fuso | `422`, sem eco do payload |
| Corpo maior que 64 KiB | `413` |
| Recibo/aplicação de outro tenant | `404` |
| Banco indisponível | `503`, resposta genérica |

`GET /v1/events` aceita `limit=1..100` e `offset=0..10000`; ambos são limitados. `GET /v1/events/{receipt_id}` consulta um recibo; `GET /v1/applications/{application_id}` consulta a projeção do parceiro. Consultas exigem API key e não exigem HMAC.

## Estados e eventos fora de ordem

Transições sintéticas: `pending → submitted → approved → funded` ou `submitted → declined`. `declined` e `funded` são terminais. Cada evento precisa da próxima sequência inteira da aplicação.

Se a sequência 2 chegar antes da 1, o worker adia a 2 sem avançar o estado, aplica a 1 quando recebida e tenta a 2 após o intervalo. Lacunas persistentes são rejeitadas após tentativas limitadas. Transições impossíveis e sequências antigas geram rejeição auditada; não há reprocessamento infinito nem aprovação inferida por IA.

A auditoria de conclusão é gravada na mesma transação da mudança de estado e do recibo. Não é uma trilha imutável contra administradores do banco. Uma falha antes do commit mantém o evento pendente; o worker seguinte pode retomá-lo.

## Testes e CI

A suíte cobre HMAC, janela temporal, adulteração do corpo, schema, limites, isolamento de tenant, idempotência, reinício da aplicação, ordens de chegada, estados terminais, rollback antes do commit e logs sem corpo/credenciais. Os testes PostgreSQL cobrem entregas concorrentes, conflito simultâneo, `SKIP LOCKED`, lock por aplicação e constraints reais.

```powershell
.\.venv\Scripts\python.exe -m pytest -m 'not postgres' -q
.\.venv\Scripts\python.exe -m pytest -m postgres -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip_audit -r requirements.txt
```

O workflow valida migrations, lint, formato, testes com PostgreSQL e dependências; publica somente `evidence/results.json`. Logs brutos e JUnit permanecem em `artifacts/`, ignorado, porque falhas de infraestrutura podem revelar configuração. O TestClient usa a dependência de desenvolvimento `httpx2` suportada pela versão atual do Starlette. Um teste ASGI separado usa `httpx` para verificar saúde enquanto uma gravação SQL está bloqueada; a operação síncrona é executada no threadpool.

O worker tolera falhas consecutivas de banco com backoff limitado (1, 2, 4, 8 segundos na configuração padrão). Ao esgotar cinco tentativas, registra apenas o código operacional e termina com saída 1. Não imprime exceções, credenciais ou payloads. SIGTERM e Ctrl+C permitem encerrar; um supervisor de implantação decide se e quando reiniciar depois da exaustão. Não há retry infinito nem movimentação externa em duplicidade.

## Contexto e limites

O projeto foi escolhido para demonstrar competências pedidas em uma vaga Python júnior no setor de crédito. A [byx descreve APIs e módulos para integrar a cadeia de crédito](https://byx.com.br/). Isso sustenta a relevância do tema, **não** demonstra que a empresa tenha falhas de webhook ou utilize esta arquitetura. Este repositório é independente, não tem vínculo ou endosso da byx e não é um desafio oficial da empresa.

Este laboratório não implementa crédito real, Open Finance, verificações de identidade, conformidade regulatória, IAM gerenciado, retenção legal nem uma operação de produção. API keys e HMAC exigem rotação e armazenamento adequados antes de qualquer uso real. Rate limiting na borda, TLS, monitoramento contínuo e revisão de segurança são responsabilidades não implementadas aqui. PostgreSQL é a referência para concorrência; SQLite serve apenas à verificação portátil.

Licença MIT. Leia [AI_ASSISTANCE.md](AI_ASSISTANCE.md) para compreender a autoria assistida e a finalidade de aprendizagem e validação externa.
