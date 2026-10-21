# NIVON — triagem das CVEs restantes no worker Trixie

**Etapa:** P0-07, 21/10/2026. **Objetivo:** diagnóstico reproduzível para remediar vulnerabilidades HIGH/CRITICAL, sem qualquer autorização de release.

## Contexto verificado

- Comparação de bases Python 3.11 slim: Bookworm **2 CRITICAL + 63 HIGH** (65 bloqueantes), Trixie **0 CRITICAL + 46 HIGH** (46 bloqueantes), mesmo Trivy v0.76.0 e banco de CVEs na execução do benchmark.
- Trixie com digest fixo é a base atual do **worker de homologação**, não uma imagem de produção.
- Gitleaks, testes unitários, build AMD64/ARM64 não nativo e ensaio Restic são gates separados. O scanner Trivy do worker **reprova** enquanto persistirem achados HIGH/CRITICAL.

## Triagem por pacote instalada

O módulo `src/nivon/infra_cve_triage.py` recebe **apenas um relatório JSON Trivy da imagem explícita** `nivon-worker-supply:ci`. Exige schema Trivy v2, alvos e classes conhecidas, nome de pacote validado e severidade conhecida.

O workflow `.github/workflows/infra_supplychain.yml` produz, em sequência:

1. Scan Trivy JSON e SBOM CycloneDX da mesma imagem efêmera, sem upload;
2. `python -m nivon.infra_cve_triage --trivy-json "$RUNNER_TEMP/nivon-trivy.json"` — resumo de **até 25 pacotes**, separando classes OS/linguagem, CRITICAL/HIGH e presença/ausência de `FixedVersion`;
3. `python -m nivon.infra_supplychain ...` — **gate obrigatório** que falha quando há HIGH/CRITICAL.

**Atenção:** `FixedVersion` preenchida significa apenas que o scanner informou uma versão de correção; não prova disponibilidade do patch no repositório da distro nem sua instalação. Os totais do relatório incluem todas as vulnerabilidades bloqueantes mesmo quando a lista de pacotes é truncada. A saída **não imprime CVE IDs, caminhos, versões instaladas ou relatórios brutos**.

A triagem retorna status normal (exit 0) quando analisa corretamente uma imagem vulnerável porque é um passo de **diagnóstico**, não a condição de aprovação. O gate posterior permanece reprovando a imagem vulnerável. Falta, ainda, avaliar manualmente cada CVE relevante e o caminho de atualização do pacote.

## Restrições inalteradas

- Nenhum `--ignore-unfixed`, supressão `HIGH`/`CRITICAL`, waive genérico, `continue-on-error` ou publish da imagem.
- Nenhum acesso à OCI, IAM, contratos/licenças de dados, coletores reais, scheduler ou deployment.
- A triagem não mede exposição efetiva: precisa avaliar biblioteca carregada, função explorável, privilégio do worker, correção upstream, distro, alcance e cenário de ataque.
- Não afirmar zero CVEs ou aprovação de produção até **um novo scan real** e revisão independente.
- O scan AMD64 não substitui execução/scanner nativos de ARM64.
- Novos commits na branch podem cancelar o CI anterior: registrar **SHA + execução + conclusão** ao fechar a rodada.

## Próxima ação

Usar a lista de pacotes produzida pelo CI para priorizar correções disponíveis por distro/versão. Comparar com candidatas oficiais fixadas por digest usando o benchmark já existente e testar imagem. Não alterar gate nem liberar produção sem comprovação de remediação.
