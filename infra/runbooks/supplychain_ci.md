# NIVON — Gates de segurança da cadeia de software (PR #10)

**Data da revisão:** 21/10/2026. **Ambiente:** GitHub Actions efêmero, PR em draft.
**Sem produção, segredos de nuvem, provisionamento ou criação de recursos pagos.**

## Inventário de ferramentas e evidência de origem

As versões fixas abaixo foram extraídas dos metadados de assets dos releases oficiais do GitHub. Hash de arquivo impede troca acidental; **não equivale** a assinatura de provenance/verificação Sigstore independente. Antes de release de produção, avaliar attestations upstream.

| Ferramenta | Versão | Arquivo Linux x64 | SHA-256 |
|---|---|---|---|
| Gitleaks | 8.30.1 | `gitleaks_8.30.1_linux_x64.tar.gz` | `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` |
| Trivy | 0.76.0 | `trivy_0.76.0_Linux-64bit.tar.gz` | `e24b1c51293c1b15e4ba8d45bbc7891ba053f90278ec2698f3562c993e145fe7` |

Downloads apenas das páginas de releases oficiais; `sha256sum -c` obrigatório antes de executar binário. Ações `checkout` e `setup-python` seguem fixadas por commit SHA. O runner obtém ferramenta e base do Docker pela rede, e Trivy consulta seu banco de vulnerabilidades. **Não é um workflow sem rede**, apenas sem chamadas a fontes agro/serviços NIVON e sem upload de dados reais.

## Gates de CI implementados

Workflow `.github/workflows/infra_supplychain.yml` tem dois jobs independentes:

1. **detect-secrets:** checkout sem credenciais persistentes com histórico Git completo; Gitleaks `git` com saída e relatório **apenas local no runner**, sem mostrar possíveis segredos. Qualquer achado ou erro do Gitleaks reprova o job, sem exceções silenciosas.
2. **sbom-and-vulnerabilities:** build local da imagem sintética `Dockerfile.worker` com base fixada por digest; Trivy `image` gera inventário **CycloneDX** e relatório de vulnerabilidades; `nivon.infra_supplychain` valida identidade de imagem, schema, presença de resultados e componentes, e reprova qualquer HIGH/CRITICAL identificado. Nenhum `--ignore-unfixed`, nenhuma allowlist não auditada, nenhum `continue-on-error`.

Resultado exibido é apenas contagem por severidade e número de componentes. Os arquivos JSON brutos e eventuais achados Gitleaks não são enviados como artefatos nem ao chat. **Não usar uploads externos** de SBOM/relatórios sem revisão de possíveis dados restritos.

## Limitações explícitas

- Trivy pode falhar por rate limit ou indisponibilidade do banco de CVEs; falha de scanner é falha do gate, não evidência de ausência de vulnerabilidades.
- O teste de imagem cobre **somente amd64 do runner**, não atesta ARM64, liberação de OCI, imagens de API, bibliotecas extras/LLM nem produção.
- A política bloqueia HIGH/CRITICAL inclusive quando não há correção conhecida. Remediação exige upgrade de base, restrição documentada e aceite independente — nunca mascarar risco para obter CI verde.
- Gitleaks é detecção baseada em heurísticas e regras; aprovação não prova ausência universal de segredos.
- CycloneDX **não** equivale a assinatura de SBOM/proveniência nem atesta autorização de licenças transitivas.
- Sem lock/transitive dependency audit das opções `agro`, `forecast`, `ports` e `excel`; a imagem offline não as instala.
- Mecanismo de autorização de release permanece separado e com todos gates do inventário bloqueados.
- CI em PR continua sem deploy, push de imagem, armazenamento de chaves ou coleta agro real.

## Execução local dos testes estáticos

```sh
PYTHONPATH=src python -m unittest discover -s tests -p test_infra_supplychain.py -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

Os scanners reais são executados pelo workflow GitHub ao modificar código, config, Dockerfile, dependências, workflow ou testes. Status deve ser conferido **no SHA da PR**, não extrapolado entre commits.

## Próxima prioridade

Após validar o workflow real, reconciliar eventuais CVEs e achados Gitleaks sem expor materiais sensíveis. Em seguida: SBOM de **todas** as imagens e arquiteturas, revisão independente de licença/proveniência, políticas branch protection comprovadas (API de leitura anteriormente retornou 403), e backup cifrado em armazenamento remoto independente com restore supervisionado.

OCI, custos reais, storage remoto e host ARM64 continuam sem acesso verificado.
