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


## Continuidade 23/10/2026 — ciclo de recuperação durável sem servidor fixo

**Problema resolvido:** o modo GCS original exportava arquivos e JSON, mas um processo efêmero sem SSD persistente não conseguia retomar o estado de capturas e revisões do SQLite após reinício.

**Implementação:** `src/nivon/anp_lpc_ciclo_gcs.py` fornece um ciclo único `restaurar -> coletar -> auditar -> exportar -> confirmar snapshot` num diretório privado temporário, com término limpo. O commit durável do lote é o **snapshot SQLite com nome derivado de SHA-256**, registrado somente após os objetos de RAW e edições normalizadas terem sido enviados. Na próxima execução, o GCS fornece o instante de criação confiável para identificar o snapshot mais recente; a restauração verifica SHA, integridade SQLite, relacionamentos, todos os XLSX e todos os HTML de índice antes de liberar nova coleta. Snapshot mais recente corrompido **bloqueia**, sem fallback silencioso a um snapshot antigo.

A operação preserva o registro de capturas, alterações do índice e revisões de planilhas, evitando duplicação de edições sob SHA idêntico. Se a primeira exportação foi interrompida antes do snapshot, arquivos órfãos em formatos conhecidos **não são promovidos automaticamente**, mas a execução pode recompor o estágio a partir de nova leitura da fonte e confirmar um primeiro snapshot. Arquivo órfão remoto cujo conteúdo não corresponde ao hash esperado bloqueia. Objetos desconhecidos no namespace bloqueiam. O GCS preserva todas as versões por identidade de conteúdo; novas capturas podem criar novos JSON e snapshots, consumindo operações/armazenamento adicionais.

**Exemplo de comando único** para uso futuro em ambiente com bucket/identidade já configurados, sem instalar ou provisionar serviços:

```bash
python -m pip install --no-input -e '.[excel,gcs]'
PYTHONPATH=src python -m nivon.cli_coletar_anp_lpc \
  --modo ciclo-gcs --ano 2026 --ultimas 3 \
  --bucket NOME_BUCKET_PRIVADO_EXISTENTE \
  --prefixo nivon/anp/lpc/v1
```

Backfill por recorte pode usar `--desde AAAA-MM-DD --ate AAAA-MM-DD --ultimas 12`. A CLI usa ADC do ambiente autorizado e `bucket.reload()` antes de coletar. Não aceita `--db` ou `--raw-dir` no ciclo: estes ficam privados e temporários; o **único estado durável** é o bucket privado GCS. O `ciclo-gcs` não é cron e não foi acionado em nuvem real nesta rodada.

**Permissões mínimas a estudar no Google Cloud:** `storage.buckets.get`, `storage.objects.list`, `storage.objects.get`, `storage.objects.create`, todas restritas ao bucket privado já existente. Evitar permissões de exclusão, atualização de ACL, criação de bucket ou owner; autenticar via identidade da execução e credenciais de curta duração. Exigir `public_access_prevention=enforced`. Uma invocação real pode **gerar operações/armazenamento cobrados**, ainda que não crie recursos; checar billing/quota efetivos antes de habilitar. Nenhuma quota grátis foi presumida.

**Concorrência:** operar com **um único escritor por prefixo** até existir lease distribuído com fencing/revisões transacionais. Duas execuções independentes simultâneas podem persistir snapshots concorrentes; esse cenário não está homologado e não deve ser agendado. O snapshot é a confirmação durável do processo, não substitui backup em domínio de falha independente nem retenção auditável do GCS.

**Testes E2E sintéticos:** três ciclos consecutivos com bucket simulado: ingestão de três semanas, restauração de 3 edições em novo processo, reprocessamento sem novas edições e revisão posterior de uma planilha resultando em 4 edições; também snapshot adulterado, primeira exportação incompleta e colisão de SHA remoto. Em instância GCS real, listagem, leitura e criação exigem credenciais e custeio prévios; por isso os testes automáticos continuam offline.

**Gates restantes:** provar operação em bucket real com acesso e custo monitorados; implementar exclusão mútua/lease por prefixo e política de retenção/backup independente; confirmar atualidade da fonte em execuções recorrentes; integrar relatórios sob governança de dados e direitos. Não foi feita promoção para `REAL_AUTORIZADO`, merge nem deploy.


## Infraestrutura real identificada na branch main (mesmo projeto NIVON)

A investigação sobre `main` confirmou que o projeto **não precisa de um segundo Google Cloud**: os workflows já usam `vars.NIVON_BQ_PROJECT`, `vars.NIVON_GCS_BUCKET`, `vars.NIVON_GCP_PROVIDER` e `vars.NIVON_GCP_SERVICE_ACCOUNT`. A documentação de ANTT de 23/10/2026 registra execução real de GCS e BigQuery [Actions #39983416188](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983416188), no projeto **`nivon-data`**, região **`southamerica-east1`**, bucket privado **`nivon-data-raw-2026`** e dataset **`nivon_raw`**. Essa prova é da ANTT e **não** comprova autorização de escrita ANP, bucket gratuito, custo zero, retenção ANP ou tabela ANP operacional.

A `main` mantém o núcleo compartilhado `arquivo_raw_gcs.py`, `lote_cloud_recuperavel.py`, `carga_bigquery_fontes.py` e workflows próprios. A camada LPC nesta PR é um **staging específico da fonte**; não deve virar um segundo núcleo central de GCS/BigQuery. Na etapa de reconciliação com `main`, será necessário reutilizar os contratos comuns de RAW/manifests/replay e mapear observações ANP para o modelo canônico do NIVON, preservando bitemporalidade, hashes e as separações diesel B/S10. **Não foi criada tabela ANP ou novo dataset BigQuery nesta rodada.**

### Workflow de operação preparada (não ativada)

`.github/workflows/anp-lpc-gcp.yml` é uma entrada operacional compatível com as variáveis e identidade federada existentes. Possui `workflow_dispatch` para `preflight` somente leitura e `coletar` e **cadência semanal prevista em código**, mas a escrita só pode acontecer após incorporação à **`main`** e todas as variáveis independentes:

- `NIVON_RAW_ARCHIVE_APPROVED=true`: autorização geral de arquivamento privado;
- `NIVON_ANP_LPC_WRITE_APPROVED=true`: autorização específica de escrita ANP;
- `NIVON_ANP_LPC_COST_LIMIT_APPROVED=true`: orçamento/cota verificado pela operação;
- `NIVON_ANP_LPC_RECURRING_APPROVED=true`: necessário **apenas** para a recorrência, não para o despacho manual;
- `NIVON_GCP_PROVIDER`, `NIVON_GCP_SERVICE_ACCOUNT`, `NIVON_BQ_PROJECT`, `NIVON_GCS_BUCKET` existentes e definidos na infraestrutura.

O job de escrita reutiliza **WIF/OIDC**, `environment: nivon-gcp-producao`, execução serializada, bucket existente com `public_access_prevention=enforced`, região `southamerica-east1`, ano UTC corrente e o `--modo ciclo-gcs`. Não habilita APIs, serviços, faturamento, contas de serviço, chaves permanentes, bucket, tabela ou agendadores externos. O pré-teste local de configuração não autentica e não escreve. O WIF atualmente verificado na `main` **não foi testado nem ampliado para a branch da PR #42**. Por isso o workflow foi adicionado somente ao código e **não foi executado com credenciais reais**.

Como o NIVON usa bucket compartilhado, o prefixo é restrito a `nivon/anp/lpc/v1` para não misturar a série municipal da ANP com ANTT, CEPEA, IMEA e CONAB. Em operação futura, confirmar explicitamente IAM mínimo no prefixo/bucket e revisar a estimativa de custo de armazenamento e leituras antes do primeiro lote. **GitHub Actions e GCS podem gerar custo**; aprovação na variable é um gate necessário, não prova de ausência de cobrança.

**Situação:** coletor ANP 3 edições reais já aprovado no runner efêmero; restauração e retomada testadas com bucket sintético; **primeira escrita ANP no bucket `nivon-data-raw-2026` ainda não executada**. PR aberta em rascunho, sem merge. A reconciliação com o núcleo canônico da `main` deve anteceder qualquer promoção operacional, evitando um pipeline concorrente.
