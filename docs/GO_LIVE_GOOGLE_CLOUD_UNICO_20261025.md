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

## Integração funcional do terminal com o snapshot privado

Além de `/api/v1/ferrovia` (consulta direta na view ANTT no BigQuery), o mesmo
serviço `nivon-terminal` passa a servir o **painel real já implementado**
em `/portal` e `/api/v1/painel`, com os assets do projeto existente
`src/nivon/portal_static`. Não haverá uma segunda implantação de frontend.

O segundo endpoint lê exclusivamente
`gs://nivon-data-raw-2026/interno/nivon/portal/v1/painel.json`, produzido
pela rotina `scripts/atualizar_snapshot_portal_gcp.py`. Essa rotina já
consulta dados ANTT, programação Imbituba e PortWatch; nenhum conteúdo é
inventado pelo serviço web. O leitor novo exige:
- bucket em `southamerica-east1` com *Public Access Prevention enforced*;
- geração consistente, arquivo de até 2 MB, metadados `nivon_modo` e
  SHA-256 verificado sobre o conteúdo bruto;
- estrutura `nivon.portal.interno.v1`, `publicavel=false`,
  `go_live_publico=false` e ao menos um indicador real;
- snapshot de no máximo 24 horas, com tolerância de relógio de 5 minutos;
- execução IAM privada no Cloud Run, sem conceder acesso anônimo.

A API retorna HTTP **503** quando o snapshot está ausente, desatualizado
ou incorreto, sem publicar dados artificiais nem erros de credenciais.
`/readyz` testa leitura real do snapshot; `/healthz` testa somente
processo. O leitor usa cache de até cinco minutos e não executa SQL;
consultas GCS podem ter custo, embora pequenas.

O script de deploy `scripts/deploy_terminal_privado.sh` agora recusa
build e publicação caso esse snapshot não esteja comprovadamente recente
e contenha ferrovia ANTT mais ao menos uma fonte marítima, com dois
indicadores reais. A mera existência do HTML ou o sucesso do CI não bastam.

**Ordem para um go-live operacional legítimo:** (1) revisão dos gates
econômicos já existentes, (2) execução autorizada de
`.github/workflows/portal-interno-gcp.yml` com readback e hash,
(3) garantir à service account de execução do terminal permissão
de leitura limitada ao objeto GCS e leitura da view ANTT, (4) execução
manual protegida de `.github/workflows/nivon-terminal-go-live.yml`,
(5) testar autenticadamente `/portal`, `/readyz`,
`/api/v1/painel` e `/api/v1/ferrovia` no Cloud Run.

A prova anterior de publicação em `nivon/painel-interno` é **outro
contrato de snapshot**, e não deve ser copiada para
`interno/nivon/portal/v1/painel.json` sem passar pelo transformador
canônico. A presença desse objeto específico e as permissões reais
de runtime ainda precisam ser comprovadas. A integração de código não
comprova um serviço acessível.
