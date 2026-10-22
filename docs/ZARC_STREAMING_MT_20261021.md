# ZARC 2026/2027 — Conector experimental de streaming para Mato Grosso

**Origem primária:** MAPA, https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico
**Recurso oficial:** https://dados.agricultura.gov.br/dataset/tabua-de-risco-zoneamento-agricola-de-risco-climatico/resource/139e5a60-1f43-4cc8-aeab-a35dbbf816c0

## Implementado

- src/nivon/amostra_csv_ckan_range.py: dois GETs controlados (catálogo + prefixo Range), um CSV específico, máximo 512 KiB padrão. Não interpreta decêndios nem representa arquivo completo.
- src/nivon/zarc_stream_mt.py: único GET para CSV 2026/2027 oficial; grava temporariamente em spool local limitado a 160 MB, calcula SHA-256 integral e percorre o arquivo com csv.DictReader. Nunca grava dados reais no repositório nem no banco.
- Testes: tests/test_amostra_csv_ckan_range.py e tests/test_zarc_stream_mt.py; fixtures sintéticas com colunas reais do arquivo oficial e bloqueios para redirecionamento, MIME HTML, limite de bytes, município malformado, safra incompatível, cabeçalho alterado e linhas desalinhadas.
- scripts/diagnostico_zarc_stream_mt.py: opt-in por --executar; somente saída agregada e sem identificar linhas individuais.

## Layout observado em HTTP real

55 colunas: Nome_cultura, SafraIni, SafraFin, Cod_Cultura, Cod_Ciclo, Cod_Solo, geocodigo, UF, municipio, Cod_Clima, Nome_Clima, Cod_Outros_Manejos, Nome_Outros_Manejos, Produtividade, Cod_NM, Cod_Munic, Cod_Meso, Cod_Micro, Portaria e dec1 até dec36.

Prova de acesso por prefixo de 512 KiB:
https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39717516248
2.262 linhas completas, estrutura reconhecida; não é ingestão integral.

## Interpretação

Portarias, classe de solo, manejo, ciclo, clima, produtividade e campos decendiais são códigos/indicadores da metodologia ZARC. O conector não converte os valores brutos em recomendação de plantio nem em probabilidade de produtividade. As permissões Creative Commons Atribuição aparecem na página do recurso, mas exigências de atribuição e eventuais condições específicas devem ser preservadas na camada de saída.

Registros foram contabilizados em MT somente quando UF=MT, geocodigo possui 7 dígitos e a safra é 2026/2027. Outros UFs são contabilizados apenas no total de linhas do arquivo. A agregação por cultura é exclusivamente contagem de registros, não área, volume, risco agregado ou intensidade climática.

## Gates de operação

O resultado de análise estrutural **não libera** backend, BigQuery, relatórios, exportação, publicação, agendamentos ou backtests. Requer: interpretação formal da metodologia dec1..dec36, portarias e relação com município/cultura/ciclo/solo/clima; validação espacial com IBGE; qualidade observada de edição e vintages; direitos por operação; snapshots imutáveis com backup e idempotência; e três provas em edições distintas antes de uso operacional.


## Resultado da prova integral de 21/10 (UTC 22/10)

- [Execução #39717906602](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39717906602): o arquivo completo NÃO foi homologado. O script retornou ErroZarcStream, sem imprimir o motivo interno. Não há contagem integral comprovada, hash completo ou persistência; nenhum valor pode ser publicado.
- [Execução #39718216591](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39718216591): HEAD confirmou HTTP 200 e Content-Type text/csv, mas não forneceu Content-Length.
- [Execução #39718357455](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39718357455): a consulta CKAN confirmou o recurso, mas o portal também não informou tamanho em bytes. Não é correto supor que a falha integral decorreu do teto de 160 MB.
- A inspeção parcial do cabeçalho/2.262 linhas permanece válida e separada do teste integral. O leitor integral existe e foi aprovado em fixtures sintéticas, mas não em dados integrais reais.

**Próxima correção técnica:** realizar prova de estrutura e tamanho em pequenos blocos com diagnóstico seguro, distinguindo arquivo maior que teto, linhas inválidas, UTF-8, geocódigo, Portaria e divergência de safra antes de repetir um download integral. Não ampliar teto às cegas e não iniciar backfill na infraestrutura real.
