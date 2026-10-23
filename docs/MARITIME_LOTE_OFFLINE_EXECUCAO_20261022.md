# NIVON — Pipeline marítimo executável em lote (22/10/2026)

**Status:** código integrado testado em fixtures sintéticas. **Não homologado com PDFs oficiais reais**; direitos por fonte/uso pendentes; execução automática e publicação **bloqueadas**. PR #132 (stack sobre #114).

## Prioridades e entregas desta rodada

| Ordem | Execução | Conclusão verificável |
|---|---|---|
| P0 | Lote atômico de edições PDF Paranaguá/Itaqui | `PdfProgrammeLedger.save_batch`: valida todas; uma transação SQLite; rollback se qualquer versão conflitar |
| P0 | Pipeline unificado sem I/O de rede | `run_offline_pdf_batch`: extrai bytes PDF → autoridade → ponte → edição → histórico → comparações → auditoria JSON |
| P0 | Comando único com manifest | `scripts/maritime_pdf_batch.py`; preview em `:memory:` por padrão; armazenamento só mediante `--commit --ack-rights --db` |
| P1 | Rastreabilidade editorial | Fonte, SHA, competência, data de referência/publicação/coleta, proveniência, números de programação, linhas excluídas, mudanças ETA/volume/produto, ambiguidades |
| P1 | Segurança e idempotência | SHA original exigido, arquivos locais dentro do diretório do manifest, domínio oficial, limite de memória/documentos/páginas/tabelas/linhas/células, conflito sem sobrescrita |
| P2 | Teste ponta a ponta | PDFs sintéticos binários verdadeiros → `pdfplumber` → lote → SQLite → reprocessamento → relatório; testes de falha, backup histórico e bloqueio de direitos |
| EXTERNO | Homologação real e publicação | **Não executado**: amostras originais autorizadas, revisão externa de Nº Prog/DUV, licenças e condições de distribuição |

## Como executar

Ambiente de desenvolvimento Python 3.11+, a partir da raiz do repositório:

```bash
python -m pip install -e '.[ports]'
PYTHONPATH=src python scripts/maritime_pdf_batch.py \
    ./dados_autorizados/manifest.json \
    --as-of 2026-10-22T18:00:00-04:00 \
    --report ./auditoria_lote_01.json
```

Por padrão, **não grava no SQLite**: processa os arquivos existentes e emite relatório de auditoria. O manifest e os PDFs devem estar em diretório local autorizado, jamais repositório público.

Somente quando houver **verificação externa documentada** de direitos para **processamento, leitura derivada e retenção**, e o operador concordar com armazenamento, o mesmo lote pode ser executado com:

```bash
PYTHONPATH=src python scripts/maritime_pdf_batch.py \
    ./dados_autorizados/manifest.json \
    --as-of 2026-10-22T18:00:00-04:00 \
    --commit --ack-rights \
    --db ./estado_local/maritimo.sqlite \
    --report ./auditoria_lote_02.json
```

**Estas linhas são instruções, não execução real.** Nenhuma fonte foi coletada, licenciada, armazenada ou publicada por esta PR. A opção `--ack-rights` é uma declaração humana, **não é prova técnica nem licença concedida automaticamente**.

Manifest de referência: `config/maritime_pdf_batch.example.json`. Ele é **intencionalmente bloqueado** (`rights_status=PENDING`, `sha256` fictício e caminho não existente) para evitar ingestão inadvertida. Substituir todos os campos com dados comprovados somente após revisão das condições da fonte. Cada objeto em `documents[]` possui:

- `port_id`: `PARANAGUA` ou `ITAQUI`; `series` obrigatória para Paranaguá e nula para Itaqui;
- `source_id`, `source_url`: fonte institucional exata e URL HTTPS idêntica à origem do arquivo;
- `file`: arquivo `.pdf` **relativo ao diretório do manifest**, sem acesso a diretórios superiores;
- `sha256`: digest do **PDF original** de 64 hex; não aceitar valor fornecido sem confrontar bytes;
- `reference_date`: data documental ISO; `collected_at` timestamp com fuso;
- `published_at` e `publication_evidence_id`: ambos quando existem provas independentes; caso desconhecidos, ambos nulos e a edição **não entra no as-of**;
- `rights`: `rights_status=ATTESTED`, `evidence_reference`, `reviewed_by`, `offline_processing`, `read_derived`, `store_derived`; verificação real permanece responsabilidade da revisão externa.

A CLI lê até 24 arquivos por lote (máximo 20 MB por PDF; 80 MB no lote), JSON de manifest até 250 KB, páginas até 60 por documento, tabelas até 300, linhas até 12 mil e células até 240 mil. Limites barram abusos comuns, **não substituem isolamento de processos/limites de CPU, RAM e tempo** para PDFs não confiáveis. Não há download, scraping, proxy, redirecionamento, cron ou processamento em nuvem.

## Saída e semântica de negócio

`documents[]`: status declarativo por edição; `document_known_as_of` mostra somente se **data de publicação provada e coleta** são anteriores ao corte. `programme_numbers_declared` **não é número de navios**. `excluded_as_port_call` são linhas que não fornecem identidade de escala segura.

`revisions[]`: compara edições do mesmo porto/fonte/série **somente na mesma data de referência**; divergências entre datas produzem `REFERENCE_DATE_BOUNDARY_NO_ID_CONTINUITY` (mudanças nulas), nunca movimento, cancelamento ou saída. Duas mercadorias com Nº Prog compartilhado não geram automaticamente duas escalas; produtos repetidos não são associados por posição. Histórico incompleto ou desconhecido não é preenchido com zero.

Campos obrigatoriamente conservadores: `port_call_count=null`, `realized_tonnes=null`, `arrivals_confirmed=null`, `canonical_duv_links_allowed=false`, `publication_allowed=false`, `external_rights_verified_by_software=false`, `source_homologation_status=NOT_HOMOLOGATED`.

O módulo de dossiê **Nº Prog → DUV** pode ser consumido no campo `programme_duv_evidence[]`; uma relação formal ainda é apenas `CANDIDATE_READY_FOR_EXTERNAL_VERIFICATION`, sem liberar vínculos canônicos.

## Recuperação e auditoria

1. Se o parser de qualquer PDF falhar, nada do lote é gravado (pré-validação antes do `save_batch`).
2. Se uma versão histórica colidir com outra do mesmo porto/fonte/série/instante, a **transação SQLite completa reverte**; versões preexistentes ficam intactas.
3. Reprocessar o mesmo lote é idempotente (`already_present` aumenta; `inserted` permanece 0); não sobrescrever a edição original.
4. `PdfProgrammeLedger.history_asof` consulta somente edições temporalmente disponíveis. Não há corte silencioso de histórico; consulta com mais de 200 edições por fonte/série exige futura paginação explícita.
5. Arquivo de relatório JSON só pode ser criado em caminho novo; pré-validar direitos e caminho antes de criar SQLite. **Não existe transação conjunta entre SQLite e arquivo JSON**: se a escrita do relatório falhar depois do commit, auditar o banco e reexecutar idempotentemente com novo caminho.
6. `MaritimeStore.backup` e `validate_restore` estão disponíveis sob autorização local explícita; **nenhum backup remoto, criptografia gerenciada, IAM produtivo ou disaster recovery real foi homologado**.

## Matriz de validação

Testes sem acesso a autoridade ou rede:

- `tests/test_maritime_offline_batch.py`: 15 testes integrados em memória, inclusive rollback parcial simulado, múltiplos portos, idempotência, direitos por operação, histórico previamente gravado, corte temporal e datas incomparáveis.
- `tests/test_maritime_pdfplumber_e2e.py`: 24 testes dedicados com bytes PDF sintéticos válidos; execução real do `pdfplumber`, comando CLI, commit/replay, proteção contra path traversal, hashes falsos, arquivo de auditoria existente e limites de páginas/linhas.
- O job CI dedicado instala versões de teste fixadas de `pdfplumber` e `reportlab`, mas a execução do NIVON não inclui instalação automática ou download de PDFs de autoridade.
- Suíte Python geral, jobs de teste de PDF e build do cockpit devem **estar verdes no commit final**. Não extrapolar `CI verde` para `SOURCE_HOMOLOGATED`.

## Próxima fila técnica

1. Com amostras autorizadas, habilitar extração **somente em processo isolado**, com timeout, cotas e neutralização de arquivos não confiáveis.
2. Realizar homologação por porto/série e três edições oficiais, verificando colunas, páginas, DUV e Nº Prog, horários, link original e direitos.
3. Se existir crosswalk oficial Nº Prog ↔ DUV, testar com dados originais revisados; sem isso, manter camadas separadas.
4. Conectar o pipeline a uma agenda de coletas **apenas depois** da permissão comprovada de cada fonte e revisão de custos/infraestrutura, sem publicar dados sob direito não conferido.
5. Consolidar e revisar os PRs empilhados com responsáveis, integração e gates; não mesclar automaticamente a branch `main` antes da homologação.

**Release: BLOCKED.** A execução sintética de CI é um teste de código, não produção operacional.
