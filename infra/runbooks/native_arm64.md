# NIVON — ensaio ARM64 nativo do worker sem ferramentas de empacotamento

**Data:** 21/10/2026. **Ambiente:** GitHub Actions `ubuntu-24.04-arm`, repositório público, runner ARM64 nativo; não é VM Oracle.

## Escopo e controles

`.github/workflows/infra_native_arm64.yml` exige repositório público e verifica `platform.machine()` **e** arquitetura do Docker Engine. Usa a mesma base Python 3.11 Trixie com digest multiarch fixo para duas imagens: worker normal e candidato que remove `pip`, `setuptools`, `wheel` e `jaraco.context`. A base é obtida explicitamente do Docker Hub, mas os builds subsequentes usam `--network=none`. Runner não recebe segredos cloud, não faz deploy, não publica imagem, não altera IAM ou cron.

O candidato roda como UID 65532, filesystem somente leitura, sem acesso de rede, capabilities removidas e limites CPU/RAM. Ensaios executados: `self-check`, validação do Python ARM64 e ausência de bibliotecas de packaging, persistência SQLite sintética duas vezes no mesmo estado privado com idempotência. Depois o mesmo Trivy v0.76.0 Linux ARM64, cujo tarball é verificado por SHA-256, gera dois relatórios JSON e SBOM CycloneDX **sem upload**.

## Evidência anterior ao ajuste de metadados de arquitetura

[Execução ARM64 nativa 39598653129](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39598653129) **SUCCEEDED**, commit `4b8a5cd12b1bfeb4baeba19e596bb4b091a0e18f`. Testes de contrato **5/5**, comparador **9/9**. `NIVON_NATIVE_ARM64_RUNNER_AND_DOCKER_OK` e `NATIVE_ARM64_RUNTIME_AND_TRIM_OK`. Worker sintético: primeira passagem `state_written=true`, segunda `state_written=false`, `job_count=1`. SBOM **89 componentes**. Comparação ARM64 no mesmo job: baseline **46 HIGH/0 CRITICAL**, candidato **44 HIGH/0 CRITICAL**; ainda **44 bloqueantes**.

A primeira versão do comparador trazia literalmente `candidate_amd64_only=true` por herança do ensaio AMD64, embora o job fosse ARM64 nativo. Foi corrigido para receber `--architecture arm64`, exibindo `scan_architecture=arm64` e `candidate_amd64_only=false`. O campo `arm64_runtime_validated=false` no **comparador JSON** continua deliberadamente conservador, pois o parser isolado não verifica execução real: a prova está nas etapas `platform.machine()`, Docker Engine e execução do worker **no workflow**. O comparador jamais autoriza release.

## Próximo bloqueio

- O worker experimental **não substitui automaticamente** a imagem principal; gate Trivy canônico continua bloqueado por 46 HIGH na imagem principal.
- Mesmo com redução experimental para 44, a candidata está **bloqueada**: revisão dos CVEs por pacote, disponibilidade dos patches upstream e auditoria da capacidade real Oracle ainda pendentes.
- Execução no GitHub ARM64 **não** equivale a VM ARM64 OCI, runtime de coleta de dados, RPO/RTO, backup cloud, autenticação de usuários, licença de fontes, custos OCI ou homologação de produção.
- GitHub documenta runners ARM64 padrão sem cobrança de minutos para repositórios públicos; checar visibilidade e termos antes de eventual mudança para privado.
- Nenhum gate de `infra/inventory.v1.json` deve ser promovido por este experimento.

**Próxima ação:** triagem independente de patches Debian e dependências opcionais, mantendo auditoria de CVEs inalterada e código do worker principal protegido.
