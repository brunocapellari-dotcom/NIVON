# NIVON — Histórico auditável das referências de programação PDF

Data de referência: **21/10/2026**. Estado do trabalho: **testado somente com documentos e dados sintéticos**; direitos de fontes e publicação pendentes, sem merge ou deploy.

## Problema resolvido

Em Paranaguá, uma tabela pode ter **Nº Prog**, data/hora da chegada prevista, carga, navio e terminal, mas não conter o **DUV**. Nº Prog é uma referência de programação da fonte, **não é identidade universal da viagem nem da escala**. Usá-lo como DUV criaria visitas fictícias e poderia duplicar embarcações em múltiplas linhas de produto. Itaqui também pode trazer programação sem DUV explícita.

O fluxo mantém duas camadas independentes:

| Camada | Registro | Pode contar como escala com DUV? | Realização de embarque? |
| --- | --- | --- | --- |
| Referências PDF | `PdfProgrammeEdition` e `PdfProgramReference`, inclusive linhas incompletas | **Não** | **Não** |
| Programação identificada | `LineupVintage` com DUV, ETA, prova temporal e sem linhas excluídas | Somente **escala programada**, não realizada | **Não** |
| Operação realizada | Fonte oficial operacional autenticada, DUV/porto vinculados, eventos e licenças específicas | Exige reconciliação independente | Exige prova própria |

Os campos `programme_pdf_rows` e `programme_numbers_declared` não são métricas de navios, atracações, carregamentos ou movimentação. Duas linhas de soja/milho com mesmo Nº Prog continuam **duas linhas declaradas e uma referência de programa**, sem contagem de visitas. `verified_port_call_count`, `actual_arrivals` e `realized_volume_t` são **null**, nunca zero estimado.

## Artefatos e contratos

- `official_lineup_bridge.py`: `pdf_program_rows`, `pdf_series`. Reaproveita parser e conferência de URL, MIME, SHA-256 dos bytes e controle de coleta já existente; produz estado `SHADOW_NOT_HOMOLOGATED`.
- `pdf_programme_ledger.py`: `edition_from_pdf_bridge`, `PdfProgrammeEdition`, `PdfProgrammeLedger`, `ProgrammeAsOf`. Usa **mesma conexão SQLite** de `MaritimeStore`, mas tabela separada `maritime_pdf_programme_editions` com identidade `(porto, fonte, série, data_coleta UTC)` e trava contra alteração de versão.
- `maritime_store.py`: `validate_restore` conta separadamente `pdf_programme_edition_rows`. Backup existente protege consistência SQLite local, **não** representa backup remoto/criptografado homologado.
- `tests/test_maritime_pdf_programme_ledger.py`: 26 testes sintéticos para integridade, idempotência, datas, segregação, direitos por chamada e backup.
- `tests/test_maritime_pdfplumber_e2e.py`: 11 testes com **arquivos PDF sintéticos válidos**, gerados na hora por ReportLab e efetivamente extraídos pelo `pdfplumber`; os casos Paranaguá/Itaqui sem DUV percorrem o caminho PDF → bridge → ledger → consulta as-of.

Os direitos de **armazenamento e leitura** são explicitamente bloqueados por padrão. `storage_authorized`/`read_authorized` são apenas controles técnicos; a verificação da licença e autorização **não** é criada por esses booleans. A origem precisa ser HTTPS do domínio previsto para o respectivo porto. Nenhum arquivo PDF bruto real foi introduzido na base ou no GitHub.

## Governança de quatro datas

A edição preserva: `competencia` (mês), `data_referencia`, `data_publicacao` comprovada por evidência, `data_coleta` com fuso explícito, `source_sha256`, URL e nome da fonte.

A consulta `as-of` só considera edição **publicada e coletada** antes do corte. Edição cuja data de publicação é desconhecida pode ser preservada para auditoria **se autorizada**, mas não retorna como histórico comprovadamente conhecido naquele instante.

O ledger aceita republicações em novos momentos de coleta, proíbe sobrescrever a edição do mesmo instante com payload divergente e verifica a identidade derivada e checksum na releitura. Hash prova integridade do payload **dentro do banco**, não autentica o publicador nem impede um adversário com controle total do arquivo SQLite de adulterar todas as evidências.

## Critérios externos ainda faltantes

1. **Três edições reais por fonte/série** obtidas legalmente, com bytes originais, hashes, páginas verificadas visualmente e permissão de retenção.
2. Comprovação das quatro datas e da origem exata. Não inferir publicação por título do PDF, caminho, relógio do servidor, data de coleta ou snapshot de um buscador.
3. Identificar formalmente se **Nº Prog** é estável por série/edição, por lote, por agência ou por navio; documentar eventual mecanismo oficial que vincule Nº Prog a DUV. Não unir registros por IMO/nome sem evidência.
4. Conferir múltiplas linhas de mercadoria por programa sem somá-las como embarques reais; validar alterações e exclusões em edições posteriores.
5. Licença AIS independente, homologação de identidade e geofences, validação do ETA/filas fora da amostra, segurança e 7 dias de aceite operacional antes de considerar release.

## Evidência automatizada

A execução anterior à inclusão deste documento, no commit de código `8026708ddcfa533f79ce0ff6f3260ebec0b3a2b9`, foi:

- [GitHub Actions — suíte geral](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39664053136): **1.180 testes**, 16 ignorados (11 em job PDF separado), nenhuma falha.
- Mesmo run, job `validar-pdf-maritimo-offline`: **11/11 aprovados**.
- [GitHub Actions — cockpit marítimo](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39664053149): **sucesso**, somente build.
  
**Estado:** `CODE_TESTED_SYNTHETIC_ONLY` / `RIGHTS_NOT_HOMOLOGATED` / `REAL_DATA_GATED` / `RELEASE_BLOCKED`. Nenhum merge, deploy, scraping, AIS produtivo ou compra foi realizado.
