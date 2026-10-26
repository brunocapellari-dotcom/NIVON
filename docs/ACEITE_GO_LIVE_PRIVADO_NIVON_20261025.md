# NIVON — Checklist de liberação do primeiro terminal privado (P0)

**Corte:** 25/10/2026 (Mato Grosso). Esta página descreve o go-live **interno** e a evidência necessária para declará-lo; não pressupõe que o serviço já esteja publicado.

## O que já existe, sem refazer projetos

1. **Dados ANTT/SIADE reais**: histórico 2006–agosto/2026 lido de `nivon-data.nivon_raw.vw_antt_ferrovia_od_atual`, com competência, TU declaradas e ressalvas. Não confundir com multimodal concluído.
2. **Painel gerencial HTML/JSON privado no GCS**, com revisões imutáveis verificadas. GCS privado não equivale a site acessível via navegador.
3. **`nivon-terminal`**: servidor web, API read-only, Dockerfile e script de build/deploy privado presentes em `main`, mas implantação Cloud Run e acesso com IAM não confirmados no diagnóstico atual.
4. **PTAX BCB em leitura real**: o PR #305 validou GET oficial read-only em CI, mas não persistiu a série nem a colocou no terminal web. Não apresentá-la como fonte integrada ao serviço.

## Caminho mais curto para o primeiro acesso

| Gate | Aceite verificável | Situação atual |
|---|---|---|
| P0.1 Identidade e infraestrutura | WIF de Actions + API GCP existente + Docker repo e service account existentes/permitidos | **PENDENTE DE CONFERÊNCIA**: diagnóstico inicial apontou correções; descoberta read-only de candidatos foi incorporada à `main` |
| P0.2 Custos e IAM | Responsável confirma orçamento, permissões mínimas de build/Cloud Run/BigQuery e invocador privado | **NÃO APROVADO NESTA PR** |
| P0.3 Deploy controlado | Workflow manual na `main`, `confirmar_deploy=true`, e variáveis `NIVON_GO_LIVE_DEPLOY_APPROVED=true` e `NIVON_GCP_COST_REVIEWED=true` após a aprovação | **NÃO EXECUTADO** |
| P0.4 Smoke autenticado | 3 GET reais: `/healthz`, `/api/v1/ferrovia` e `/`, com ID token, TLS, headers privados, dados ANTT e competência verificáveis | **AUTOMAÇÃO PREPARADA; PENDENTE DO DEPLOY REAL** |
| P0.5 Acesso humano | Usuário autorizado com `roles/run.invoker`, 403 para identidades não autorizadas, interface útil no navegador | **PENDENTE** |
| P0.6 Operação | Dois ciclos reais, logs/alertas de falha, custo observado, ausência de divulgação de fontes restritas | **PENDENTE** |

**Nunca anunciar go-live aprovado apenas por CI verde, metadados GCP confirmados ou publicação de arquivo privado.**

## Uma sequência operacional no GitHub

1. Abrir Actions → **NIVON - Terminal privado Go Live** → diagnóstico na `main`. O Job Summary deve mostrar cada recurso com estado e **ação de correção**. O código da ação é padronizado, sem nomes de credenciais.
2. Validar os candidatos de Artifact Registry Docker e service account existentes exibidos pelo diagnóstico novo da `main`. Selecionar somente recursos efetivamente apropriados e confirmar IAM mínimo; não criar recursos pagos silenciosamente.
3. Um administrador aprova custos/limites e as variáveis de deploy. Ativar a execução manual com `confirmar_deploy=true`. O deploy executa `gcloud builds submit` e `gcloud run deploy` para o serviço **privado** `nivon-terminal`.
4. Após deploy, a etapa `Homologar autenticacao e resposta real do terminal privado` usa a identidade WIF autorizada para invocar o serviço com token em memória, inspecionar as três rotas e produzir somente metadados e SHA256. Caso falte `roles/run.invoker`, o smoke falha e o job não é apresentado como homologado. **Não conceder IAM automaticamente**.
5. O administrador concede o papel de invocação estritamente ao operador, valida o acesso de navegador, configura monitoramento básico e revisa custos medidos. Registre a URL apenas em canal privado; o workflow não a envia ao público.

## Controles de orçamento e privacidade

O script de deploy existente configura `min-instances=0`, `max-instances=1`, `cpu=1`, `memory=512Mi`, `concurrency=8` e `no-allow-unauthenticated`. BigQuery usa limite de 250 MB por query e cache de 15 min por instância; **esses limites não asseguram custo zero**. Cloud Build, registry, rede e consultas devem integrar a revisão de custos antes do primeiro deploy.

O smoke real é **opt-in** pela execução manual e não é chamado automaticamente em PRs. Execute com ID token injetado no ambiente; a CLI sem `--executar` não abre rede. A saída não inclui preços, TU totais, identidade, dados de origem/destino, SQL ou token.

## Pós-go-live em paralelo

Após disponibilizar o terminal privado de ANTT/SIADE, adicionar em lotes verificáveis: PTAX com persistência canônica, CONAB/IMEA/CEPEA quando coletor contínuo e direitos estiverem prontos, ANP diesel, ANTAQ/hidrovias e line-ups auditados. Manter fretes anunciados sem médias municipais, AIS inferido e probabilidades de frete sem backtest real fora da liberação inicial.

O objetivo de início é entregar **um produto interno acessível com dados reais e fontes explícitas**, não declarar todo o projeto NIVON finalizado.
