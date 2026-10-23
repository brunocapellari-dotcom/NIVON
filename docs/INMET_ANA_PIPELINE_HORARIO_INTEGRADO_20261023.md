# NIVON — Integração INMET e ANA em um único acervo horário
**Referência:** 23/10/2026. **Estado:** código em PR draft, testes sintéticos; nenhum coletor/autorização/deploy.

## Objetivo e escopo executado
A frente saiu dos parsers isolados para um ciclo completo com **um único contrato operacional de hora e medição**, independente do transporte:

1. **Entrada/QA**: INMET CSV horário (parser original `inmet_horario_qc.extrair_horarios_inmet`), ANA HidroWebService telemetria adotada JSON (`ana_hidrowebservice.normalizar_adotada`), sem implementar novos parsers concorrentes.
2. **Suporte temporal explícito**: INMET `CHUVA_HORA_MM` recebe `HORA_ROTULADA_SEM_CONVENCAO` até validação oficial da janela; ANA `CHUVA_INTERVALO_MM`, `VAZAO_M3_S` e `COTA_CM` recebem `INSTANTANEO_OU_INTERVALO_API_NAO_HOMOLOGADO`. **Não** converter chuva de 23/24 registros para dia civil ou instantâneo da ANA em vazão média diária.
3. **Versionamento**: SHA-256 dos bytes RAW originais, arquivo write-once `<sha>.raw`, banco SQLite com cada observação, suporte temporal, QC da fonte, edição e captura. Coleta declarada pelo arquivo não é homologação da data de publicação histórica.
4. **Atualização atômica**: até 40 arquivos por manifesto, preflight completo antes de qualquer gravação e savepoint SQLite. Falha no último arquivo desfaz todas as edições do ciclo, com limpeza restrita a RAWs novos órfãos.
5. **Consultas as-of**: somente snapshots capturados na edição vigente até o corte **local do NIVON**, verificação do hash antes de responder; publicação por medição e skill preditivo permanecem desconhecidos.
6. **Auditoria e restauração**: relê todos os RAWs, reexecuta parsers canônicos, compara byte SHA, contagem, unidade, QC, registros e vínculos SQLite; exporta SQLite+RAW para pasta nova com manifesto de hashes e verifica backup após restauração.
7. **CLI por lote**: `pipeline_medicoes_cli` com `validar`, `executar`, `auditar`, `backup` e `validar-backup`, sem rede nem agendadores. Registro de motores de METEOROLOGIA, HIDROLOGIA e CLIMA_HIDRO continua OFF.

### Exemplo de manifesto para arquivos locais existentes

```json
{
  "schema": "1.0",
  "projeto": "NIVON",
  "lotes": [
    {
      "arquivo": "estacao_A904_2025.csv",
      "formato": "INMET_HORARIO_CSV",
      "estacao_id": "A904",
      "ano": 2025,
      "zona": null,
      "coletado_em": "2026-10-23T12:00:00Z",
      "classe": "EXTERNO_NAO_HOMOLOGADO"
    },
    {
      "arquivo": "ana_15400000.json",
      "formato": "ANA_ADOTADA_JSON",
      "estacao_id": "15400000",
      "ano": null,
      "zona": "America/Manaus",
      "coletado_em": "2026-10-23T12:00:00Z",
      "classe": "EXTERNO_NAO_HOMOLOGADO"
    }
  ]
}
```

**Exemplo de contrato, não dados disponíveis.** As duas entradas são exemplos fictícios: arquivos devem existir localmente e sua utilização precisa respeitar direitos por operação e credenciais privadas. A classe externa é **não homologada**, sem desbloqueio de coletor. Todas as datas de corte de desenvolvimento são verificadas pelo instante de primeiro registro real no processo para arquivos externos, e não pelo texto declarado do manifesto.

```bash
PYTHONPATH=src python -m nivon.pipeline_medicoes_cli validar --manifesto lotes.json
PYTHONPATH=src python -m nivon.pipeline_medicoes_cli executar --manifesto lotes.json --banco ambiental.sqlite --raw-dir arquivo_raw --confirmar-gravacao
PYTHONPATH=src python -m nivon.pipeline_medicoes_cli auditar --banco ambiental.sqlite --raw-dir arquivo_raw
PYTHONPATH=src python -m nivon.pipeline_medicoes_cli backup --banco ambiental.sqlite --raw-dir arquivo_raw --destino-backup backup_hidro_01
PYTHONPATH=src python -m nivon.pipeline_medicoes_cli validar-backup --destino-backup backup_hidro_01
```

## Governança e limitações

- **INMET:** método de agrupamento por rótulo UTC não prova o início/fim físico da precipitação horária; QC instrumentais, metadados de estação, mudança de sensor, lacunas e conversão de dias continuam dependências para comparação espacial. Campos diários do motor de avaliação existente permanecem bloqueados até 24 horas + evidência temporal + QC externo adequado.
- **ANA:** dados adotados podem ser leituras instantâneas de cota/vazão e chuva de intervalo curto, não medições diárias. A normalização original preserva `APROVADO` / `SUSPEITO` / `RUIM` como estados fornecidos pela API, **não** parecer final do NIVON. Timezone de cada estação deve ser confirmado externamente.
- **RAW/SQL:** hashing e auditoria provam consistência interna após arquivamento, não autenticidade da resposta HTTP original, titularidade de dados, licença, QC independente ou disponibilidade point-in-time na fonte antes da captura.
- **Rede:** nenhuma implementação acessa URLs, BDMEP privado, ANA SSO ou tokens. Os conectores existentes para rede mantêm sua política original OFF. Dados externos podem ser fornecidos *localmente* por um processo separado autorizado.
- **Concorrência:** diretório RAW dedicado, arquivo SQLite fechado para outro escritor durante importação/backup; backup deve ser copiado para storage persistente e testado em restauração antes de operar. Não exportar RAW privado para repositório público.
- **Publicação:** relatórios, modelos prognósticos e qualquer estratégia de produção exigem aprovação separada de direitos, horários, latência, QC e validação real OOS.

## Priorização de execução e testes para a próxima etapa

| Prioridade | Entrega | Critério de aceite |
|---|---|---|
| P0 | Pipeline INMET/ANA unificado | 2 fontes, 51 medidas sintéticas, metadados temporais/QC preservados |
| P0 | Ingestão incremental e replay | Reedição de chuva, consulta as-of, idempotência e restart |
| P0 | Rollback e integridade | Erro no segundo arquivo desfaz o primeiro; corrupção RAW/SQLite reprovada |
| P0 | Backup/restauração e CLI | Banco e RAWs íntegros após restore e comandos de ponta a ponta |
| P0 | Regressão total de motores | CI do repositório no HEAD final, sem falhas |
| P1 | Fonte INMET real pontual | ZIP BDMEP autorizado, estação verdadeira, metadados e direitos |
| P1 | ANA telemetria pontual | Credenciais válidas fora do Git, schema real e referência horária/QC |
| P1 | Google Cloud / armazenamento durável | Infra já autorizada sem ativação de cobrança, storage e transações auditáveis |
| P2 | Janelas diárias, grade e modelos hidrológicos | Mapear intervalos físicos; backtest OOS e skill com vintages reais |

Esta PR é **módulo de trabalho reversível**, baseada na PR #152. Não realizar merge em duplicidade com #9/#11 e nenhuma das PRs empilhadas.
