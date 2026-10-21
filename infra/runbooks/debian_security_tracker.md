# NIVON — Reconciliação de vulnerabilidades no Debian Security Tracker

**Data de execução verificada:** 21/10/2026. **Aplicação:** worker sintético, imagem Trixie; não equivale a go-live.

## Fonte e método

- **Debian Security Tracker (fonte primária)**: `https://security-tracker.debian.org/tracker/data/json`. O CI faz download HTTPS de URL fixa com limite de **90 MB** no runner temporário, sem armazenar no GitHub nem enviar artefatos; após a execução, o runner efêmero descarta a cópia.
- **Trivy v0.76.0**: scanner independente da imagem Docker; os achados HIGH/CRITICAL continuam integralmente bloqueantes.
- `src/nivon/infra_debian_advisory.py` cruza IDs CVE por `SrcName` do Trivy e pelo pacote **fonte** do Debian (não supõe que cada binário é pacote-fonte). Em ausência de `SrcName`, usa `PkgName` somente se ele existir como nome de pacote-fonte no tracker; caso contrário, marca lacuna.
- Comparação estritamente da release `trixie`; arquivo JSON oficial não contém, por si só, evidência de qual versão está instalada na imagem. `status=resolved`, uma versão corrigida declarada ou `not-affected` **nunca devem afirmar que a imagem foi corrigida**.
- Publicar apenas totais sem IDs CVE, versões instaladas, caminhos locais ou payloads externos. Os status do Debian são segunda opinião, não substituem o gate Trivy. Falha da fonte/verificação reprova a etapa; o passo final de bloqueio Trivy é executado mesmo se o download falhar.

## Evidência do primeiro confronto ao vivo

[GitHub Actions 39654866046](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39654866046), SHA `94c45c611a1c25a7e8c0f629cee4ccd096f92b74`:

| Evidência | Contagem observada |
|---|---:|
| Achados HIGH/CRITICAL em pacotes Debian | 44 |
| Achados HIGH/CRITICAL em pacotes Python | 2 |
| CVEs distintas na classe de pacotes Debian | 8 |
| Pares pacote-fonte/CVE correspondidos no tracker Debian | 4 |
| Pares classificados `open` no Debian Trixie | 4 |
| Pares com sinal `no-DSA` | 4 |
| Pares com versão corrigida informada pelo Debian | 0 |
| Achados bloqueantes no gate Trivy | 46 |

**Ajuste metodológico:** a primeira versão somava ao contador `no_source_mapping_cves` todo identificador que tivesse *alguma linha* sem `SrcName`, mesmo quando outra linha já o mapeava. Isto foi corrigido: `no_source_mapping_cves` mede IDs **sem nenhum mapeamento em quaisquer linhas**; `os_findings_without_source_mapping` mede linhas individuais sem metadado; `source_mapped_distinct_os_cves` mede IDs com ao menos um mapeamento. Portanto, os resultados de cobertura do primeiro confronto não devem ser reutilizados sem este ajuste.

O Debian é a autoridade sobre estado da distribuição, mas `open` + `no-DSA` pode refletir decisão de manutenção para uma versão específica, não é classificação automática da explorabilidade dentro do container. Não suprimir esses CVEs sem revisão independente. A lista de bibliotecas/binários depende do build real; não atribuir `util-linux` a qualquer pacote sem `SrcName` confiável.

## Pendências

1. Verificar a fonte/versão instalada para os CVEs sem pacote-fonte mapeado; cruzar com avisos Debian e, quando pertinente, patches upstream.
2. Analisar se as quatro correspondências abertas afetam tarefas efetivamente expostas no worker sem privilégios. Avaliação de explorabilidade não é licença automática para retirar achados.
3. Manter o SBOM e scanner em **AMD64 e ARM64**, sem liberar produção com HIGH/CRITICAL.
4. Revisar permissões de reutilização de dados do Tracker antes de redistribuir snapshot/derivados; o uso interno de diagnóstico não prevê redistribuição.
5. OCR/LLM não necessários: os dados oficiais e Trivy são JSON estruturado e devem continuar auditáveis.
