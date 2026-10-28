# Operação e diagnóstico

## Preparação e validação

1. Instalar as dependências pinadas em ambiente virtual próprio.
2. Gerar `.env` local; preservar arquivos existentes e não imprimir credenciais em logs.
3. Subir banco isolado e aplicar `alembic upgrade head`.
4. Validar `/health/live` e `/health/ready`.
5. Validar evento sintético e consultar seu recibo. `queued` significa aguardando worker.
6. Executar `scripts/verify.py --postgres` em base `_test` e revisar o resumo público.

O Compose mantém as portas no loopback. API e worker compartilham o banco; o worker não precisa de porta HTTP. A API aplica migrations antes de ficar saudável; o worker deve aguardar a prontidão. Não promover somente porque o build passou.

## Eventos pendentes ou rejeitados

- `queued` com tentativas e `available_at` futuro: aguarda o predecessor; conferir a ordem do parceiro.
- `rejected / sequence_gap`: predecessor não chegou dentro das tentativas; reconciliar com a fonte antes de qualquer reparo autorizado.
- `rejected / stale_sequence`: outro evento já avançou aquela sequência; revisar identificadores e origem.
- `rejected / invalid_transition`: o evento não cabe no estado atual; não modificar silenciosamente o histórico.
- `503`: verificar banco e configuração; resposta externa omite detalhes internos.
- `worker_database_retry`: banco falhou; há backoff limitado e o evento não foi confirmado como processado.
- `worker_failure_budget_exhausted`: após cinco falhas consecutivas o processo sai com código 1. Investigar conexão e saúde; só então autorizar reinício pelo supervisor. O orçamento é configurável com `--max-failures` (1 a 10). Uma operação bem-sucedida zera as falhas consecutivas.

Não há endpoint administrativo de replay. Um reparo exigiria novo fluxo com autorização, evidência e preservação da auditoria; isso é uma evolução deliberada, não uma instrução para alterar tabelas em produção.

## Encerramento e recuperação

`docker compose stop` para apenas os serviços deste projeto e preserva volume. Não usar limpeza global ou exclusão de volumes como rotina. Ao reiniciar, eventos com transação não concluída continuam `queued`; eventos finalizados conservam seu resultado. Backups e restauração completa de desastre não foram exercitados neste estudo.

SIGTERM sinaliza encerramento ao worker e interrompe a espera de backoff. Uma transação em andamento termina ou encontra os timeouts configurados do banco antes de o ciclo parar. Ctrl+C encerra o processo com liberação do pool. A API não mantém uma gravação SQL síncrona no event loop; usa threadpool, com teste de saúde concorrente para proteger essa fronteira.

Migrations não devem ser revertidas sem análise de dados. O downgrade incluído remove tabelas e é destrutivo; não representa um rollback seguro de operação. Em uma implantação real, definir artefato anterior conhecido, compatibilidade de schema, sinais de promoção e responsável pela recuperação.

## Leituras para entrevista

Explique por que `202` é diferente de aprovação, por que HMAC não substitui idempotência, por que o tenant não é aceito no payload e como um lock por aplicação difere de um lock por mensagem. Mostre o teste de falha antes do commit e os testes concorrentes de PostgreSQL. A evidência publicada descreve a revisão efetivamente executada, não uma certificação de prontidão para produção.
