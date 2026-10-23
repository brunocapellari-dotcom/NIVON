# NIVON — PAM/IVO operacional unificado: captura, vintage, revisão e recuperação

**Data do checkpoint:** 23/10/2026. **Decisão:** evolução reversível em PR draft, sem merge/deploy e sem novas chamadas de coleta real nesta integração.

## O que passou a funcionar em conjunto

```text
IBGE/SIDRA 1612 — API pública pontual (piloto upstream PR #7)
      │
      ▼
Normalização município/ano/produto/variável + unidade
      │
      ▼
Quarentena local SHA-256 (bytes originais e recibos)
      │
      ├──> SQLite operacional incremental: vintages, capturas, alterações
      │                   │
      │                   ▼
      │           auditoria SQLite↔recibo↔bytes↔célula
      │                   │
      │                   ▼
      │           ponte de revisão: sem promover dados
      │
      └──> backup ZIP portátil com inventário SHA e snapshot SQLite
                          │
                          ▼
                    restauração em pasta nova
                          │
                          ▼
               nova auditoria de integridade

PARADO AQUI: licença/verificação externa, Knowledge Factory assinada,
Hermes OIDC/OPA/OpenFGA, vintage oficial e promoção canônica.
```

O coletor HTTP pontual e o SQLite operacional foram desenvolvidos em PR #7; o executor **offline** e a fila de revisão estavam na PR #78. A reconciliação preserva ambos, sem atribuir a um caminho poderes do outro. O banco `pam_vintages/pam_capturas` é **staging**, não o ledger canônico de `registro_snapshots`.

## Execuções já verificadas e limites de evidência

- [Actions piloto SIDRA #39890755981](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890755981): **6 capturas reais pontuais, 0 falhas, 6 vintages**, auditoria SQLite/bytes local aprovada. Tangará da Serra, Lucas do Rio Verde e Sorriso, soja em anos civis 2021–2024. O lote e a primeira evidência foram preservados via artefato e Drive na frente da PR #7; **esta integração não acessou nem rebaixou novamente o ZIP do Drive**. Coletas ocorreram em 23/10/2026 e **não reconstituem** arquivos publicados em anos anteriores.
- A **PR #78** foi conciliada com o piloto sem conflito de conteúdo, mantendo modo somente `workflow_dispatch` do piloto. Não houve repetição das seis requisições HTTP nesta rodada de integração.
- `src/nivon/ivo_pam_ponte_operacional.py`: lê SQLite em modo somente leitura, executa `ivo_pam_qualidade.auditar_operacao_pam`, reconstrói pacote de auditoria de cada vintage a partir de seus recibos/bytes, respeita limite de coletas para leitura retrospectiva, compara mudanças operacionais e emite fila bloqueada por SHA. Nenhum valor ou conclusão numérica sai por esse caminho para motores de previsão.
- `src/nivon/ivo_pam_backup.py`: cópia consistente de SQLite por `Connection.backup`, bytes em arquivo ZIP `ZIP_STORED`, inventário SHA-256, quota, detecção de adulteração, symlink e path traversal. Restauração só em diretório novo, seguida de `PRAGMA integrity_check`, `foreign_key_check` e reauditoria completa contra os objetos recuperados. **Não** envia para cloud, não estabelece integridade independente e não assina.
- `tests/test_ivo_pam_ponte_operacional_e2e.py` e `tests/test_ivo_pam_backup_e2e.py`: baterias ponta a ponta por capturas, revisão de valor, corte as-of, hashes, backup/restauro, adulteração, quota e CLI; sem internet.
- `scripts/smoke_ivo_pam_lote.py` foi ampliado: 2 registros fictícios passam pelo executor offline, importação de arquivos locais, staging SQLite, ponte operacional, backup, restauro e nova auditoria no GitHub Actions em toda PR. Os 6 itens da coleta IBGE REAL não são confundidos com os 2 registros do smoke.

## Comandos disponíveis (na branch da PR #78)

Apenas em ambiente onde o banco e os arquivos tenham sido preservados legalmente. Python 3.11 e `PYTHONPATH=src`:

**Consultar/acompanhamento de versões de produção anual:**

```bash
PYTHONPATH=src python -m nivon.ivo_pam_consulta \
  --db dados_operacionais/ivo_pam.sqlite \
  --municipio 5107958 --produto 2713 --variavel 214 \
  --inicio 2021 --fim 2024
```

**Emitir fila de revisão a partir do SQLite/arquivos existentes, sem rede:**

```bash
PYTHONPATH=src python -m nivon.ivo_pam_ponte_operacional \
  --db dados_operacionais/ivo_pam.sqlite \
  --acervo dados_operacionais/quarentena_pam \
  --saida relatorios/ivo_pam_revisao.json
```

O diretório `relatorios/` deve existir. Arquivo de saída existente só é aceito se o conteúdo for idêntico. Nenhuma autorização de publicação é criada.

**Criar backup portátil:**

```bash
PYTHONPATH=src python -m nivon.ivo_pam_backup criar \
  --db dados_operacionais/ivo_pam.sqlite \
  --cofre dados_operacionais/quarentena_pam \
  --arquivo backups/nivon_pam_backup.zip
```

**Testar restauração (diretório de destino ainda não deve existir):**

```bash
PYTHONPATH=src python -m nivon.ivo_pam_backup restaurar \
  --arquivo backups/nivon_pam_backup.zip \
  --destino restauracao_teste/nivon_pam
```

A pasta `backups/` e a pasta pai de `restauracao_teste/nivon_pam` precisam existir. O módulo recusa sobrescrever os dados.

## Controles operacionais

**Tipos de tempo:** competência/ano civil PAM, data de coleta efetiva e data oficial de publicação são distintos. Um corte `as-of` do SQLite reflete apenas *quando aquela cópia foi registrada*, não quando foi oficialmente publicada. Revisão observada entre coletas não determina automaticamente dia/horário da correção do IBGE.

**Proteção:** capturas ou metadados sem SHA consistente bloqueiam toda a ponte; nenhum retorno parcial pode mascarar um acervo corrupto. Uma revisão do mesmo ano mantém cada captura separada; não funde e não transforma em indicador de previsão.

**Backups:** são cópias locais portáveis, não cópias externas atestadas nem política de retenção/restore cloud. O integrador exige verificação independente de licenças, data de publicação, identidade do revisor e chave KMS antes de permitir promoção canônica, treinamento ou publicação.

## Próximos lotes técnicos independentes e bloqueadores

| Prioridade | Ação | Portão de aceite |
| --- | --- | --- |
| P0 | Unificar contratos de proveniência e direitos reais por operação | Verificação autoritativa por fonte, tenant e momento |
| P0 | Incluir vintages oficiais e evidências anteriores a erratas | Arquivos anteriores genuínos com datas e hashes atestáveis |
| P1 | Instalar armazenamento privado durável com backup automático e restauração ensaiada | Escopo de acesso, custo validado, reposição íntegra sem sobrescrever |
| P1 | Execução recorrente incremental sem full scans | Deduplicação por SHA, controle de frequência, WAF/limites respeitados |
| P1 | Entregar visão gerencial do IVO rotulada `captura atual` versus `vintage da publicação` | Auditoria editorial de datas e direitos |
| P2 | Homologar porta Hermes + Knowledge Factory para assinatura de decisões | Revisor independente, OIDC, OPA/OpenFGA, aprovações pendentes fail-closed |
| P2 | Convergência com IMEA, CEPEA e CONAB | Esquema/direitos/frescor individual, sem combinar medidas incompatíveis |

**Sem ativação nesta rodada:** coleta HTTP adicional, schedule de coleta real, merge, deploy, Google Cloud pago, treino, redistribuição ou publicação de estatísticas do staging como verdade canônica.
