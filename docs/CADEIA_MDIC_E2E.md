# MDIC — cadeia comprovável de bytes (somente teste sintético)

O transferidor `mdic_aquisicao` entrega um SHA-256 dos bytes originais. O parser `mdic_stream` calcula SHA nos mesmos bytes que consome ao gerar os agregados. `ingestao_mdic.ingerir_arquivo_mdic(...,sha256_esperado=...)` compara ambos **antes de registrar os dados no ledger**. Modo `REAL_AUTORIZADO` não admite SHA esperado omitido.

A suíte `test_pipeline_mdic_e2e.py` testa sem rede: índice MDIC simulado, download streaming falso, arquivo privado versionado, parsing de NCM e FOB/quilogramas, consulta as-of, backup/restore, repetição idempotente e arquivo modificado entre transferência e parsing. Testes não conferem fonte real, direitos oficiais, completude do histórico ou totais oficiais. É necessário homologar tudo antes de produção.
