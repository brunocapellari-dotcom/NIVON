# NIVON — Preflight GCP para go-live interno

**Corte:** 25/10/2026, somente verificação de infraestrutura.

## Evidência operacional

- [Ações #40257978213](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40257978213): o painel interno foi **gravado realmente no bucket privado** `nivon-data-raw-2026`, com dois objetos em `nivon/painel-interno/revisoes/`, hash e readback. Não há URL pública.
- [Ações #40257778476](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40257778476): a leitura ANTT/SIADE no BigQuery foi **real e bem-sucedida**, com 21 anos e competência mais recente `2026-08`; o relatório registra expressamente `terminal_em_producao=false`.
- [Ações #40257929205](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40257929205): o inventário autenticado confirmou projeto `nivon-data`, bucket e dataset em `southamerica-east1`, mas retornou erro exclusivamente porque `nivon_raw.agro_fonte_stage` **não existe**.

## Correção de gate

A tabela `agro_fonte_stage` faz parte de uma trilha de **carga agro**, não do readback privado ANTT/line-up do portal. O workflow `nivon-go-live-readonly.yml` agora devolve `AUSENTE_OPCIONAL_PARA_PORTAL` e `carga_agro_stage_pronta=false` com sucesso de diagnóstico de **metadados**, sem alegar que o terminal esteja hospedado. Se a tabela existir e seu schema não corresponder, o preflight continua falhando.

**Esta alteração não cria tabelas, não consulta dados SQL, não envia nada e não habilita cobrança.**

## Gates que continuam faltando para terminal acessível

1. Confirmar conta de execução somente leitura e repositório Docker existentes no Google Cloud; atualmente o [preflight #40257778476](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40257778476) reportou ambos ausentes da configuração GitHub.
2. Autorizar explicitamente custos/revisão de orçamento e o deploy Cloud Run privado; não remover o bloqueio de `NIVON_GO_LIVE_DEPLOY_APPROVED`.
3. Publicar serviço privado via `.github/workflows/nivon-terminal-go-live.yml`, com readback de URLs/ACL e nenhum `allUsers`.
4. Conectar o portal web incorporado pela PR #276 a snapshots validados, sem liberar dados restritos a usuários anônimos.
5. Verificar dois ciclos reais consecutivos de coleta, geração e disponibilização.

Go-live técnico **parcial** existe para as séries/painel privado, mas não está comprovado como terminal web remoto em produção.
