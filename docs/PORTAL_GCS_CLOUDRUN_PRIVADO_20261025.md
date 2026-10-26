# NIVON — Portal privado consumindo Cloud Storage

## O que está implementado

O servidor WSGI agora aceita leitor de snapshot vindo do Google Cloud Storage,
sem salvar credenciais, sem liberar URL assinada e sem leitura BigQuery em
cada consulta web. Somente o objeto fixo interno/nivon/portal/v1/painel.json
do bucket nivon-data-raw-2026 é aceito. A leitura exige tamanho limitado,
SHA-256 correspondente ao metadata do objeto, geração consistente, região
southamerica-east1 e contrato interno SHADOW. Falha de rede, IAM, objeto
alterado ou payload inválido -> 503 na API. Cache positivo máximo de 60 s;
erros não reutilizam o snapshot anterior indefinidamente.

## Deploy privado preparado, não executado

O repositório agora contém Dockerfile.portal, cloudbuild.portal.yaml e
scripts/nivon_portal_cloudrun_deploy.sh. O workflow manual
portal-cloudrun-privado.yml executa build e deploy apenas na main,
quando executar_deploy=true, o projeto/bucket correspondem aos nomes
existentes e as variáveis de IAM/custos foram explicitamente aprovadas:

- NIVON_PORTAL_DEPLOY_APPROVED e NIVON_GCP_COST_REVIEWED
- NIVON_PORTAL_GCS_READ_APPROVED e NIVON_PORTAL_PRIVATE_BUCKET_REVIEWED
- NIVON_PORTAL_SERVICE_ACCOUNT e NIVON_PORTAL_ARTIFACT_REPO
- NIVON_GCP_PROVIDER, NIVON_GCP_SERVICE_ACCOUNT, NIVON_BQ_PROJECT, NIVON_GCS_BUCKET

Reutilizar uma SA **existente** com permissão storage.objects.get restrita
ao objeto/bucket apropriado e IAM run.invoker concedido somente à identidade
humana/autorizada (por exemplo, por Cloud Run Auth Proxy no terminal).
O script não concede IAM, não cria buckets nem habilita APIs. Recusa
sobrescrever serviços não identificados e bloqueia IAM com allUsers ou
allAuthenticatedUsers antes e após o deploy.

O serviço roda com min-instances=0, max-instances=1. Isso reduz custo ocioso,
mas não garante R$ 0. Cloud Build, Artifact Registry e Cloud Run podem gerar
cobrança, portanto deployment aguarda revisão e autorização financeira.

## Próximo passo real de homologação

1. A rotina de renovação BQ → GCS criada anteriormente deve passar uma
   execução autorizada com readback hash confirmado.
2. Implantar manualmente o serviço privado após aprovação IAM e custos.
3. Conferir 403/401 sem identidade, 200 com run.invoker autorizado,
   /readyz e tela carregada com dado real (não dados sintéticos).
4. Testar mudança do snapshot, prazo de cache, novo dado e falha de permissão.
5. Liberar agendamento de renovação somente após dois ciclos reais e
   evidência explícita de orçamento. Manter rótulos de dado shadow.

O sucesso do CI prova somente as rotinas offline e contrato de segurança;
**não representa serviço Cloud Run publicado, funcional ou faturamento zero**.
