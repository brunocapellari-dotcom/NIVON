# Triagem técnica das PRs abertas — 26/10/2026

**Relatório para aprovação, não autorização de fechamento.** Critério primário: lista de arquivos alterados e função inferida de caminhos; títulos não determinam a classe. Uma PR empilhada sobre outra não é duplicada automaticamente. A confirmação de INCORPORADA exige confronto com `main` e de DUPLICADA exige prova de equivalência; na dúvida conservar como ÚTIL para revisão.

## Tabela de classificação preliminar

| PR | Classe preliminar | Frente | Evidência de arquivos e função | Base |
|---|---|---|---|---|

| [#335](https://github.com/brunocapellari-dotcom/NIVON/pull/335) | ÚTIL | F4 | 3 arquivo(s): `config/fontes.yaml`, `config/gerar_fontes.py`, `docs/FONTES.md` | `main` |
| [#330](https://github.com/brunocapellari-dotcom/NIVON/pull/330) | ÚTIL | F1 | 2 arquivo(s): `docs/CATALOGO_FERRAMENTAS_IA_P1_P2_20261026.md`, `docs/integracoes_ia_nivon.md` | `main` |
| [#324](https://github.com/brunocapellari-dotcom/NIVON/pull/324) | ÚTIL | F2 | 8 arquivo(s): `.github/workflows/nivon-terminal-go-live.yml`, `docs/M1_ROTEIRO_BRUNO_IAP_ANTT.md`, `scripts/deploy_terminal_privado.sh`, `scripts/smoke_terminal_container.py`, … | `main` |
| [#323](https://github.com/brunocapellari-dotcom/NIVON/pull/323) | ÚTIL | F1 | 2 arquivo(s): `README.md`, `STATUS_NIVON.md` | `main` |
| [#320](https://github.com/brunocapellari-dotcom/NIVON/pull/320) | ÚTIL | F2 | 21 arquivo(s): `.github/workflows/ci-terminal-web.yml`, `.github/workflows/mercado-portal-ci.yml`, `.github/workflows/nivon-terminal-ci.yml`, `.github/workflows/nivon-terminal-go-live.yml`, … | `main` |
| [#305](https://github.com/brunocapellari-dotcom/NIVON/pull/305) | ÚTIL | F2 | 7 arquivo(s): `.github/workflows/piloto-go-live-ptax.yml`, `docs/GO_LIVE_MVP_CAMINHO_CRITICO_20261025.md`, `src/nivon/painel_local_mvp.py`, `src/nivon/piloto_ptax_readonly.py`, … | `integration/nivon-auditoria-20261020` |
| [#302](https://github.com/brunocapellari-dotcom/NIVON/pull/302) | ÚTIL | F2 | 5 arquivo(s): `AGENTS.md`, `docs/EXECUCAO_UNIFICADA_NIVON.md`, `docs/NIVON_BACKLOG_EXECUCAO.json`, `src/nivon/backlog_cloud.py`, … | `main` |
| [#246](https://github.com/brunocapellari-dotcom/NIVON/pull/246) | ÚTIL | F2 | 24 arquivo(s): `.github/CODEOWNERS`, `.github/workflows/coleta-recorrente-fontes.yml`, `.github/workflows/maritimo-gcp-api-bootstrap.yml`, `.github/workflows/monitor-p0-operacao.yml`, … | `main` |
| [#221](https://github.com/brunocapellari-dotcom/NIVON/pull/221) | ÚTIL | F5 | 69 arquivo(s): `config/fontes_nivon_master.v1.json`, `config/integracao_historicos_meteo_hidro.v1.json`, `config/integracao_meteo_hidro.v1.json`, `config/motores_inteligencia.v1.json`, … | `integration/nivon-auditoria-20261020` |
| [#217](https://github.com/brunocapellari-dotcom/NIVON/pull/217) | ÚTIL | F2 | 10 arquivo(s): `docs/INTEGRACAO_INCREMENTAL_RAW_GCS_R12_20261023.md`, `src/nivon/arquivo_raw_gcs.py`, `src/nivon/carga_bigquery_fontes.py`, `src/nivon/ingestao_fontes_reais.py`, … | `integration/nivon-r11-incremental-conab-argentina-20261023` |
| [#216](https://github.com/brunocapellari-dotcom/NIVON/pull/216) | ÚTIL | F2 | 5 arquivo(s): `.github/workflows/testes.yml`, `docs/RECUPERACAO_ISOLADA_CONAB_LAB_20261023.md`, `scripts/validar_retificacoes_conab_ci.py`, `src/nivon/recuperacao_isolada_conab_lab.py`, … | `feat/dados-retificacoes-lineagem-conab-lab-20261023` |
| [#215](https://github.com/brunocapellari-dotcom/NIVON/pull/215) | ÚTIL | F2 | 7 arquivo(s): `.github/workflows/testes.yml`, `docs/MARITIME_HISTORICO_ACUMULADO_E_FONTES_CANDIDATAS_20261023.md`, `src/nivon/maritime/offline_pdf_batch.py`, `src/nivon/maritime/pdf_programme_ledger.py`, … | `feat/maritime-container-smoke-homologation-dossier-20261023` |
| [#214](https://github.com/brunocapellari-dotcom/NIVON/pull/214) | ÚTIL | F4 | 8 arquivo(s): `config/motores_inteligencia.v1.json`, `docs/INTEGRACAO_FONTES_ZIP_INMET_ANA_20261023.md`, `src/nivon/arquivo_zip_integral.py`, `src/nivon/fontes_hidro_entrada.py`, … | `feat/meteo-hidro-inmet-ana-pipeline-horario-20261023` |
| [#212](https://github.com/brunocapellari-dotcom/NIVON/pull/212) | ÚTIL | F4 | 7 arquivo(s): `config/motores_inteligencia.v1.json`, `docs/FRETES_RECUPERACAO_POSCOMMIT_R01.md`, `scripts/recuperar_recibo_fretes_local.py`, `src/nivon/fretes_recuperacao_poscommit.py`, … | `feat/frete-ciclo-emissao-recibos-20261023` |
| [#211](https://github.com/brunocapellari-dotcom/NIVON/pull/211) | ÚTIL | F2 | 32 arquivo(s): `docs/R13_AGRO_MARITIMO_FRESCOR_CAPTURAS_20261023.md`, `scripts/coletar_agro_google_cloud.py`, `src/nivon/agro_origem_gcp.py`, `src/nivon/agro_staging_bigquery.py`, … | `integration/nivon-r12-ivo-pam-seguro-20261023` |
