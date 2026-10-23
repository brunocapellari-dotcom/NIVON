# IVO / PAM — Rodada 16: estado incremental, backup e restauração comprovados

**Execução:** 23/10/2026, 07h28–07h32 (MT), em PR #7 draft,
baseado no PR #1. **Sem merge, deploy, serviço pago ou treinamento
preditivo real.**

## Matriz de prioridades atualizada

| Prioridade | Implementação | Prova de integração |
|---|---|---|
| P0 | Consultas PAM/SIDRA reais com fonte e unidade correta | 6/6 reais por execução, já comprovado |
| P1 | SQLite com versões e múltiplos timestamps de coleta | 6→12→18 capturas reais do MESMO histórico |
| P2 | Conteúdo original, recibos SHA e painel anual IVO | Arquivo ZIP auditável e painel E2E |
| P3 | Backup integral SQLite+objetos+recibos, manifesto global | SHA de cada entrada, leitura e restore completos |
| P4 | Recuperar estado anterior ANTES da próxima coleta | GitHub Actions 39946544006 recuperou run 39946290744 |
| P5 | Bloqueio de ZIP corrompido, path traversal, histórico ausente, falha de coleta | Teste E2E com três ciclos e falhas induzidas |
| P6 | Copiar resultado real para Google Drive | Arquivo privado 18 capturas, metadados verificados |
| P7 | Agendar coleta e cópia externa automáticas | **PENDENTE**: PR não merged, Actions artifacts 30 dias, Drive sem credenciais de CI |
| P8 | Expandir fontes/municípios mantendo recortes comparáveis | **PENDENTE**: integrar atualização incremental às demais bases do NIVON |
| P9 | Backtest anual REAL as-of | **PENDENTE**: falta vintage pré-errata, não inferir dados do passado |

## Implementação

- `src/nivon/ivo_pam_backup.py`: auditoria prévia da quarentena +
  snapshot SQLite usando `sqlite3.Connection.backup`, ZIP portátil
  com manifesto SHA-256 de cada entrada, limites de expansão/número de
  objetos, importação segura em diretório novo, rejeição de symlinks e
  arquivos fora do contrato. Antes de publicar a restauração, audita
  **SQL, conteúdo JSON, recibos, unidade/município/ano e referência**.
  Suporta o ZIP antigo do primeiro piloto apenas com `permitir_legado=True`,
  sem supor que esse ZIP possuía manifesto global.
- `src/nivon/ivo_pam_ciclo.py`: execução `restaurar -> lote público
  -> auditar -> backup`, falhando quando um ZIP anterior for obrigatório
  e estiver ausente, quando uma consulta falhar ou quando a reconciliação
  dos arquivos não for aprovada. Capturas de nova execução têm instante
  próprio e são adicionadas ao SQLite recuperado.
- `tests/test_ivo_pam_continuidade_e2e.py`: teste integrado com três
  ciclos reais de SQLite local/quarentena e fixtures sintéticas de JSON,
  incluindo revisão 100→150, recuperação de histórico, mesmo SHA com
  nova captura, ZIP adulterado, sobrescrita proibida, path traversal,
  ZIP legado e falha de fonte sem substituir backup anterior.
- `.github/workflows/ivo-pam-piloto.yml`: restaura automaticamente
  artifact mais recente **de execução bem-sucedida da mesma branch**,
  importa o ZIP antigo do piloto apenas no bootstrap, executa seis
  consultas reais, compara capturas antigas/novas e publica backup com
  manifesto e relatórios por 30 dias.
- **Reforço de fail-closed:** se existir execução incremental anterior
  bem-sucedida com backup novo, a indisponibilidade/expiração desse
  backup provoca **falha**, em vez de fallback silencioso ao piloto
  antigo. O workflow não pode reiniciar o histórico sem estado confiável.
- O workflow executa em PR apenas quando seu próprio arquivo for
  alterado; `workflow_dispatch` permite solicitação explícita.
  Não há schedule ativo nem job de backup externo automatizado.

## Provas reais

1. [GitHub Actions 39946290744](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946290744):
   recuperou o ZIP **legado** de 6 capturas, efetuou seis consultas
   públicas e publicou estado com **12 capturas, 6 vintages, zero
   revisões numéricas**. Auditoria SQL/JSON/recibos aprovada.
2. [GitHub Actions 39946544006](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946544006):
   recuperou o **novo formato com manifesto** de
   `BACKUP_RECUPERADO=run-39946290744`, efetuou seis novas consultas
   reais, verificou e publicou estado com **18 capturas, 6 vintages,
   zero alterações dos valores, zero falhas de consulta**.
3. Houve falha de *shell quoting* no commit intermediário
   `a9acc338`, corrigida em `e32aa0ee`. O primeiro run
   dessa versão falhou; a versão corrigida passou.
4. [Testes locais 39946544007](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39946544007):
   **1.252 testes executados, 8 ignorados, 1.244 aprovados**.
5. Backup final baixado e analisado em ambiente separado:
   ZIP externo com `estado_pam.zip`, `resultado_ciclo.json` e
   `auditoria.json`; backup interno com manifesto
   `nivon_pam_backup_v1`, 25 arquivos verificados por SHA,
   `PRAGMA integrity_check=ok`, 6 linhas `pam_vintages` e
   18 linhas `pam_capturas`.
6. O GitHub artifact 12498417174 expira em **22/11/2026**.
   Cópia pontual preservada no Google Drive de uso do projeto,
   sem compartilhamento público:
   [NIVON PAM 18 capturas](https://drive.google.com/file/d/1zxar9mAzRrnuyS8HLnxrNE74zj3crVJS/view?usp=drivesdk).
   Upload e metadados confirmados. A API do Drive conectada ao ChatGPT
   **não dá automaticamente credenciais ao GitHub Actions**: a cópia
   automática permanece PENDENTE.

### Comando de ciclo integrado

```bash
PYTHONPATH=src python -m nivon.ivo_pam_ciclo \
  --anterior estado_pam_anterior.zip \
  --modo PUBLICO_IBGE \
  --tarefas config/ivo_pam_piloto_mt.v1.json \
  --saida saida_proximo_ciclo
```

A primeira importação do artifact legado exige `--legado`. Repetições
normais usam apenas backups versionados com manifesto SHA.

## Limites editoriais e científicos

As seis vintages representam **edições do SIDRA capturadas em
outubro de 2026**; 18 capturas repetidas NÃO são 18 versões distintas
nem comprovam o conteúdo de 2021 publicado em 2021. Progresso
operacional não significa performance preditiva histórica. As
estatísticas da PAM são **anuais**; o sistema não as transforma em
safra CONAB ou produção mensal. Sem versões efetivamente arquivadas
antes da errata, um benchmark anual estritamente as-of continua
impossível para aquele evento.

## Próxima ação autônoma prioritária

1. Integrar ao storage durável aprovado (Drive/cloud sob credenciais
   específicas), automatizando **cada** backup após auditoria e
   verificação de leitura. Não usar os 30 dias do artifact como única
   persistência.
2. Preparar recorrência de coleta controlada pela cadência da PAM
   e alertas somente quando houver mudança real de SHA/valor/unidade.
3. Expandir catálogo de tarefas municipal por demanda e normalizar
   a exportação do IVO para demais motores sem reclassificar
   `INFORMADO_PAM_ANUAL` como `OBSERVADO` material.
4. Recuperar vintages oficiais antigas e suas datas de publicação
   se o objetivo for benchmark retrospectivo antes das erratas.
5. Nenhum merge, deploy, gasto ou alteração de fonte privada sem
   autorização específica; manter PR #7 em draft.
