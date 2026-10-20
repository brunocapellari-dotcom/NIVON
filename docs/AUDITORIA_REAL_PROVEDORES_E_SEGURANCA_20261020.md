# NIVON — Auditoria de provedores e controles de segurança

**Data de coleta:** 20/10/2026. **Classificação:** leitura limitada pelas conexões autorizadas, sem deploy, sem alteração de cloud, sem gasto autorizado. Não é certificação da infraestrutura existente.

## Evidência observada e limites da descoberta

| Superfície | Verificação | Achado | Limite |
|---|---|---|---|
| GitHub `brunocapellari-dotcom/NIVON` | Repositório, `main`, PR #10, branches e Actions | `main` contém apenas README; componentes permanecem em PRs draft; PR #10 é a frente de infraestrutura | Nenhuma homologação/deploy |
| GitHub Actions | Run 39482822259 no SHA `3d58723cf97ad97a0f12f641dd9bcc81513a418f` | 949 testes, 5 ignorados, 0 falhas; cinco jobs reais ignorados; workflow sintético aprovado | Fixtures não equivalem a teste com fonte real |
| GitHub Rulesets | Listagem de regras de repositório | API retornou lista vazia | Branch protection retornou 403 na integração: **não é possível confirmar nem negar** proteção efetiva de `main` |
| Render (conexão autorizada) | Inventário de serviços visíveis | Nenhum serviço identificado como NIVON | Outros projetos existem; não atribuir recursos/custos de terceiros ao NIVON |
| Vercel (conexão autorizada) | Busca de projetos NIVON | Nenhum projeto NIVON retornado | Não exclui recursos fora do escopo/conta |
| Supabase (conexão autorizada) | Nomes/status de projetos disponíveis | Nenhum identificado como NIVON | Não inspecionados bancos de projetos não relacionados |
| Neon (conexão autorizada) | Nomes de projetos disponíveis | Nenhum identificado como NIVON | Não inspecionados bancos de projetos não relacionados |
| Oracle Cloud Infrastructure | Descoberta de integrações OCI disponíveis | **Nenhuma conexão OCI capaz de auditar tenancy/quotas** nesta sessão | Não há prova de home region, IAM, billing, instâncias, A1 livre ou storage |

Os dados de outros projetos, IDs de conta, regiões específicas, segredos e URLs administrativas **não são reproduzidos** no repositório público.

## Oracle A1 — referência oficial não constitui quota disponível

Em 20/10/2026, a [documentação oficial Oracle](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) indicava, para a modalidade Always Free, até **2 OCPUs e 12 GB** de memória Ampere A1, computados também como **1.500 OCPU-h/mês e 9.000 GB-h/mês**, além de **200 GB agregados** para boot/bloco e **20 GB** de object storage, sujeitos às regras da tenancy. A documentação também ressalva disponibilidade regional, região home e possível reclaim de VM ociosa. A proposta **1 OCPU, 4 GB RAM, boot 50 GB e objeto 5 GB** cabe matematicamente nos tetos de referência **isolada**, sem comprovar saldo da conta nem custo final.

Não ativar fallback pago. Limites de requisições, egress, backups e serviços associados exigem conferência no console/API OCI, não são abrangidos pela conta aritmética.

## Riscos priorizados

**P0:**
1. Integrar as frentes num SHA de release único, manter `main` sem merge prematuro e rodar regressões neste SHA.
2. Verificar realmente OCI em modo somente leitura: região home, quota restante, billing, IAM, instâncias, volume, backups, endpoints e usos de outras unidades. Não introduzir chaves de conta no GitHub.
3. Verificar proteção efetiva de `main`: reviews obrigatórias, checks necessários, prevenção de force-push, aprovação de workflow/segredos e permissions mínimas. Leitura do endpoint retornou 403.
4. Backup remoto **criptografado**, segregado da VM, com retenção e restore integral comprovado em ambiente diferente (RPO/RTO medidos).
5. Segurança da cadeia de software: scanners de segredo e CVE, SBOM, imagem ARM64 com digest e dependências travadas; avaliar o aviso de Node.js 20 no workflow.
6. Observabilidade operacional real com alerta de erro, atraso/lag, falha de backup, disco, limite de quota e incidentes; monitor local `infra_health.py` não substitui monitor remoto.

**P1:** gatilho governado de jobs por fonte, API privada, IVO e orquestração, geração de briefing e ponte WhatsApp com direitos/consentimento.

## Correção executada nesta rodada

- Workflow `.github/workflows/testes.yml` ganhou `confirmar_diagnostico_fonte_real` (boolean, **false** por padrão).
- Cinco diagnósticos reais exigem, ainda, `main` e **variável de homologação específica por fonte** com valor literal `true`.
- Novo teste `tests/test_infra_ci_source_gates.py` e ajuste de `tests/test_workflow_network_safety.py`, mantendo CI de PR estritamente sintético.
- Procedimento: `infra/runbooks/ci_fontes_reais.md`.

**Gasto incremental de provisionamento:** nenhum recurso foi criado ou contratado nesta auditoria; **não existe comprovação do consumo faturado ou custo mensal da tenancy**. Uma execução de CI não é evidência de custo total zero.

## Bloqueios decisivos

- OCI: **acesso autenticado read-only ausente** na sessão, indispensável para dimensionamento real.
- Main protegida: **não verificável pelo token/integração atual** (403).
- Dados operacionais, direitos e backup remoto: não homologados.
- IVO, coletores e briefing: nenhuma capacidade cloud contínua atestada.
- Autorização humana para implantação da versão integrada: ainda pendente.

A PR #10 permanece em draft; **nenhum código desta documentação autoriza produção**.
