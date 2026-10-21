# NIVON — Conciliação segura dos dois históricos CONAB

Data: 21/10/2026. Área: Coletores e Engenharia de Dados.

## Descoberta verificada no código

O NIVON mantém dois storages da mesma fonte lógica `CONAB_PROGRESSO_SEMANAL`:

| Camada | Armazenamento | Hash da edição | Identidade temporal |
| --- | --- | --- | --- |
| Legado | `progresso_edicoes/progresso_coletas/progresso_observacoes` | `sha256_json` do JSON normalizado | `publicado_utc` + `coletado_utc` |
| Ledger NIVON | `nivon_snapshots/nivon_coletas/nivon_conab_progresso` | `sha256` dos bytes da origem **declarados** | `publicacao` (apenas data) + `coletado_utc`, observação mantém publicação completa quando disponível |

**Esses hashes não são intercambiáveis.** Mesmo com valores iguais, não
se demonstra que o arquivo-fonte seja o mesmo. Ambos são códigos de
desenvolvimento, sem RAW privado auditado, backup/restore e licença
operacional comprovada.

## Escopo da implementação

`src/nivon/conciliacao_progresso_stores.py` faz auditoria somente de
leitura, não grava, não migra, não liga redes, não usa credenciais. Lê
dois SQLite distintos existentes, exige esquema esperado, mesmo
dataset/fonte, JSON canônico sem chaves repetidas, URL oficial, UF,
operação, percentuais no intervalo [0,1], chave indexada compatível,
publicação não futura e timestamps de coleta com fuso.

Compara eventos somente se **URL oficial + cultura + safra + operação
+ UF + semana + captura UTC** coincidirem, evitando deduplicação
indevida entre edições e datas de aquisição diferentes.

Classificações:
- `VALORES_IGUAIS_NA_MESMA_CAPTURA_SEM_PROVA_RAW`: equivalência de
  conteúdo normalizado (não homologação física do arquivo).
- `DIVERGENCIA_VALORES_MESMA_CAPTURA`: divergência dos campos para a
  mesma chave/captura, bloqueia conciliação.
- `SOMENTE_LEGADO_NESTA_CAPTURA` / `SOMENTE_CANONICO_NESTA_CAPTURA`:
  não inferir remoção, lacuna real, nem copiar automaticamente.
- `SEM_CAPTURAS_PAREADAS_HISTORICO_NAO_CONCILIADO`:
  mesmo conjunto de chaves observado em instantes distintos não prova
  versões equivalentes.

A consulta pode receber cortes `--corte-coleta` e
`--corte-publicacao` (ambos instantes com fuso). Com corte de
publicação, registros sem publicação conhecida são excluídos e
contabilizados; nunca se gera retroativamente o conhecimento de uma
edição a partir de captura posterior.

## Execução em ambiente privado (offline)

```sh
PYTHONPATH=src python -m nivon.conciliacao_progresso_stores \
  --legado /dados/privados/progresso_legado.sqlite \
  --canonico /dados/privados/snapshots_nivon.sqlite \
  --corte-coleta "2026-10-21T12:00:00Z" \
  --corte-publicacao "2026-10-21T12:00:00Z" --resumo
```

A abertura é somente leitura (`mode=ro` e `query_only`); recusa
banco inexistente, symlink e schema não reconhecido. A auditoria limita
o volume de linhas; bases maiores exigem paginação e consolidação
por lotes, não truncamento silencioso. Resultados apresentam chaves,
status e até 30 exemplos, sem valores de percentuais ou conteúdo bruto.

## Decisão técnica

- **Nenhuma migração automática**, mesmo quando valores coincidirem.
- Preservar o contrato de snapshot bruto com SHA no ledger central
  como candidato ao caminho canônico, sujeito a análise independente.
- O mecanismo legado tem `evidence_id` e booleano de
  `direitos_confirmados`, que **não** dispensam validação documental
  de direitos por operação no catálogo central.
- Separar contagem de capturas, edições, linhas normalizadas e arquivos
  reais. Não somar os dois storages.
- Não usar séries sintéticas para gerar briefing, tendência ou previsão.
- Não usar timestamps históricos de primeira publicação sem evidência
  externa verificável; preservar nulos.

## Dependências antes de eventual migração

1. Homologar origem e direito de captura, armazenamento, derivação e
   redistribuição para a edição individual.
2. Validar vínculo RAW imutável -> SHA256 -> parser/versionamento ->
   registros transformados e reprocessáveis.
3. Cobrir todos os instantes/vintages (incluindo faltantes, revisões,
   eventos simultâneos, schemas antigos, e quantidades reais).
4. Implementar migração idempotente com backup/restauração independente,
   modo dry-run, relatório de diferenças, rollback e CI E2E.
5. Realizar auditoria independente e integrar com a PR #13, antes de
   habilitar agendamentos ou publicar.

**Escopo executado nesta rodada: código offline e testes com fixtures
sintéticas. Coletas reais executadas: zero. Migrações: zero.**

## Auditoria de integridade reforçada

Antes de comparar as capturas, o reconciliador também:
- verifica a existência de capturas para cada edição legada ou snapshot
  CONAB canônico, sem fabricar registros faltantes;
- identifica observações órfãs ou vinculadas ao dataset incorreto;
- confronta a contagem de observações de cada edição legada com
  `numero_linhas`;
- **recalcula o SHA-256 do JSON normalizado legado** a partir de todas
  as observações persistidas e recusa divergências, inclusive adulterações
  de valores e ausência de linhas;
- preserva a distinção fundamental: esse SHA do JSON **não**
  verifica o arquivo bruto, e a coluna canônica `sha256` segue sem
  confirmação externa dos bytes no presente relatório.

A verificação processa integralmente as edições até o limite configurado;
limite excedido resulta em erro, não amostragem silenciosa. O número de
edições com hash JSON recalculado é apresentado separadamente de
capturas e observações.
