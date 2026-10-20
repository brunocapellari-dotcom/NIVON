# NIVON — Arquitetura operacional e plano de implantação na nuvem

**Data-base:** 20/10/2026. **Estado:** engenharia de infraestrutura organizada
em branch isolada; nenhum recurso de nuvem provisionado ou auditado nesta
entrega. Objetivo: operação permanente sem notebook, R$ 0 enquanto a
capacidade real da conta e as quotas gratuitas o permitirem.

## 1. Decisão de arquitetura

**Candidato:** Oracle Cloud Infrastructure (OCI) Always Free, Ubuntu/Oracle
Linux ARM64 em VM Ampere A1, sujeito a disponibilidade regional e quota da
conta. Não adquirir instâncias pagas como fallback automático. Evitar
Kubernetes, serviços gerenciados com cobrança e duas bases concorrentes
antes de existir operação que necessite dessa complexidade.

**Uma máquina candidata, serviços logicamente isolados:**

| Domínio | Processo futuro | Persistência | Regra de ativação |
|---|---|---|---|
| Coleta | execução programada por fonte | raw + checkpoints | licença, endpoint, limites |
| Normalização/qualidade | jobs finitos e idempotentes | catálogo + ledger | esquema e reconciliação |
| Dados | SQLite WAL controlado inicialmente, evoluir para PostgreSQL se cargas concorrentes exigirem | volume privado + backup externo | durabilidade e restore |
| Histórico analítico | Parquet + DuckDB offline ou read-only | object storage/volume versionado | quota, direitos |
| Motores | jobs temporais, estatísticos e físicos | features + predições versionadas | backtest histórico real |
| IVO | orquestrador sob limites de memória/tempo | evidências e métricas | autorização de modelo/API |
| API/Gateway | serviço privado autenticado | leitura controlada e auditoria | TLS, IAM, rede privada |
| Briefing | composição, outbox e ponte contratual | edições/acks duráveis | dados publicados e WhatsApp |
| Monitoramento | heartbeats/lag, fonte indisponível, recursos | logs com retenção mínima | prova de alertas |
| Backup | snapshot SQLite consistente + artefatos relevantes | cópia criptografada externa | restauração em outro ambiente |

Os motores não podem chamar secretamente APIs ou executar workers pelo uso
do IVO; são invocados pelo orquestrador com contratos e rastreabilidade.

## 2. Camadas e diretórios

**Código (imutável em release):** `/srv/nivon/releases/<sha>`;
link de versão ativa apenas depois da homologação. Containers limitados por
CPU/RAM, com non-root, read-only FS, capabilities descartadas e rede por
necessidade mínima.

**Dados privados (nunca no Git):**
- `/var/lib/nivon/raw`: evidência bruta autorizada, hash, MIME, direitos e fonte;
- `/var/lib/nivon/state`: banco SQLite, ledger de execuções, jobs e outbox;
- `/var/lib/nivon/analytics`: derivados com as quatro datas e revisão;
- `/var/lib/nivon/models`: pesos, parâmetros, métricas e versões de previsão;
- `/var/backups/nivon`: pacotes locais transitórios (não substituem remoto).

Separar cliente e provedores externos por segredos, chaves e privilégios
mínimos. Sem montar `/var/run/docker.sock` em agentes, expor portas do banco,
publicar UI ou API sem TLS/autenticação, ou manter token dentro da imagem.

## 3. Orquestração e confiabilidade

- Execuções de coleta com timers ou scheduler controlado, um lease por dataset,
  chave de idempotência e estado persistente; primeira execução é dry-run.
- Retry limitado com backoff/rate limits; fonte indisponível vira SOURCE_LAG.
- Jobs separados por carga: horários curtos para status quando permitido;
  diário para mercado e clima, semanal para safra/diesel, mensal para Comex
  e outros, **sempre respeitando a cadência real de publicação**.
- Processamento histórico em lotes resumíveis para não estourar CPU,
  memória, armazenamento nem chamadas à origem.
- AIS contínuo somente com cobertura, licença, quotas e armazenamento
  garantidos: não assumir que 24/7 cabe na instância gratuita.
- Notícias do briefing precisam de `published` original nas últimas 24h;
  valores econômicos usam a última data de referência disponível, distinta
  da notícia.

## 4. Segurança, dados e backup

- Inventário separado de código, dados, material restrito e credenciais.
- Acesso do operador por identidade segura; desabilitar senha SSH se possível,
  restringir origem e usar MFA no provedor. HTTPS por proxy autenticado.
- Segredos em mecanismo protegido da conta, nunca em flags de CI, commits,
  logs, imagens, manifestos ou variáveis de exemplo com valores reais.
- Trilha de auditoria sem PII excessiva; dados pessoais minimizados.
- Snapshots SQLite consistentes via API do SQLite: usar código já existente
  `pacote_recuperacao.py`, não fazer cópia de arquivo WAL em escrita ativa.
- Remoto deve ser criptografado, independente da VM, restaurável, com
  política explícita de retenção e custo; provas de integridade e hashes
  não significam criptografia nem autenticidade. Restaurar periodicamente em
  ambiente independente antes do go-live e após alterações relevantes.
- Sem backup remoto comprovado, **não** ativar coleta contínua com dados
  cuja perda destruiria histórico.

## 5. Limites financeiros e capacidade

O provedor é um candidato, **não uma disponibilidade conferida na conta**.
Validar região principal, A1 ARM, OCPU/RAM, boot/block volumes, objeto, tráfego,
backup e quotas compartilhadas com outras unidades. Orçamento/alertas não
constituem hard cap universal de cobrança: usar ausência de recursos pagos,
quotas explícitas e bloqueio de provisionamento como proteção efetiva.

A documentação oficial Oracle Always Free deve ser revisada na data do
provisionamento: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

## 6. Ordem de adoção (sem liberar cloud nesta PR)

1. Congelar commit/release consolidando PRs #1, #3, #6, #7, #8, #9 sem
   regressão nem perda de código; resultados de branches isoladas não se somam
   automaticamente.
2. Rever todas as dependências e licenças; assinar versão de configuração.
3. Verificar via console/API autorizada a disponibilidade REAL de OCI e quotas;
   registrar evidência e custo projetado antes de criar qualquer VM.
4. Criar infraestrutura mínima privada somente após decisão de homologação,
   com rede, IAM, firewall, volumes e segregação.
5. Implementar banco persistente e backup remoto criptografado; restaurar.
6. Homologar uma cadeia completa com fonte pública autorizada,
   aquisição real, análise, histórico, testes de qualidade e recuperação.
7. Habilitar scheduler e observabilidade após proteção contra duplicações.
8. Adicionar interface privada, IVO e motores validados; finalizar fluxo de
   briefing/outbox/WhatsApp apenas com direitos e consentimento.
9. Executar ensaio operacional de falhas e recuperar dados/serviços.
10. Auditar e liberar cada serviço explicitamente; publicação e go-live são
    decisões separadas do merge GitHub.

## 7. Gates de aceite (vinculados a inventory.v1.json)

`OCI_ACCOUNT_QUOTAS`, `SECRETS_AND_IAM`, `DURABILITY`,
`BACKUP_RESTORE`, `SOURCE_RIGHTS`, `REAL_SOURCE_VALIDATION`,
`REAL_HISTORICAL_BACKTEST`, `GOVERNED_AGENT_E2E`,
`AUTH_AND_TLS`, `AIS_LINEUP_LICENSED`, `PUBLISH_AND_PROVIDER`,
`ALERTS_AND_RECOVERY`, `ZERO_COST_PROOF`,
`INDEPENDENT_SECURITY_REVIEW`, `OPERATOR_HOMOLOGATION`.

Nenhum gate está liberado neste inventário. Quem verificar posteriormente
deverá associar prova datada e assinada no mecanismo de release, não
simplesmente mudar booleano em JSON para obter go-live.
