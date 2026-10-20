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

## Controle de jobs e modo degradado

- O módulo `nivon.infra_job_ledger` guarda apenas metadados dos ensaios
  `TEST_SYNTHETIC_*`, em arquivo SQLite cuja pasta pertence ao operador e
  não é acessível por grupo/terceiros (0700). Banco 0600, `synchronous=FULL`
  e WAL para arquivo local; não usar NFS sem validação de locking.
- Um job é reservado numa transação `BEGIN IMMEDIATE`; o lease não concede
  autorização de usar uma fonte. Chave/dia e hash diferentes provocam bloqueio.
- Um job `RUNNING` que perdeu lease não pode ser repetido automaticamente:
  torna-se `UNCERTAIN`. Um operador deverá reconciliar evidências externas
  no módulo futuro antes de autorizar qualquer nova tentativa.
- O comando `PYTHONPATH=src python -m nivon.infra_smoke` exerce somente
  cálculo determinístico sintético em memória; nunca toca serviços reais.
  `--db` aponta para armazenamento local privado quando desejado.
- Se houver falta de banco/backup, bloquear cadências; **não** mover
  automaticamente o banco a volume efêmero de contêiner.
- Cron/systemd/cloud scheduler continuam NÃO configurados. Não criar
  secretamente loops infinitos nem execução silenciosa em CI.

## Ferramentas de diagnóstico sem rede

```sh
PYTHONPATH=src python -m nivon.infra_health
PYTHONPATH=src python -m nivon.infra_oci_quota
```

Ambos operam com arquivos de configuração locais; o primeiro pode abrir
um ledger sintético **somente leitura** com `--ledger`. Não
confundir o status `CANDIDATO_COMPATIVEL_SOZINHO` da proposta OCI
com elegibilidade da tenancy. Qualquer tentativa de homologação antes
de evidenciar home region, recursos totais ocupados, backup, IAM e
segregação continua bloqueada. Nunca colar chaves e tokens no repositório.
