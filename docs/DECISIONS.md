# Decisões de arquitetura

## ADR 001 Inbox no PostgreSQL

**Status:** aceita. **Data:** 28/10/2026.

**Contexto:** o fluxo precisa reconhecer reenvios e sobreviver ao reinício da API, sem criar uma plataforma distribuída maior que o problema.

**Decisão:** gravar evento e identidade única `(tenant_id, event_id)` antes do `202`. Mesmo payload devolve o recibo original; alteração conflita. O hash usa JSON canônico validado, enquanto HMAC usa os bytes originais do transporte. Campos desconhecidos são recusados.

**Consequências:** um banco basta para o estudo e a idempotência atravessa processos. O banco também concentra a fila e requer capacidade/monitoramento. Redis e SQS foram descartados neste escopo para evitar duplicar uma fonte de verdade; não há promessa de escala ilimitada.

## ADR 002 Transação curta por evento

**Contexto:** workers paralelos podem disputar eventos ou alterar a mesma aplicação.

**Decisão:** selecionar evento com `FOR UPDATE SKIP LOCKED`, criar a projeção se ausente e bloquear a linha da aplicação. Processamento, estado e auditoria terminam no mesmo commit. Não chamar serviços remotos dentro dessa transação.

**Consequências:** uma falha antes do commit reverte todas as alterações. Sequências antigas são rejeitadas; sequências futuras são adiadas com limite. Não há efeitos externos neste estudo, portanto não é necessário outbox. Se futuramente houver envio remoto, será necessário considerar outbox e deduplicação no consumidor.

## ADR 003 Escopo de parceiro resolvido no servidor

**Contexto:** uma integração não pode escolher a empresa de outro cliente no JSON.

**Decisão:** uma API key configurada resolve tenant e segredo HMAC. Assinatura inclui timestamp; comparação usa `compare_digest`. O corpo é limitado a 64 KiB. GETs sempre filtram pelo tenant; falha de acesso retorna 404.

**Consequências:** os testes demonstram uma fronteira verificável. O laboratório não substitui um provedor de identidade, rotação, cofre de segredos, autorização granular, controles de rede ou TLS.

## ADR 004 Evidência pelo comportamento

**Decisão:** usar SQLite temporário para testes portáveis e PostgreSQL real para concorrência/locks/constraints. Publicar resumo sanitizado com impressão digital das fontes, escopo e resultado. Não transformar teste SQLite em alegação de correção PostgreSQL, nem quantidade de testes em senioridade.

**Consequências:** validação local simples é possível; a verificação completa depende de PostgreSQL local ou do CI. Dependências Python são pinadas; imagens Docker seguem major fixo e precisam de revisão de digest em uma release real.
