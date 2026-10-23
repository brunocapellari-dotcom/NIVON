# NIVON — staging versionado ZARC MT

Data técnica: 22/10/2026 (execuções CI em UTC de 23/10).

## Motivação

O CSV MAPA ZARC 2026/2027 foi lido integralmente no GitHub Actions #39854814268, com 211.652.014 bytes, 957.490 linhas para o Brasil, 27.918 linhas de MT, 142 geocódigos e 16 valores de Portaria. Essa constatação prova **integridade estrutural da leitura**, não autorização de armazenamento permanente nem interpretação agronômica completa.

## Implementação

- `src/nivon/zarc_staging.py`: importa **arquivo binário local, sem HTTP** para SQLite staging em transação única, usando o livro-razão existente `src/nivon/registro_snapshots.py` e savepoints `src/nivon/transacoes_sqlite.py`.
- `abrir_zarc_staging()`: cria as tabelas locais `zarc_edicoes` e `zarc_linhas`. Cada linha é chaveada por `(sha256_edicao, numero_fisico_csv)`. **Não** há unicidade artificial de município/cultura/solo/ciclo: arquivos oficiais podem ter múltiplas linhas com as mesmas dimensões.
- `importar_zarc_local()`: calcula hash completo, valida 55 colunas, safra, geocódigo IBGE, demais códigos e decêndios brutos. Registra a coleta e insere linhas de MT sem reter dados de outras UFs.
- Em `zarc_linhas`, `chave_logica_sha` é somente candidata a ligar revisões. `conteudo_sha` preserva alterações nos decêndios e demais campos. `dados_raw_json` guarda os **55 valores literais** como recebidos, sem converter em risco.
- `comparar_edicoes()`: compara vintages com contagem de chaves adicionadas/ausentes/alteradas e **ambíguas**; não colapsa ou faz correspondência forçada de duplicatas.
- As quatro datas são tratadas separadamente: competência 2026/2027, referência nula não comprovada, publicação nula até prova de data da edição e coletas UTC em `nivon_coletas`. Edicões sem publicação provada não são válidas para backtest as-of.
- `registro_snapshots.py` recebeu limite isolado de 230.000.000 bytes para **metadados de arquivo ZARC_JANELAS**, coerente com o teto de transferência comprovado; demais fontes não ganham aumento de limite.

## Segurança e semântica

- O catálogo canônico permanece `enabled=false`, `collection_authorized=false`, `runtime_enabled=false`, `scheduled_enabled=false`.
- `origem=REAL_AUTORIZADO` é bloqueada pelo livro-razão enquanto os gates canônicos estiverem desativados. Dados de teste usam `origem=SINTETICO`, que não representa aquisição autorizada de fonte real.
- Não há chave de API, download, nuvem, agendamento, modificação do projeto Google Cloud ou escrita real por esse módulo.
- Como staging não retém o CSV RAW integral, restauração do conteúdo original depende da recuperação externa do arquivo autorizado com o mesmo SHA.
- Os valores dec1..dec36 não são interpretados como probabilidades, janelas aprovadas ou previsão meteorológica. `Cod_Munic` SICOR não é tratado como igual ao `geocodigo` IBGE.
- `PRAGMA foreign_keys=ON`, FK diferida para inserção atômica, `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, testes de rollback, idempotência e restauração.

## Evidências verificadas

- [CI #39889714293](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39889714293): suíte offline passou após correção da integridade referencial.
- [CI #39889895820](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39889895820): suíte completa no HEAD da implementação passou.
- [Ensaio #39889892098](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39889892098): **27.918 linhas totalmente fictícias**, 142 identificadores artificiais, 1 edição e 2 datas de coleta, 27.918 linhas após backup/restauração, integridade SQLite `ok`, FKs `OK`, duração observada de 3,985 segundos. **Nenhuma linha dessa prova corresponde à base agrícola real.**

## Bloqueios para promoção

1. Revisar licenças CC BY, condições de armazenamento e obrigatoriedade de atribuição especificamente para o arquivo e histórico.
2. Interpretar oficialmente códigos dos 36 decêndios com legenda/metodologia e verificar riscos por ciclo/solo/clima/manejo.
3. Validar municípios reais contra base canônica IBGE e mapeamento separado para SICOR.
4. Implementar retenção RAW imutável, snapshots por versão, backups criptografados, teste de restauração real e idempotência na infraestrutura selecionada.
5. Criar migração controlada para banco operacional, validar custos zero/quotas e monitorar a atualização da fonte por diferença/hash. Sem habilitação automática.
6. Após esses gates e atualização do catálogo/autorização, testar uma carga real supervisionada antes de agendar consultas.

Estado: **STAGING_LOCAL_TESTADO_COM_DADOS_SINTETICOS**, não produção.
