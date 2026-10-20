# Runbook de infraestrutura NIVON — pré-implantação

**Situação:** não há ambiente operacional confirmado. Este é um procedimento
de homologação. A execução atual permitida é apenas offline.

## Pré-voo da release

1. Registrar SHA único da release integrada e resultado de testes no mesmo SHA.
2. Ler `infra/inventory.v1.json` e rodar `PYTHONPATH=src python -m nivon.infra_preflight`.
3. Rodar `PYTHONPATH=src python -m nivon.infra_preflight --require-live`:
   deve retornar **3** enquanto não houver infraestrutura homologada.
4. Verificar proveniência/licença de software, modelo e de cada fonte por operação.
5. Não usar as Actions para coletar informação operacional nem guardar dados
   privados: CI usa fixtures sintéticas e artefatos efêmeros.
6. Confirmar conta OCI, home region, quotas ARM e espaço livre, risco de
   reclaim de máquina ociosa, billing/alerts e política de gastos. Se algum
   item for desconhecido, abortar provisionamento.

## Pré-voo cloud quando autorizado

- Criar usuário/compartment da unidade NIVON com IAM mínimo e registro de
  custo segregado; sem assumir recursos já existentes na Holding.
- VM ARM64 Always Free somente se elegível, protegida e em quota; nenhuma
  opção paga substituta sem autorização expressa.
- Sistema atualizado, credenciais SSH por chave, firewall, acesso de
  administração restrito, portas de banco fechadas, backup remoto segregado.
- Nunca copiar `.env`, tokens, chaves, banco ou arquivo de terceiros ao Git.
- Reservar armazenamento com folga de crescimento, WAL, staging e backup.
- Validar Docker/Compose e arquitetura ARM64 sem instalar serviços externos.
- Até homologação, apenas job offline:
  `docker compose -f infra/compose.yaml run --rm nivon-preflight`.
- Não usar `docker compose up -d` como receita de deploy: não há definição
  do runtime operacional nesta branch.

## Plano de falhas

| Evento | Resposta segura | Prova necessária |
|---|---|---|
| Fonte indisponível | SOURCE_LAG, não inventar 0 nem reemitir dado como atual | log redigido, timestamps |
| Duplicata ou retry | lease/idempotência; quarentena sem dupla contagem | replay comparado |
| Falha de disco/corrupção | interromper escrita, isolar, restaurar snapshot íntegro | teste de restore, ponto de recuperação |
| Perda da VM gratuita | recriar infraestrutura, recuperar dados remotos e revalidar | restore em host diferente |
| Quota excedida | parar jobs opcionais e notificar operador; nunca ampliar gasto | medição e orçamento |
| Token exposto | revogar/rotacionar, bloquear chamadas, investigar logs | revogação confirmada |
| Modelo degradado | modo SHADOW, baseline/cenário, auditoria | backtest e erro recente |
| Envio incerto WhatsApp | consultar status assinado; jamais reenviar cegamente | ID de remessa e ACK |
| Fonte sem direito comercial | continuar OFF, bloquear publicação | ficha de licença |

## Backups, retenção e RPO/RTO

RPO e RTO ainda **não foram contratados nem medidos**. Proposta a ensaiar:
backup consistente diário de estado; cópia de arquivos brutos e derivados por
edição; retenção local curta e remoto segregado. Definir frequência real após
dimensionar perda aceitável, evolução das séries e quotas. Testar, pelo menos,
restauração numa VM/contêiner separado sem segredos de produção.

Existe rotina local `nivon.pacote_recuperacao`, mas não criptografa nem
copia para nuvem. Nenhuma evidência de recuperação remota é reivindicada.

## Critérios mínimos para abrir produção

- Git release única + teste de regressão + revisão independente.
- Direitos, amostras reais, qualidade, datas, cobertura e histórico por fonte.
- Persistência durável, backup remoto criptografado e restore separado.
- Controles de acesso, TLS, segredos, monitoramento e orçamento real.
- Modelos preditivos fora da amostra aprovados antes de previsão pública.
- Fluxo ponta a ponta por produto; WhatsApp somente com consentimento,
  template e provedor habilitado.
- Aprovação de operação explícita, documentada por humano responsável.

**Qualquer item faltante: permanecer em homologação, não inventar status.**
