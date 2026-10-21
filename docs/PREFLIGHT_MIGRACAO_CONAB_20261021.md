# NIVON — Pré-voo controlado da migração CONAB (21/10/2026)

## Problema e decisão

Duas representações históricas coexistem para `CONAB_PROGRESSO_SEMANAL`:
`progresso_store` (SHA-256 do JSON normalizado) e
`progresso_conab_historico` (SHA-256 do arquivo bruto **informado**).
Esses hashes não são equivalentes e as bases não podem ser somadas nem
migradas automaticamente.

**Decisão implementada:** criar um _preflight_ estritamente somente leitura
para validar a documentação por edição legada e mapear divergências do
ledger existente. **Não inclui executador de migração.**

## Contrato offline do manifesto

Formato: objeto JSON com `schema=NIVON_CONAB_PREFLIGHT_V1` e `edicoes`
(lista de até 500 registros). Cada registro precisa ter exatamente:

| Campo | Propósito |
| --- | --- |
| `legacy_id` | ID existente em `progresso_edicoes.id` |
| `sha256_json` | Hash do **JSON normalizado legado** |
| `url_origem` | URL oficial da edição, igual à existente no legado |
| `raw_path` | Caminho **local absoluto** do RAW capturado, sem symlink |
| `raw_sha256` | Hash do **arquivo RAW**, distinto do hash JSON |
| `raw_bytes` | Tamanho real do arquivo |
| `raw_mime` | MIME validado localmente (XLS, XLSX, PDF, CSV, TXT) |
| `replay_json_path` | JSON de saída do parser **fornecido externamente**, sem provar seu vínculo com RAW |
| `parser_versao` | Identificador declarado da versão do parser, não uma certificação |
| `direitos_evidencia_id` | Referência declarada da evidência jurídica, não uma licença verificada |

**Exemplo de esquema (caminhos não reais):**

```json
{
  "schema": "NIVON_CONAB_PREFLIGHT_V1",
  "edicoes": [
    {
      "legacy_id": 1,
      "sha256_json": "<64 caracteres hexadecimais do JSON normalizado>",
      "url_origem": "https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/edicao-exemplo",
      "raw_path": "/dados/privados/conab/edicao-exemplo.xlsx",
      "raw_sha256": "<64 caracteres hexadecimais do arquivo bruto>",
      "raw_bytes": 54321,
      "raw_mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "replay_json_path": "/dados/privados/conab/replay-exemplo.json",
      "parser_versao": "PARSER-CONAB-REV-1",
      "direitos_evidencia_id": "DOC-PENDENTE-ANALISE"
    }
  ]
}
```

Os valores entre `< >` são *placeholders* e serão rejeitados na validação.
`replay_json_path` precisa conter uma lista de observações normalizadas
seguindo o contrato CONAB existente; a coluna `coleta`, se existir,
é removida antes de comparar o conteúdo, pois pertence ao ledger de
capturas.

## Execução segura

```sh
PYTHONPATH=src python -m nivon.preflight_migracao_conab \
  --legado /dados/privados/progresso_legado.sqlite \
  --canonico /dados/privados/ledger_nivon.sqlite \
  --manifesto /dados/privados/conab/preflight.json --resumo
```

Todos os bancos são abertos com SQLite `mode=ro` e `query_only=ON`;
não se criam bancos inexistentes. Nenhuma conexão de rede. O RAW e o
replay são lidos localmente, com rejeição de symlink, verificação MIME,
hash e tamanho, limites de 20 MB por RAW e de 20.000 observações legadas.
O módulo confronta cada edição com o ledger usando o **SHA RAW**, sem
confundir seus hashes; se o SHA já existir mas contiver valores diferentes,
falha imediatamente. Revisions usam IDs distintos e não são colapsadas.

Estados possíveis:
- `SEM_MANIFESTO_RAW`: edição histórica sem prova local;
- `RAW_E_REPLAY_LOCAIS_CONFERIDOS_SEM_PROVA_DO_PARSER`: bytes e
  reprocessamento informado internamente consistentes com o legado,
  sem prova da cadeia RAW → parser;
- `SHA_RAW_PRESENTE_NO_CANONICO_CONFERIR_CAPTURAS`: o hash bruto
  também consta no ledger e as observações coincidem, mas os instantes
  de captura e demais permissões requerem conciliação externa.

**O módulo nunca registra uma migração apta**. Mesmo com manifestos
inteiramente validados, `migracao_permitida=false`,
`pronto_para_migracao=false`, `backup_verificado=false`,
`restauracao_testada=false` e
`direitos_coleta_armazenamento_derivacao_publicacao_verificados=false`.
Um caminho local, uma URL oficial, uma cadeia de SHA consistente e um
identificador de direitos **não provam** que o parser gerou o resultado
a partir daquela fonte, nem que direitos comerciais foram obtidos.

## Próximos requisitos antes de migrar de verdade

1. Reproduzir a extração a partir dos bytes brutos com parser fixado por
   versão/revisão, hash da saída e evidência auditável de execução.
2. Registrar licença e permissão por operação (coleta, armazenamento,
   transformação, distribuição), com revisão independente.
3. Construir matriz das capturas temporais de cada edição e de todas as
   revisões, distinguindo publicação, competência, referência e coleta.
4. Implementar backup consistente dos dois SQLite e teste documentado de
   restauração/rollback, com verificação SHA e `PRAGMA integrity_check`.
5. Somente então projetar um executor de migração idempotente, com plano
   de batches, controle transacional, dry-run e suíte E2E autorizada.

**Estado desta PR:** código e testes sintéticos offline, sem RAW real,
migração, merge, deploy, custos ou ativação de coleta.
