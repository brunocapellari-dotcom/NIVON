# Operação do NIVON — ESQUELETO PROVISÓRIO

**Situação:** PENDENTE de versão final após merges F2, F3 e F4. Nenhum deploy ou operação real é atestado aqui.

## Antes de qualquer execução
1. Conferir SHA da `main`, PR incorporada, ambiente `producao` e aprovação de Bruno.
2. Verificar custos e quotas no projeto Google Cloud autorizado; **R$ 0 é objetivo, não limite técnico automático**.
3. Validar identidade, IAP, princípio do menor privilégio e inexistência de acesso anônimo.
4. Verificar fonte, autorização de uso, frescor, unidade, competência, publicação/coleta e se o valor é observado, programado, inferido ou estimado.
5. Não emitir relatório com número fictício ou fonte indisponível tratada como zero.

## Rotina diária — PENDENTE F2/F3/F4
- **Coleta:** consultar execução efetiva do Cloud Run Job e evidências por fonte; jobs agendados e retentativas serão descritos por F2/F4.
- **Qualidade:** conferir RAW → STAGE → CORE, proveniência e registros de quarentena quando existirem.
- **Terminal:** conferir URL HTTPS real, login IAP e resposta read-only com dados observados; testes locais não validam disponibilidade pública/privada.
- **Briefing:** conferir limite móvel de 24 h para notícias, fechamento anterior para cotações e unidade/dia das referências logísticas; não enviar se faltarem requisitos.
- **Incidentes:** registrar hora, sistema, run, SHA, erro reproduzível, alcance e responsável; nunca enviar segredos nos logs.

## Falha e recuperação — PENDENTE F2/F5
Conservar snapshot e evidências antes de rollback, usar mecanismo efetivamente disponível e autorizado; não reiniciar cargas sem verificar idempotência. Procedimento concreto de rollback, alarmes, SLAs, comandos e contatos será escrito após infraestrutura consolidada.

## Aceite do go-live
Exigir URL real acessível por identidade autorizada, IAM/IAP validado, leitura de dados reais permitidos, execução verificada do job, histórico de execução e retentativa, observabilidade, custo revisado, recuperação demonstrável e aceite explícito. **PENDENTE.**

Ver [Arquitetura](ARQUITETURA.md), [Fontes — F4](FONTES.md), [Segurança — F5](SEGURANCA.md).
