# NIVON — consolidação para Google Cloud único

## Decisão vinculante

A plataforma de execução do NIVON é **Google Cloud**. O GitHub mantém
exclusivamente versionamento, revisões, testes e disparos autorizados.
Vercel, Railway, Render e servidores próprios não fazem parte da arquitetura
de produção. Nenhum novo front-end separado ou função serverless fora do GCP.

## Uma aplicação, uma API, uma nuvem

- **Cloud Run privado:** serviço `nivon-terminal`, imagem
  `infra/google_cloud/Dockerfile.terminal`; acesso autenticado por IAM.
- **Interface histórica ferroviária:** `GET /` e `GET /api/v1/ferrovia`;
  leitura limitada da view atual ANTT no BigQuery, sem alegar PIT histórico.
- **Centro de Operações:** `GET /painel` e arquivos `GET /assets/*`
  servidos pelo mesmo container, usando `public/`.
- **Indicadores públicos do Banco Central:** `GET /api/mercado` no mesmo
  serviço, por `mercado_bcb_ro.py`, consultando somente códigos SGS 1 e 11
  com URL fixa, TLS e redirecionamentos bloqueados; não equivalem à PTAX oficial
  e não garantem atualização do BigQuery.
- **GCS e BigQuery:** os repositórios canônicos de dados; sem outro banco para
  essa funcionalidade. Cloud Scheduler somente após validação de um escritor
  por fonte, contas de execução, custo e testes E2E.
- **Um único deploy:** workflow `nivon-terminal-go-live.yml`,
  `scripts/deploy_terminal_privado.sh` e Cloud Build/Artifact Registry.
  Não criar novo Cloud Run paralelo para o portal.

## Legado aposentado no repositório

Removidos arquivos de configuração Vercel, app estático duplicado,
handler Node específico de Vercel e workflows/testes correspondentes.
O frontend `public/` foi preservado e é empacotado no Cloud Run.
A leitura BCB foi portada com testes equivalentes para o backend Python.

**A exclusão de configuração no GitHub NÃO desconecta a integração Git↔Vercel
nem apaga a implantação já ativa no serviço externo.** Essa desconexão
administrativa deverá ocorrer após verificação de que a URL privada GCP
funciona e de que nenhuma funcionalidade foi perdida. Não remover conta,
domínio ou dados sem pedido específico do titular.

## Homologação do corte

1. Testes HTTP com `/painel`, assets, `/api/mercado`,
   `/api/v1/ferrovia` e bloqueio de rotas arbitrárias.
2. Teste negativo sem credenciais IAM de invocação no Cloud Run;
   somente usuários autorizados acessam.
3. Execução de leitura BQ com as_of, limite de bytes, origem/competência
   e direito de exibição; classificação de dados correta.
4. Verificação de faturamento e autorização para build, deploy e runtime;
   a existência de free tier não garante custo zero.
5. Auditoria da `main` protegida, conta deployer separada da conta
   leitora e identidade WIF restrita.
6. Só após aceitação do endpoint Cloud Run em serviço privado, suspender
   automações e conexão do provedor anterior e revisar DNS, se houver.

**Estado desta mudança:** patch de repositório submetido a PR, NÃO
constitui deploy de produção, desativação externa, IAM ou homologação.
