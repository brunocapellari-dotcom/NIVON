# NIVON — implantação oficial exclusivamente no Google Cloud

Decisão operacional de 25/10/2026: **Vercel deixa de ser destino de go-live e deixa de fazer parte do caminho crítico do NIVON**. O projeto web antigo não é apagado por este PR; ações destrutivas/alterações de conta exigem decisão separada. Não lançar novas interfaces ou deploys Vercel.

## Caminho único, já presente na main

- Serviço privado **Cloud Run**: `nivon-terminal`, `southamerica-east1`, sem acesso anônimo, com `min-instances=0` e `max-instances=1`.
- Fonte inicial **ANTT/SIADE**, lida da view existente `nivon-data.nivon_raw.vw_antt_ferrovia_od_atual` via cliente BigQuery. Só leitura. Não inferir transbordo realizado nem interpretar revisão atual como série bitemporal.
- Container existente `infra/google_cloud/Dockerfile.terminal`, `Cloud Build` e Artifact Registry existente.
- `scripts/deploy_terminal_privado.sh` só opera via GitHub Actions manual na main, com aprovação explícita de deploy e revisão de custos. Não cria IAM, service account, registry, APIs, Scheduler ou bucket.

## Diagnóstico de prontidão automático e somente leitura

A workflow `NIVON - Terminal privado Go Live` executa, após os testes, uma etapa `diagnostico-metadados` para commits da `main` e disparos manuais (não para PRs), desde que a identidade WIF existente esteja configurada.

`src/nivon/diagnostico_terminal_cloudrun.py` confere apenas metadados:
- APIs Cloud Run, Cloud Build e Artifact Registry habilitadas;
- repositório Docker existente em São Paulo;
- service account existente e não desabilitada;
- dataset e view ANTT com região/tipo corretos;
- serviço `nivon-terminal` existente ou ausente, e política de invocação privada quando existente.

O resultado no `Job Summary` separa `CONFIRMADO`, `AUSENTE`, `NAO_CONFIGURADO`, `SEM_PERMISSAO`, `DIVERGENTE` e `INDETERMINADO`. Não faz SQL, build, deploy, alteração de IAM ou APIs; não concede autorização para gastos. WIF de metadados não é prova de permissões de escrita ou execução.

## Depois que todos os metadados estiverem conformes

Homologar IAM mínimo da implantação, contas/custos e consulta BQ. Execução manual no workflow existente com `confirmar_deploy=true` e os gates `NIVON_GO_LIVE_DEPLOY_APPROVED` e `NIVON_GCP_COST_REVIEWED` explicitamente autorizados.

Somente declarar `GO-LIVE INTERNO` após o job de deploy, resposta autenticada real do serviço, dados lidos da view e custo efetivamente controlado. A primeira versão não precisa aguardar CEPEA/IMEA/CONAB/Argentina/meteorologia/marítimo/fretes para começar, mas não pode anunciá-los como funcionalidades finalizadas.

## Operação sem o notebook ligado
Google Cloud executa o runtime. GitHub faz CI e pode acionar o deploy manual. O computador é terminal de supervisão. Neon e Vercel não são dependências do go-live; o legado não deve ser usado para coletar ou publicar dados novos.
