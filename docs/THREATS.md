# Modelo de ameaças do laboratório

| Cenário | Controle e verificação | Limite |
| --- | --- | --- |
| Tenant informado pelo cliente | Schema não aceita tenant; credencial resolve o escopo | API keys estáticas são simplificação de laboratório |
| Corpo adulterado | HMAC cobre timestamp e bytes exatos | Segredo comprometido permite forjar mensagens |
| Replay | Janela temporal e identidade única persistente | Reenvio válido na janela pode recuperar recibo, sem reaplicar efeito |
| Mensagens concorrentes | Constraint única, transação e lock da aplicação | O banco ainda exige dimensionamento e proteção operacional |
| Evento fora de ordem | Sequência e adiamento limitado | Lacuna permanente exige análise humana; não há reparo automático de histórico |
| Entrada excessiva ou malformada | Limite do corpo, Pydantic estrito e paginação limitada | Sem rate limiting de borda ou proteção DDoS |
| Vazamento em resposta/log | Respostas excluem payload/hash; logs só têm rota, status, duração e request ID | Não colocar PII em identificadores sintéticos; infraestrutura deve redigir seus próprios logs |
| Falha após receber | Commit antes da confirmação | Disponibilidade depende do banco |
| Falha durante processamento | Estado, evento e auditoria na mesma transação | Auditoria não é WORM ou proteção contra administrador |

Não há cobrança, transferência, scoring ou decisão financeira real. Nunca usar chaves ou dados de clientes para testar. A URL de testes exige base `_test`; cada teste PostgreSQL usa schema novo com nome gerado, removido no encerramento. Um scanner sem achados não equivale a certificação de segurança.
