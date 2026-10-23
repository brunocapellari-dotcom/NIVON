# NIVON — Radar real PyPI/OSV · Execução de 23/10/2026

**Natureza:** observação pontual de metadados públicos; **NÃO** é homologação de bibliotecas Python. Fonte atual externa e os mesmos testes de integridade em artefatos produzidos pelo GitHub Actions.

## Execução e evidência

- **Data/hora da coleta na CI (UTC):** `2026-10-23T11:30:39.747519+00:00`. O horário das fontes não significa que publicações ocorreram nesse instante.
- **Commit do código radar:** `bc0d24ef11e897e83e7035de5efb0c6627bfeb48`.
- **CI da consulta real:** [GitHub Actions #39946562704](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946562704), job `radar-metadata-real` aprovado. Suite integrada de seis casos de contrato, seguida por quatro GET PyPI de metadados e um POST OSV de somente leitura; nenhum wheel foi baixado ou instalado.
- **Artefato:** [#12498476799](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946562704/artifacts/12498476799), `nivon-radar-pypi-osv-real-readonly`, 6.754 bytes. SHA256 do ZIP externo `fe03d55607a7edd92106e06154cdfe6b4afa57bd872dfcf7052032c06bdd4b82`, retornado pela API GitHub **e conferido por hash dos bytes baixados fora do runner**. ZIP sem erro de teste CRC. Contém apenas `radar_pypi_osv.json` e `sha256sums.txt`; o SHA256 do JSON é `145146de8e400948613f5999e2ab2cdeeb618bb2f5b41aca669de419539a3ad6`, também conferido fora do runner.
- **APIs consultadas:** [PyPI release JSON](https://docs.pypi.org/api/json/) e [OSV querybatch](https://google.github.io/osv.dev/post-v1-querybatch/). Nenhum conteúdo de roda de terceiros foi obtido; os digests no JSON são **alegações de hash do índice**, não validação contra bytes dos arquivos.

## Resultado observado na coleta

| Dependência direta selecionada | Versão publicada consultada | Restrição do NIVON | Interpretação |
|---|---|---|---|
| agrobr | 2.0.0 | `==2.0.0` | Versão fixada confere; licença declarada MIT, não homologada |
| duckdb | 2.0.0 | `>=1,<2` | **Incompatível** com a faixa declarada; não atualizar automaticamente |
| mlforecast | 1.1.0 | `>=1,<2` | Satisfaz faixa numérica local, sem resolver transitivas |
| river | 0.26.1 | `>=0.22,<1` | Satisfaz faixa numérica local; licença declarada BSD-3-Clause, não homologada |

Na mesma consulta, **OSV retornou zero IDs para as quatro versões** e o campo de vulnerabilidades da API PyPI estava presente, também com zero IDs. Isso significa *nenhuma vulnerabilidade listada nessas duas respostas no momento da coleta*, não “zero CVEs” para o NIVON, para versões transitivas ou para todas as fontes de segurança.

**Incompatibilidade concreta detectada:** o PyPI apresentou `duckdb==2.0.0` como release mais recente, mas `pyproject.toml` delimita `duckdb>=1,<2`. A seleção de um release compatível exige resolvedor PEP 440 e metadados adequados; jamais assumir que a versão mais recente pode ser instalada no projeto.

## Entregas de código auditáveis

- `src/nivon/radar_pypi_osv.py`: cliente HTTPS com endpoints estritamente permitidos, limite de 4 consultas PyPI + 1 OSV, tamanho e tempo limitados, sem redirects e sem credenciais. Lê grupos diretos do `pyproject.toml`, compara requisitos numéricos reconhecidos, inventaria digests de releases, versão, Requires-Dist, declarações de licença e IDs de avisos OSV/PyPI. Retorna `approved_for_install=false` e `approved_for_production=false`.
- `tests/test_radar_pypi_osv.py`: fluxo de quatro releases mais OSV simulado, checksums inválidos, paginação/resposta incompleta, substituição de versão fixada e incompatibilidade de `duckdb<2`; nos testes simulados, os campos `pypi_responses_verified_https` e `osv_response_verified_https` são falsos.
- `.github/workflows/radar-pypi-osv.yml`: job isolado, permitido somente em PR da branch de pesquisa do próprio NIVON; permissões `contents:read`, sem terceiros instalados, com artefato de retenção 3 dias. Alterações na branch padrão/ativação recorrente exigem integração separada.

## Limites e próximo bloco

A consulta **não** criou lock resolvido, SBOM transitive, não verificou hash de bytes de wheels, assinaturas do fornecedor, PEP 508/440 completo, tags de plataforma, compatibilidade de licença ou execução do software. Índice PyPI + OSV não substituem scanner em dependências transitivas resolvidas. Ainda não há liberação para produção.

**Próxima execução P1:** ampliar cobertura aos extras completos e versões compatíveis com resolução PEP 508/440 em sandbox, baixar wheels somente após revisão de licenças e procedência, executar scanner CVE independente e certificar hashes. Não executar instalação ou publicar como homologado sem esses gates.

**Regra editorial:** este relatório é um retrato da coleta de 23/10/2026; não tratar as versões observadas ou os resultados de vulnerabilidades como atuais em outra data.
