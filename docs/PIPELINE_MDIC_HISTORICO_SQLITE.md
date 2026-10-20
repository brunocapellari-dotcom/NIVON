# MDIC — ingestão local de agregados e histórico de versões

`src/nivon/ingestao_mdic.py` conecta o leitor anual `mdic_stream.py` ao ledger SQLite e guarda **somente recortes agregados e controles mensais**, não o arquivo original. O CSV local é processado e hasheado no momento de ingestão, com janela/código NCM8 ou SH4 explicitamente selecionados. A referência `SHA-256` identifica a versão do CSV; uma nova edição do mesmo ano não sobrescreve a antiga.

O ledger amplia **apenas** os datasets `MDIC_COMEX_NCM` e `MDIC_COMEX_MUNICIPIO_SH4` para arquivos de até 1,5 GB (metadata-only). Dados sintéticos por padrão, excluídos das consultas operacionais; `REAL_AUTORIZADO` exige gates do catálogo mais direitos de coleta/armazenamento e evidência. A mesma versão com filtro diferente é conflito, pois o resultado agregado é específico de uma seleção. Se novos filtros de produto forem necessários, gerar nova extração com contrato explícito de versão de transformação em vez de alterar silenciosamente o agregado.

A consulta `observar_mdic_asof_coleta` reconstrói apenas o que já fora **coletado**, não o que foi publicado oficialmente. Publicação desconhecida permanece nula. Todo resultado permanece `dados_homologados=False` e `publicacao_permitida=False`.

Teste E2E sintético inclui alterações de vintage, ausência em cortes antigos, idempotência, bloqueio de dados reais quando catálogo desativado e backup/restauração SQLite local. Não há backup remoto em nuvem, agenda, download, merge ou deploy neste módulo.
