# NIVON — Remediação da base Docker após CVEs

**21/10/2026 · imagem de homologação, produção bloqueada.**

## Resultado real do Trivy

Foi observado no [supply chain guard](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39591175438)
um total de **2 CRITICAL + 63 HIGH = 65 CVEs bloqueantes** na imagem
`python:3.11-slim-bookworm` do worker. O Gitleaks passou, e a
política bloqueou corretamente a promoção.

Para evitar supor que outra imagem seria mais segura, foi criado um
benchmark com builds dos mesmos arquivos do NIVON sobre duas bases,
executado com **Trivy v0.76.0, a mesma base de CVEs e no mesmo job**
sem dados privados ou publicação de artefatos. Resultado observado em
[benchmark Bookworm versus Trixie](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39591819974):

| Base | CRITICAL | HIGH | Bloqueantes |
|---|---:|---:|---:|
| Bookworm, imagem anterior | 2 | 63 | 65 |
| Trixie, candidata | 0 | 46 | 46 |

**Redução observada de 19 achados altos/críticos.** Não demonstra que os
achados restantes foram remediados, nem que o scanner cubra todos os riscos.

## Mudança adotada somente em homologação

A base do `infra/docker/Dockerfile.worker` foi atualizada para
`python:3.11-slim-trixie@sha256:cce12316475d7d56d605f76e1d811d0dc4e7227f2d4afd29951521264f504ff8`,
digest observado no ambiente de benchmark. O worker permanece sem rede,
coletas, timers e publicação. A versão anterior continua documentada
para comparação, mas **não é instalada em produção**.

A suíte `tests/test_infra_worker.py` requer o digest fixo; a pipeline
`infra_worker.yml` deve aprovar novamente build AMD64, criação de
camadas ARM64 e persistência local. A pipeline `infra_supplychain.yml`
continua **reprovando HIGH/CRITICAL** sem `continue-on-error`.

O comparador `src/nivon/infra_base_benchmark.py` verifica os relatórios
JSON das duas bases e imprime apenas contagens. Mesmo um candidato
sem vulnerabilidades permaneceria com `production_release_allowed=false`.

## Limitações e próxima remediação

1. **46 HIGH ainda são bloqueantes:** identificar pacotes, distribuições,
   CVEs e correções disponíveis no runner restrito sem publicar SBOM bruto
   potencialmente sensível. Não ignorar CVEs nem relaxar o gate.
2. Testar próximas bases oficiais menores/mais atuais e dependências,
   preservando Python e compatibilidade científica. Benchmark não
   equivale a aprovação de troca global.
3. Executar testes **nativos** em ARM64 e scan de imagem ARM64 em
   ambiente autorizado; build de camadas sozinho é insuficiente.
4. Revisar attestations/proveniência, assinaturas, SBOM e bibliotecas extras
   necessárias para coletores/IVO, não apenas o worker sintético.
5. Sem OCI comprovada, backup remoto restaurado, fontes licenciadas,
   IAM, gateway, scheduler nem aprovação independente, não existe go-live.

## Segurança dos scanners

O projeto Trivy sofreu ataque de supply chain em março de 2026
(https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23).
O NIVON usa download de release oficial e checksum fixo, sem
`trivy-action@tag`, e não envia tokens de cloud a runners. Mesmo assim,
checksum isolado não substitui assinaturas de provenance nem revisão
independente da cadeia de distribuição.
