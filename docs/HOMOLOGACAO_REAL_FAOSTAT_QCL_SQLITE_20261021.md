# NIVON — FAOSTAT QCL: validação real de ZIP + SQLite local (21/10/2026)

## Código, testes e rastreabilidade

Código permanente integrado: https://github.com/brunocapellari-dotcom/NIVON/pull/111

- `src/nivon/faostat_qcl_stream.py`: download HTTPS limitado, ZIP com limites e allowlist, CSV em streaming, recorte país/cultura/ano/elemento e exportação de snapshot.
- `scripts/smoke_faostat_qcl_stream.py`: comando manual com `--executar` obrigatório e `--sqlite` opcional.
- `tests/test_faostat_qcl_stream.py`: fixture ZIP real em memória, teste end-to-end simulado, idempotência SQLite, revisões e fail-closed.

## Teste HTTP e stage SQLite reais

Execução completa: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39698793414

| Prova | Evidência |
| --- | --- |
| URL oficial | https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip |
| Arquivo download | **33.921.825 bytes** |
| Checksum SHA-256 | `c5835418c18f9322e7decbd6800f93a216eaae3cdfa31acb08f0518c0c6d6853` |
| Linhas de CSV percorridas | **4.209.110** |
| Filtro | Brasil (FAOSTAT código 21), soja (código 236), produção física (elemento 5510), 2023 |
| Resultados selecionados | **1** |
| Inserções no SQLite temporário | **1** |
| Validação SQL de data_publicacao | **NULL (sem inventar data de divulgação)** |
| Atualização do BigQuery | **NÃO executada** |
| Cron/pagamento/publicação | **NÃO ativados** |

A execução ocorreu em runner temporário, com stage no diretório `/tmp` e sem anexar dados ou banco como artefato. O workflow de investigação estava isolado na PR #113, fechada sem merge para não ativar qualquer chamada automática no repositório.

## Escolha de rota canônica

No Catálogo Mestre, a rota `FAO_FAOSTAT_LONG_RUN` passa a apontar ao ZIP oficial e a `nivon.faostat_qcl_stream.executar_qcl`. A API fenixservices legada segue como fallback documentado, mas o teste HTTP real daquela API havia dado timeout. A rota Bulk já passou por validação.

O dataset continua em **CODE_PRESENT**, com `runtime_enabled=false`, `scheduled_enabled=false`, `last_verified_data=null`, porque o campo `last_verified_data` representa estado operacional contínuo, não um teste pontual. Esta página tem o registro próprio e imutável de evidência HTTP.

## Regras metodológicas

FAOSTAT QCL é estatística anual por país, não medição de produtividade em fazenda nem projeção da safra CONAB/USDA atual. A chave usa `Area Code`, `Item Code`, `Element Code`, ano e hash de versão do arquivo. A quantidade é expressa em **t**, não em sacas; flags oficiais devem ser preservadas. `data_atualizacao_fonte` é metadado da edição do dataset, não `data_publicacao` da observação; bitemporalidade continua pendente de pesquisa.

O SQLite é uma camada de stage **local, portátil e opcional**, e não substitui o banco analítico central. Reexecuções com o mesmo SHA não duplicam registros; uma versão de arquivo diferente produz uma nova edição preservada.

## Próxima execução

Conectar camada canônica BigQuery do NIVON somente após descobrir e verificar ID de projeto, dataset, contas/identidades técnicas e orçamento. Preparar carga idempotente, particionada por referência e com hash/vintage, preservar raw com limites e backup/restauração. Não ativar APIs pagas, serviços ou storage sem consentimento explícito para possível custo.

Dado de milho/trigo, outros países e períodos seguem com parser e testes simulados, mas **não passaram ainda por amostras reais específicas**. O teste do Brasil/soja/2023 prova o pipeline pontual, não cobertura total ou ausência de futuras alterações de esquema.
