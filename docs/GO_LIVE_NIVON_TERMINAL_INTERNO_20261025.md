# NIVON — Go-live interno: primeira versão operacional

**Meta:** abrir um terminal de consulta real, protegido, conectado ao BigQuery, sem esperar todos os módulos do Bloomberg do Agro. Este é um **primeiro recorte operacional interno**, não a homologação de todo o NIVON.

## O que entra

Interface responsiva em português, marca NIVON agro, com dados oficiais históricos ANTT de 2025:

- Ferrovia: origem das estações Rondonópolis, Itiquira e Alto Araguaia, toneladas úteis anuais; não confundir com fluxo de caminhões ou embarque marítimo.
- Rodovia: recorte top-16 RGI do Anuário TRC 2025; sem identificação de produto. Não equivale ao transporte rodoviário total do Brasil.
- Hidrovia: exibida somente como **pendente de homologação da fonte oficial**. Sem números de terceiro apresentados como oficiais.
- Identificação explícita de ano-base, fonte, escopo e ausência de tempo real. Sem transbordos inventados e **sem somar modais**.
- Consultas somente leitura e SQL fixo; teto de 50 MB faturáveis por consulta, cache em memória de 10 minutos, 1 instância máxima, nenhum scheduler.
- Em queda do BigQuery, mostra indisponível/HTTP 503, **nunca** valores sintéticos, cache defasado indefinido ou zero.

## Implantação com segurança

A aplicação é um serviço Cloud Run PRIVADO com autenticação obrigatória pelo IAM Google. A aplicação **não faz login próprio** e **não pode** ser exposta anonimamente. A imagem é construída pelo Cloud Build usando repositório Artifact Registry **existente**. O workflow `.github/workflows/nivon-terminal-golive.yml` nunca publica por push/PR; o deploy só roda por `workflow_dispatch` + `publicar=true` + variáveis de aprovação. Nenhuma IAM binding, API, repo Docker ou novo banco é criado pelo script.

**Variáveis em GitHub Settings → Secrets and variables → Actions → Variables:**

| Nome | Valor esperado |
|---|---|
| NIVON_BQ_PROJECT | `nivon-data` (preexistente) |
| NIVON_BQ_DATASET | `nivon_raw` (preexistente) |
| NIVON_GCP_PROVIDER | Provedor Workload Identity Federation já configurado |
| NIVON_GCP_SERVICE_ACCOUNT | Identidade federada já autorizada para build/deploy |
| NIVON_TERMINAL_ARTIFACT_REPO | Nome de repositório Artifact Registry Docker **existente** na região southamerica-east1 |
| NIVON_TERMINAL_READONLY_SA | Service account **existente** de runtime com **somente** `roles/bigquery.jobUser` no projeto e leitura restrita (`roles/bigquery.dataViewer`) às views/tabelas necessárias |
| NIVON_TERMINAL_DEPLOY_APPROVED | `true` somente após aprovar implantação |
| NIVON_GCP_COST_REVIEWED | `true` somente após revisar cotas, orçamento e preços GCP |

O deployer federado precisará das permissões existentes para build, repositório Artifact Registry e Cloud Run; o workflow **não amplia permissões**. O runtime tem que ser distinto do coletor/escritor. Sem essas dependências a execução é bloqueada, não substituída por serviço aberto ao público.

**Uma ação para publicar, após os gates:** GitHub → Actions → **NIVON - Go-live terminal privado** → Run workflow → branch `main` → marcar `publicar` → Run workflow. Não há PowerShell, chaves JSON nem instalação de SDK no notebook para esta publicação.

**Para consultar em navegador protegido:** uma identidade autorizada precisa de `roles/run.invoker` no serviço. Cloud Run com IAM privado não equivale a um login web pronto. A forma de acesso técnico é usar proxy autenticado do `gcloud run services proxy nivon-terminal --project nivon-data --region southamerica-east1 --port 8080` e acessar `http://localhost:8080`. Para acesso web direto com login amigável será necessário configurar camada de autenticação/roteamento aprovada, sem publicar a URL diretamente e sem custo inesperado.

## Gates objetivos antes de anunciar go-live

1. CI: testes de HTTP, header de segurança, cache, SQL restrito, tratamento de erro e recortes oficiais aprovados.
2. GCP: dataset e views existentes em southamerica-east1; service account com acesso somente leitura.
3. Cloud Build: imagem do SHA atual; Cloud Run com `--no-allow-unauthenticated`, mínimo zero e máximo uma instância.
4. Smoke em produção por identidade autorizada: `/healthz` 200 (saúde do processo), `/api/resumo` 200 **com dados conciliados**; ambos têm significados distintos.
5. Evidência: commit/tag de imagem, execução do Actions, URL privada, observabilidade, orçamento e registro de acesso.
6. **Não publicar** se o BigQuery retornar divergências de revisão ou 503.

## Escopo futuro, sem bloquear esta versão

Integração de 2026 com dados recentes, carga automática CEPEA/IMEA/CONAB, linha de navios, ANTAQ primária, MDF-e completo, previsões quantitativas, fretes e modelo de pressão dos corredores. Cada módulo só entra no terminal quando sua ingestão, freshness, evidência, licença e contratos de acesso forem validados.

**Status documental ao criar este PR:** código de serviço + pipeline de deploy privado. **Não afirmar que a URL Cloud Run já existe até execução confirmada.** As permissões/custos são condições explícitas, e limites técnicos não garantem R$ 0.
