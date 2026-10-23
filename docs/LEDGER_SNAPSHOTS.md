# NIVON — Ledger de snapshots por dataset

Implementação: \`src/nivon/registro_snapshots.py\`.

Registra **somente metadados** locais em SQLite. Não lê rede, não guarda arquivo bruto, não cria serviços, não agenda coletores e não aprova direito de publicação.

- Identidade: dataset do catálogo + SHA-256 original + versão de schema. Nova coleta de payload igual não cria novo snapshot; preserva a observação em outra data.
- Metadados: fonte, hash, tamanho, MIME, competência, referência, publicação (quando comprovada), coleta UTC com fuso, tipo sintético/real e referência de evidência de direitos.
- SINTETICO é o modo padrão. REAL_AUTORIZADO requer evidência e as duas operações COLETA e ARMAZENAMENTO explicitamente autorizadas; isso **não** autoriza redistribuição nem acesso ao endpoint.
- Mesma versão/hash com metadados divergentes falha; não corrigir datas por suposição. Qualidade dos registros numéricos permanece a cargo dos parsers específicos.
- A visão \`visao_asof\` filtra por corte de coleta **e** publicação, e exclui versões cuja publicação é desconhecida, para evitar contaminação em backtests.
- Compatível com \`backup_sqlite.py\` para snapshot local e restauração testada, mas **não representa backup remoto durável**.
- Uso futuro: registrar snapshots de APIs, TXT, CSV e XLS antes de promover uma edição à cadeia normalizada. Nunca gravar dados identificáveis de postos ANP ou empresas privadas em commits.
- Testes sintéticos: \`PYTHONPATH=src python -m unittest tests/test_registro_snapshots.py\` (ou \`unittest discover\`).

Os 86 datasets seguem desativados, até gate separado de direito por operação, amostra real, integração de parser, validação semântica, persistência e homologação de publicação.

## Gate central de ativação — 20/10/2026

Além da comprovação explícita de `COLETA` e `ARMAZENAMENTO` por operação e `evidencia_direitos`, o ledger **nega qualquer snapshot REAL_AUTORIZADO quando o dataset no catálogo não declara `enabled is True` E `collection_authorized is True`**. Esse controle é intencionalmente duplicado em relação aos coletores: novos adaptadores não poderão contornar a governança omitindo um gate local. Testes exercitam indicadores falsos, ausentes e valores `1` (que não substituem booleanos explícitos). É controle de execução, não certificação jurídica automática; edição indevida do catálogo também deve ser protegida por revisão humana.
