# NIVON — Lacunas de código e adoção de ferramentas GitHub

**Data-base 20/10/2026 — pesquisa e planejamento, SEM deploy, instalações ou
autorização de custos.** Esta nota completa o inventário do PR #10. As
ferramentas estão catalogadas em `config/infra_ferramentas_github.v1.json`;
não adicionar cópias divergentes ao catálogo do IVO ou da Holding.

## Diagnóstico demonstrável

A branch de infraestrutura contém `infra/compose.yaml` com **um único job
de auditoria offline**; não contém containers de API, workers de dados,
scheduler, banco operacional cloud, backup remoto criptografado, proxy TLS ou
agentes IVO em produção. `infra_health`, `infra_smoke`,
`infra_job_ledger` e `infra_oci_quota` são contratos, ensaios ou
diagnósticos locais. A branch `main` não possui código do produto homologado.

**Não confundir**: catálogo de fonte ≠ coletor ativo, CI sintético ≠
dados reais validados, e modelo codificado ≠ forecasting com skill validado.

## Backlog único de infraestrutura, dependências e aceite

| Ordem | Entrega a desenvolver | Reuso/solução | Prova que encerra o trabalho |
|---|---|---|---|
| P0-01 | Release integrada e imagem ARM64 reprodutível | GitHub Actions, Docker Compose, uv opcional | SHA único, CI de todas PRs, digest de imagem, SBOM, scan sem CVEs críticos |
| P0-02 | Preparação OCI privada/IAM e instalação reproduzível | OCI SDK/CLI oficiais ou scripts declarativos próprios; NÃO executar apply | Conta/região/quota real auditadas, volume/rede/identidade sob permissão mínima |
| P0-03 | Persistência operacional resistente a crash | SQLite WAL inicialmente, backup API já existente; PostgreSQL só com necessidade | reinícios/concorrência, snapshots com quatro datas, registro e consulta as-of |
| P0-04 | Backup externo cifrado e restauração | restic (preferência) vs Litestream (benchmark opcional) | cofre remoto independente, retenção, recuperação em outro host, RPO/RTO medidos |
| P0-05 | Dispatcher com permissão por fonte | systemd timers ou agendador leve + ledger existente | uma fonte autorizada E2E, idempotência, retry seguro, rate limit, checkpoints |
| P0-06 | Saúde real e observabilidade | health checks próprios, logs JSON; exporters opcionais | falha/sumiço de fonte, disco cheio, inatividade e token exposto detectados |
| P0-07 | Gate de segurança no release | Gitleaks, Trivy, lock+SBOM, checagem de third parties | scan no SHA release, ausência de segredo/versão vulnerável conhecida |
| P1-01 | Gateway/API privado autenticado | FastAPI, contratos já existentes | TLS, IAM, rate limit, auditoria, nenhuma série sem licença/frescor |
| P1-02 | Motor e IVO em runtime governado | reutilizar contratos NIVON/IVO/Hermes, não duplicar runtime | evidências fonte→predição as-of→auditor→explicação, rollback |
| P1-03 | Pipeline automático do briefing | radar/portos/mercados/whatsapp existentes nas PRs | notícia <=24h, indicadores datados, frete anunciado, outbox/ack/consentimento |
| P1-04 | Cockpit marítimo conectado | MapLibre/deck.gl e gateway marítimo existentes na PR #6 | autenticado, 3+ amostras reais licenciadas por fonte, AIS e line-up segregados |

P0 é condição de infraestrutura e primeira operação vertical autorizada;
P1 é entrega das funcionalidades do produto sobre infraestrutura já robusta.
Não abrir dezenas de serviços/containers sem necessidade comprovada.

## Ferramentas: decisão técnica

**ADOPT (após gate):**
- [Docker Compose](https://github.com/docker/compose) — orquestração na VM,
  sem Kubernetes.
- [restic](https://github.com/restic/restic) — backup cifrado fora da VM,
  com credenciais segregadas e ensaio de restore.
- [Gitleaks](https://github.com/gitleaks/gitleaks) e
  [Trivy](https://github.com/aquasecurity/trivy) — detecção de segredos e
  vulnerabilidades em CI; não fazer upload de payload sensível.
- [uv](https://github.com/astral-sh/uv) — lock e instalação reproduzível
  se validar ARM64 e dependências da release.
- [FastAPI](https://github.com/fastapi/fastapi) — implementação futura de API
  privada, compatível com gateway existente em vez de duplicá-lo.

**BENCHMARK:** [Litestream](https://github.com/benbjohnson/litestream)
somente se RPO/WAL justificarem replicação contínua além do Restic.
Evitar dois subsistemas de backup sem ganho mensurável.

**RESERVE:** [Caddy](https://github.com/caddyserver/caddy) para proxy TLS,
[Prometheus Node Exporter](https://github.com/prometheus/node_exporter) para
métricas e [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector)
para tracing. Não iniciar coletores de telemetria extras na VM de baixo
consumo enquanto diagnósticos próprios resolverem.

As licenças listadas no JSON foram inspecionadas nos repositórios upstream;
**isso não verifica versões transitivas, licença de dados, datasets,
tokens, endpoint ou direito de redistribuição.**

## Bloqueadores que GitHub sozinho NÃO resolve

1. OCI: quotas, região home e recursos de outros projetos no mesmo tenancy;
   uso real e proteção contra gasto.
2. Direitos de consulta, coleta, cache, transformação, treinamento,
   publicação e redistribuição para cada fonte; CME/ICE/market data exige
   tratamento específico.
3. Consentimento, provedor e templates de WhatsApp quando aplicável;
   integração com WhatsApp AI sem copiar suas responsabilidades.
4. Histórico licenciado e verificado, vintages reais, medições físicas
   coerentes e evidência de skill fora da amostra.
5. Backup cifrado fora da VM, ensaio remoto de restore e acesso seguro
   operacionais — scripts e documentação não são substitutos.

## Regra de avanço

Não criar infraestrutura paga, instalar dependências no servidor, subir
serviços, ligar coletor real, publicar dados ou fazer merge na `main`
como efeito desta nota. Para cada ferramenta escolhida, revisar versão,
licença exata e dependências transitivas, escrever adaptador mínimo e teste
de falha, registrar custo/uso e comparar alternativas na release.

O próximo código executável prioritário é **runtime container ARM64
sem segredos + backup restic verificável + controlador de jobs
configurável que continue OFF**. Ativar uma fonte real somente depois de
direitos, persistência e recuperação homologados.

## Ferramentas adicionais de infraestrutura como código (OCI)

A auditoria posterior identificou também soluções oficiais de código aberto:
[Oracle OCI CLI](https://github.com/oracle/oci-cli) (UPL-1.0/Apache-2.0)
para inventário read-only de recursos e limites com credenciais segregadas;
[OpenTofu](https://github.com/opentofu/opentofu) (MPL-2.0) e
[provider OCI da Oracle](https://github.com/oracle/terraform-provider-oci)
(MPL-2.0) como candidatos para provisionamento reprodutível somente após
homologação. `terraform plan` ou `tofu plan` não confirma por si só
que haverá custo zero; **apply automático e provisionamento seguem OFF**.

A OCI CLI é opção prioritária quando existir acesso permitido à conta;
OpenTofu/provider são BENCHMARK, pois uma única VM não justifica aumentar
complexidade sem benefício de manutenção comprovado.
