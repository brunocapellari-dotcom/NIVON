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


## Achados distintos e avisos compartilhados (21/10/2026)

Para não confundir quantidade de linhas do Trivy com quantidade de vulnerabilidades
distintas, `infra_cve_triage.py` agrupa adicionalmente pelo identificador
`VulnerabilityID` (sem imprimi-lo). A saída pública do runner contém apenas:

- `blocking_findings`: achados por pacote/alvo; é esta a contagem que permanece bloqueante;
- `distinct_vulnerability_ids`: identificadores distintos de HIGH/CRITICAL;
- `repeated_findings_vs_distinct_ids`: diferença entre linhas e IDs distintos;
- `ids_affecting_multiple_packages`: IDs relacionados a mais de um pacote;
- `blocking_by_package_class`: contagens para pacotes de SO versus linguagem;
- `largest_shared_vulnerability_groups`: top 10 grupos por quantidade de pacotes,
  sem publicar IDs, paths ou versões brutas.

**Evidência real do scan canônico:**
[GitHub Actions 39604501944](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39604501944),
commit `33200b57643a5f82afeb4c08b1d8d9f292368282`: 46 HIGH, 0 CRITICAL,
**10 IDs distintos**, 19 pacotes, 6 IDs em múltiplos pacotes, 36 linhas
repetidas além dos 10 IDs únicos; classe do SO 44 achados, linguagem 2.
Quatro grupos, cada qual com 9 pacotes afetados e sem `FixedVersion`
informada. Os dois achados com `FixedVersion` indicada são da camada Python.
O gate de segurança **falhou corretamente** por 46 HIGH; o passo de triagem
terminou com sucesso porque é diagnóstico, não autorização.

**Interpretação restrita:** IDs de vulnerabilidade comuns a nove pacotes
não significam necessariamente nove vulnerabilidades independentes nem
comprovam que existe apenas uma correção trivial. Não somar/descontar a
mesma exposição sem análise de origem do pacote, distro, dependência e
correção disponibilizada. Falta comparar os IDs com advisories Debian
e verificar por pacote se há versão corrigida disponível, sua instalação
efetiva, compatibilidade e possível exposição explorável. Não dispensar
achados por serem de bibliotecas aparentemente não utilizadas.

Ações já aprovadas no mesmo commit: [suíte Python](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39604501880),
[ARM64 nativo](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39604501871),
[worker offline](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39604501988),
[Restic sintético](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39604501866).
Os demais gates e a produção continuam fechados.
