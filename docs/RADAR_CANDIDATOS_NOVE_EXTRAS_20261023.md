# NIVON — Candidatos PyPI para nove dependências opcionais

**Observado em:** 23/10/2026 às 16:00:34 UTC. **Estado:** coleta real de metadados públicos, read-only. **Nunca interpretar esta tabela como lock resolvido ou homologação de pacote**.

## Finalidade e escopo

A frente de Pesquisa, Ferramentas e Inovação expandiu o radar para **9 distribuições diretas distintas**, presentes nos sete extras declarados em `pyproject.toml`: `agro`, `forecast`, `ivo-ml`, `ivo-online`, `ivo-query`, `ports` e `excel`. A seleção usa o maior release numérico estável, não-yanked e com arquivo de distribuição e SHA256 *declarado pelo índice PyPI*, dentro das restrições numéricas suportadas do projeto. Para pins exatos usa a versão fixada. A API versionada é consultada de novo para recuperar os metadados do candidato, seguida de OSV em lote para as nove versões selecionadas.

| Dependência | Candidato por faixa numérica | Release mais recente informado pelo índice | Faixa declarada no projeto |
|---|---|---|---|
| agrobr | 2.0.0 | não consultado (pin exato) | `==2.0.0` |
| duckdb | **1.5.6** | **2.0.0** | `>=1,<2` |
| mlforecast | 1.1.0 | 1.1.0 | `>=1,<2` |
| openpyxl | 3.1.5 | 3.1.5 | `>=3.1,<4` |
| pandas | **2.3.3** | **3.1.0** | `>=2.2,<3` |
| pdfplumber | 0.11.10 | 0.11.10 | `>=0.11,<1` |
| river | 0.26.1 | 0.26.1 | `>=0.22,<1` |
| scikit-learn | 1.9.1 | 1.9.1 | `>=1.4,<2` |
| statsforecast | 2.1.1 | 2.1.1 | `>=2,<3` |

**Principais achados:** `duckdb 2.0.0` excede `<2`, e `pandas 3.1.0` excede `<3`. Os candidatos 1.5.6 e 2.3.3, respectivamente, satisfazem apenas a faixa numérica tratada pelo auditor local. A versão candidata não foi instalada e o código não testou ABI, wheel tags, Python real, resolução transitiva, comportamento do adaptador nem licenças. Não trocar versões no `pyproject.toml` sem testes de compatibilidade.

## Evidência observada

- [GitHub Actions — coleta real #39983115717](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983115717): **SUCCESS**. 6 testes de integração v2, 6 do radar v1, 8 requisições PyPI de índice, 9 requisições PyPI de versão selecionada e 1 lote OSV de 9 versões. Sem `pip install` ou download de `.whl`, `.tar.gz`, `.zip` de terceiros.
- [GitHub Actions — suíte integrada #39983115736](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983115736): **SUCCESS** após reconciliação do teste concorrente GCS da PR #7. **1.465 testes executados, 8 skipped, 1.457 aprovados**. O pipeline E2E sintético da pesquisa também continuou em execução.
- [Artefato #12513963598](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983115717/artifacts/12513963598): `nivon-radar-pypi-osv-real-readonly`, ZIP externo de **23.659 bytes**; SHA-256 externo **`5c92a2906f8709d225df912ad261067c6076761ccc5e0cbdd693675dd66b1a8d`**, obtido da API GitHub e **recalculado dos bytes baixados fora do runner**. O ZIP passou no teste CRC; contém `candidatos_nove_extras.json`, `radar_pypi_osv.json` e `sha256sums.txt`. Os **dois checksums internos foram recalculados independentemente e coincidiram**. Artefato disponível por 3 dias após a execução, salvo se a plataforma o remover antes.
- As duas APIs públicas **não reportaram IDs de vulnerabilidade para as nove versões nessas respostas**, na data de corte. Isso não certifica ausência de CVEs, não contempla advisories posteriores e não cobre toda a árvore transitiva. Foram enumerados **218 arquivos nas listas de distribuição dos nove releases**; os arquivos são apenas metadados e alegações de hashes no índice, não downloads locais verificados.
- Fontes: [PyPI JSON API](https://docs.pypi.org/api/json/) e [OSV querybatch](https://google.github.io/osv.dev/post-v1-querybatch/). A confiança no TLS/índice remoto é distinta da autenticação criptográfica de cada wheel.

## Implementação verificada

- `src/nivon/radar_compatibilidade_pypi.py`: conjunto fechado de 9 distribuições, parsing de todos os sete extras via TOML e parser numérico conservador, exclusão de releases prerelease/yanked/sem digest, segunda consulta PyPI para o candidato, lote OSV e JSON de evidências. Nunca aprova instalação/produção.
- `tests/test_radar_compatibilidade_pypi.py`: seis testes integrados: cobertura total, seleção de versão anterior não-yanked, dependência não autorizada, troca de versão, arquivo yanked/sem hash e retorno parcial OSV.
- `.github/workflows/radar-pypi-osv.yml`: execução separada read-only, permissions `contents:read`, runner GitHub, sem segredos, acesso apenas às APIs permitidas e publicação de artefato de integridade. O radar v1 de quatro pacotes permanece no fluxo como referência de versão latest; o v2 monitora os nove candidatos.

## Decisões e bloqueios posteriores

O projeto **não** passou a ter lock reproduzível com hashes de artefatos efetivamente baixados. A maior versão estável numérica na faixa não necessariamente suporta Python 3.11 e/ou Linux x86_64. Também não foi feita interpretação integral PEP 440/508, avaliação legal de licenças, SBOM transitivo, scanner CVE independente em todas as transitivas ou verificação Sigstore da origem.

**Próximo bloco prático:** validar `Requires-Python` e tags de wheel para o ambiente-alvo sem instalação; pesquisar a resolução completa de dependências e construir um lock de metadados para validação; separar o futuro download/homologação de wheels reais do radar estritamente informativo. Somente após uma auditoria e autorização de ambiente prosseguir com instalação em sandbox. `approved_for_install=false`, `approved_for_production=false`.
