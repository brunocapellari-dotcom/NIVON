# NIVON R12 — Ponte incremental para RAW GCS sem promoção analítica

**Data:** 23/10/2026. **Base:** [R11 #185](https://github.com/brunocapellari-dotcom/NIVON/pull/185). **Implementação:** [R12 #217](https://github.com/brunocapellari-dotcom/NIVON/pull/217).

## Entregue em código

- **Reuso, sem reinvenção:** foram incorporados à branch R11, pelos mesmos hashes Git da `main` atual, os módulos `ingestao_fontes_reais`, `arquivo_raw_gcs`, `lote_cloud_recuperavel` e `carga_bigquery_fontes`, além de suas três suítes de regressão. O primeiro par prepara uma base de snapshots RAW locais idempotentes compatíveis com a estrutura futura de objetos GCS.
- **Nova ponte:** `src/nivon/ponte_incremental_raw_gcs.py` lê versões **já persistidas e auditadas** dos bancos locais da R11; checa a integridade semântica do histórico, a identidade de cada edição e o SHA dos arquivos privados, preservando suas revisões.
- **CONAB:** os bytes vêm dos XLSX de referência do **repositório agrobr de terceiros fixado por commit**, não de resposta HTTP diretamente confirmada na CONAB. O dataset é `CONAB_AGROBR_TERCEIRO`; a URL de proveniência aponta para a referência de terceiro realmente usada.
- **Argentina:** RAW obtido previamente por meio autorizado, catalogado por `sha256` e recurso SAGyP, dataset `ARG_SAGYP_QUARENTENA`. A ausência de prova de publicação não é substituída por data de coleta.
- **Controle de promoção:** os dois datasets têm estado `QUARANTINED`, **zero registros na tabela `observacoes`**. O preparador de lote BigQuery não aceita snapshots desse estado. A ponte rejeita estágio existente com registros analíticos, datasets desconhecidos ou snapshot previamente alterado para `NORMALIZED`.
- **GCS:** `preparar_manifesto` retorna apenas contagens, identificadores e destino futuro. Upload foi executado **somente em cliente falso no teste**, com prova de idempotência, sem autenticação, internet ou cobrança. Nenhum upload real é realizado pelo adaptador.

## Operação local

Modo sem escrita por padrão:

```bash
PYTHONPATH=src python -m nivon.ponte_incremental_raw_gcs \
  --stage-dir /pasta-privada/stage \
  --stage-banco /pasta-privada/stage/quarentena.sqlite \
  --bucket nivon-raw-archive \
  --argentina-manifesto /pasta-privada/argentina-manifesto.json \
  --argentina-banco /pasta-privada/argentina.sqlite \
  --argentina-raw-dir /pasta-privada/raw-argentina \
  --conab-manifesto /pasta-privada/conab-manifesto.json \
  --conab-banco /pasta-privada/conab-lab.sqlite \
  --conab-raw-dir /pasta-privada/raw-conab
```

Somente após comprovar **direitos efetivos de arquivamento por fonte e conteúdo**, usar `--executar --direitos-arquivamento-verificados`. Isso grava o estágio **local**, não no GCS, e nunca promove publicações ao BigQuery. Todos os diretórios existentes de origem/estágio precisam ser privados (0700 no POSIX), com bancos e arquivos 0600, sem symlinks.

## Contratos de aceitação

1. Duas fontes com RAW íntegro e databases de origem válidos → dois snapshots distintos, nenhum registro analítico, manifesto GCS offline com dois objetos.
2. Repetição e revisão → reprocessamento idempotente por `dataset_id + sha256` e preservação de versões sem sobrescrita.
3. XLSX terceiro adulterado, CSV alterado, histórico SQLite modificado, dataset não autorizado ou conteúdo antigo promovido → negar antes da promoção; não copiar arquivo inválido para cloud.
4. Falha no preflight de qualquer uma das fontes → não criar staging novo. **Não há atomicidade entre escrita RAW em disco e SQLite após o preflight**; em falhas de disco, retry idempotente e reconciliação são obrigatórios.
5. Fluxo sem `executar` ou sem direitos explicitamente verificados → nenhum staging escrito. Mesmo com os dois flags verdadeiros, **GCS e BigQuery permanecem desligados**.
6. Proteger contra divergência de calendário, direitos, fonte e estado epistemológico. O operador não infere competência/publicação da data de coleta.
7. Nenhuma linha QUARANTINED participa de relatório, precificação, previsão, backtest ou briefing até auditoria e promoção controlada em estágio de governança separado.

## Gaps e próximos gates

- O código da R12 não prova que o bucket GCS ou dataset BigQuery existam, estejam livres de cobrança, tenham IAM adequado ou storage imutável/retention configurado.
- A **`main` recebe os módulos de GCS**, mas a R11/R12 permanece **PR draft** não incorporada à main; a convergência final precisa de merge/rebase cuidadoso para não descartar projetos de outra frente.
- A próxima fase deve implementar recibos/provas de direitos com autoria verificável e agendamento somente após operacionalização do Google Cloud com credenciais limitadas, isolamento de lotes e orçamento explicitamente aprovado.
- **CEPEA e IMEA** ainda dependem de direitos claros de coleta e redistribuição e de endpoints homologados para sincronização automática. Importação local autorizada não é feed vivo.
- Bloqueios transversais ainda incluem a proteção da branch `main`, auditoria de egress independente e triagem de vulnerabilidades da imagem Docker.

**Evidência:** PR #217 contém testes com cliente GCS simulado, falhas adversariais (RAW/histórico/stage) e ensaio de bloqueio BigQuery. A comprovação de CI deve sempre usar o **SHA final da PR**, sem contar testes sobre commits anteriores como aprovação da versão mais recente.
