# NIVON — evidência real ANP/LPC de três edições — 23/10/2026

## Resultado observado em runner externo

Coleta autorizada para finalidade interna não comercial. Fonte primária:
https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas

**Evidência CI do lote REAL:** GitHub Actions [#39984247762](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39984247762) — jobs `validar-nucleo`, `validar-anp-lpc-fixtures` e `inspecao-anp-lpc-real-pontual` **SUCCESS**. Script:
`scripts/inspecionar_anp_lpc_real_3_edicoes.py`.

Os três XLSX oficiais foram **realmente baixados e lidos com openpyxl 3.1.5** no runner em 23/10/2026; o conteúdo foi validado, agregado para MT e gravado num banco SQLite **temporário** no runner; depois o SHA-256 de cada XLSX/HTML arquivado temporariamente foi conferido. **Não houve gravação durável de preços reais no GitHub, Drive, banco operacional ou Google Cloud.**

| Competência semanal | Bytes XLSX | SHA-256 original | Observações de diesel MT | Municípios MT |
|---|---:|---|---:|---:|
| 11–17/10/2026 | 298891 | `41790a14ee758cf9d2582b6c0e1e5c5d7e0f17cd6c8ca91f476f75193d2bcf5f` | 14 | 7 |
| 04–10/10/2026 | 297219 | `0c2a23ede918c5b16d9756fe2bb6cef0a36a955d0bfa8fef2512c48a8a487f4a` | 14 | 7 |
| 27/09–03/10/2026 | 298097 | `d27039aad136b87445352936d3f072044bcd158951f229d3f796f5964a3cf134` | 14 | 7 |

**Total:** três edições, 42 observações municipais agregadas, separando `DIESEL` e `DIESEL S10`, sem dados por posto. `falhas=[]` e auditoria local `RAW_VERIFICADO_LOCALMENTE`, `quantidade_falhas=0`. O relatório QA apresentou três edições distintas e semana mais recente terminando em 17/10/2026.

**Layout realmente observado:** cada planilha possui `MUNICIPIOS`, `CAPITAIS`, `ESTADOS`, `REGIOES`, `BRASIL`; a aba municipal conta **3888 linhas declaradas** e o cabeçalho fechado com os oito campos obrigatórios foi encontrado na **linha 10** nas três edições. Não é possível validar conteúdo real presumindo a linha 7 das fixtures. Por isso, `anp_resumo_lpc.py` agora detecta o conjunto exato de colunas canônicas nas primeiras 20 linhas, preservando a possibilidade de exigir linha explicitamente. Em 23/10/2026 a reexecução real deu resultado `INSPECAO_COMPLETA`. Não afirmar que o layout permanecerá estável no futuro.

**Padrões de nomes oficiais:** links descobertos no índice incluem duas grafias: `resumo_semanal_lpc_2026-10-04_2026-10-10.xlsx` e `resumo_semanal_lpc_2026_10_11-2026_10_17.xlsx`. Ambas são aceitas sob validação de intervalo de sete dias. O coletor solicita o arquivo XLSX **na URL anunciada** sem anexar caminhos de download não publicados.

## Governança do dado real

1. As 42 observações são preços **médios amostrais de revenda de diesel B**, publicados semanalmente por município. Não constituem o preço efetivamente pago pela transportadora, frete negociado, frete anunciado ou volume efetivamente embarcado.
2. Os XLSX foram baixados num ambiente de CI efêmero; só **metadados estruturais, SHA-256 e contagens** aparecem nos logs. A inspeção não habilitou publicação automática de valores ou o gate `REAL_AUTORIZADO` do histórico canônico.
3. Os hashes devem servir a rastreio/reconciliação de snapshots. Uma nova captura posterior da ANP pode conter revisões; não sobrescrever o passado.
4. A bateria de testes offline e E2E sintético segue ativa. O job HTTP **pontual** foi removido do fluxo automático após obtenção das evidências, para evitar coleta a cada atualização da PR. O script de inspeção permanece para execução controlada.
5. A validade de uso não comercial pressupõe atribuição à ANP e respeito a eventuais termos específicos. Não usar em produto comercial sem revisão própria.

## Pronto para conectar GCS sem provisionamento automático

`src/nivon/anp_lpc_gcs.py` implementa upload idempotente de RAW por SHA e JSON normalizado com todos os vínculos de coleta, índices e versões, usando `if_generation_match=0`; bloqueia bucket sem `public_access_prevention=enforced` e verifica hashes RAW locais antes de qualquer transferência. Sem credencial, criação de projeto/bucket, ativação de API, cobrança ou agendamento.

Após existir **bucket privado** já configurado e autorizado, identidade do Google Cloud com permissões mínimas de leitura de metadados e gravação de objetos, instalar `google-cloud-storage` no ambiente e executar explicitamente:

```bash
PYTHONPATH=src python -m nivon.cli_coletar_anp_lpc \
  --modo rede --ano 2026 --ultimas 3 \
  --db data/anp_lpc/staging.sqlite --raw-dir data/anp_lpc/raw

PYTHONPATH=src python -m nivon.cli_coletar_anp_lpc \
  --modo integridade --db data/anp_lpc/staging.sqlite \
  --raw-dir data/anp_lpc/raw

PYTHONPATH=src python -m nivon.cli_coletar_anp_lpc \
  --modo gcs --db data/anp_lpc/staging.sqlite \
  --raw-dir data/anp_lpc/raw \
  --bucket NOME_BUCKET_PRIVADO_EXISTENTE \
  --prefixo nivon/anp/lpc/v1
```

Este procedimento **NÃO foi executado contra o Google Cloud** nesta rodada. Não confundir o conector GCS implementado e testado contra bucket sintético com uma exportação real verificada. Não provisionar serviços pagos, conceder permissões públicas ou fazer deploy automaticamente.

## Próximas entregas operacionais

- Restabelecer runtime persistente no Google Cloud com custos conhecidos e autorização separada de infraestrutura, armazenar RAW, staging e derivados com backups.
- Rodar primeira coleta persistente e segunda captura incremental, checando idempotência, correções de edições e divergência de preço por município/produto sem inventar valores faltantes.
- Conectar observações de diesel ao painel e motores de sensibilidade, **sem medir nem inferir repasse real ao frete**.
- Evoluir a coleta oficial para estágio homologado com fonte validada, governo de direitos e auditoria temporal, mantendo monitoramento de revisões.
