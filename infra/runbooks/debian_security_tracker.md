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

## Reconciliação integral usando o dpkg da mesma imagem (evidência posterior)

O Trivy retorna achados por **pacote binário**, enquanto o Debian Security Tracker indexa vulnerabilidades por **pacote-fonte**. O scan anterior tinha 40 linhas de SO sem `SrcName`. A ausência de origem não é ausência de vulnerabilidade; por isso a correlação anterior (4 pares) ficou **superada** pela análise posterior, sem alteração dos 46 bloqueantes.

Foi incorporado ao CI um inventário `dpkg-query -W -f='\${binary:Package}\\t\${source:Package}\\n'` executado **dentro da própria imagem local**, com `--network none`, sem privilégios, sistema de arquivos somente leitura. O mapa temporário é validado por `ler_mapa_dpkg`: nome de pacote, encoding, limite de tamanho, formato em duas colunas, impedimento de symlink e conflitos binário→fonte. Os dados não são enviados como artifacts nem incluídos no repositório.

**Evidência real mais recente:** [CI 39655958440](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39655958440), código `887590c2baea15a021f936172e46edfb2a17f6ee`, data UTC 21/10/2026 18:48:29. O scanner do worker Trixie relatou **44 achados HIGH de SO = 8 CVEs distintas** e **2 HIGH Python**. O inventário `dpkg` possuía **87 entradas**; mapeou as 44 linhas de SO a pacotes-fonte e encontrou **8 pares pacote-fonte/CVE correspondentes** no Debian. Os oito estão classificados como **`open` com `no-DSA`** para Trixie, nenhum com versão corrigida indicada na fonte consultada. `no_source_mapping_cves=0`, `no_tracker_entry_pairs=0`. Ainda assim, o **gate principal do Trivy falhou corretamente** com 46 HIGH.

**Limites:** `open`/`no-DSA` é situação informada pelo Debian, **não** prova explorabilidade nem impossibilidade absoluta de atualização futura. Não houve comparação de versões dos pacotes instalados com versões de correção; nenhuma CVE foi suprimida ou marcada como resolvida. O relatório mede estado de pacotes do worker de homologação, não exposição de OCI ou coleta real. A candidata experimental sem ferramentas Python continua separada, com 44 HIGH, e não foi automaticamente promovida.

Testes registrados no mesmo commit: [suíte Python 39655958394](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39655958394) **1.033 testes, 6 ignorados, zero falhas**; [ARM64 nativo 39655958287](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39655958287), [worker 39655958280](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39655958280), [Restic 39655958657](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39655958657), [bench trim 39655958289](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39655958289) e [bench bases 39655958484](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39655958484): **SUCCESS**.

**Próxima remediação:** avaliar outros sistemas-base confiáveis com imagens fixadas por digest e provar o resultado via build/testes/scan em AMD64 e ARM64; investigar cada vulnerabilidade do SO junto ao Debian/upstream e à configuração efetiva do runtime. `no-DSA` não autoriza desabilitar o gate de segurança. Backup externo, IAM, quotas/custo OCI e liberação humana de produção continuam pendentes.
