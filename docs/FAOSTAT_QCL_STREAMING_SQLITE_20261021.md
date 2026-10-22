# FAOSTAT QCL — extrator seletivo de produção, streaming e stage SQLite (21/10/2026)

## Alvo e limites

**Fonte:** https://bulks-faostat.fao.org/production/datasets_E.json, domínio QCL, arquivo oficial `Production_Crops_Livestock_E_All_Data_(Normalized).zip`. O ZIP QCL tem cerca de 33 MB comprimidos e 4,2 milhões de linhas; o formato FAOSTAT normalizado contém campos `Area Code`, `Item Code`, `Element Code`, `Year`, `Unit`, `Value`, `Flag`, `Note`.

O conector `src/nivon/faostat_qcl_stream.py` seleciona apenas **produção física** (elemento FAOSTAT 5510) em toneladas para Brasil/Argentina/EUA, soja/milho/trigo e janela limitada de anos. Usa identificadores FAOSTAT, não IBGE nem NCM. São **estatísticas anuais nacionais**, não safras da CONAB ou projeções de produtividade. Em caso de mudança de códigos, unidade ou CSV, bloqueia a linha.

## Proteção de infraestrutura

- O manifest precisa passar pelo parser existente e indicar URL QCL exatamente igual à allowlist; links dinâmicos não são seguidos.
- `executar=True` é obrigatório. Nenhum download/agendamento/importação em produção implícito.
- Um download de até 43 MB para arquivo temporário *spooled* (disco depois de 2 MB), com SHA256, timeout, limite de resposta, status/MIME e proibição de redirects.
- ZIP com limites de partes/tamanho total (950 MB descomprimidos), membros CSV seguros, sem paths/criptografia; apenas o CSV normalizado é percorrido em streaming.
- Até cinco milhões de linhas varridas; somente até 600 linhas filtradas em memória. Nenhuma extração total do arquivo.
- `--sqlite /caminho/local.db` é opt-in. Stage SQLite versionado por `source_sha256`, ano, país, cultura e elemento; reexecução idêntica não duplica; revisões ficam preservadas. O arquivo local não é BigQuery/GCP.
- `data_referencia`, `competencia`, `data_coleta` e `data_publicacao=NULL` preservados. `data_atualizacao_fonte` é metadado de lote, não data individual de disponibilização pública.

## Testar sem persistência

```bash
PYTHONPATH=src python scripts/smoke_faostat_qcl_stream.py --pais BRA --cultura SOJA --inicio 2023 --fim 2023 --executar
```

## Testar SQLite local opcional

```bash
PYTHONPATH=src python scripts/smoke_faostat_qcl_stream.py --pais BRA --cultura SOJA --inicio 2023 --fim 2023 --sqlite /tmp/nivon_faostat_qcl.db --executar
```

O teste automatizado `tests/test_faostat_qcl_stream.py` constrói um ZIP genuíno sintético, simula HTTPS e valida seleção, 5510/t, Unicode, ausência de observações, ZIP paths inseguros, datas, idempotência e revisões de uma observação em SQLite local.

## Gates

1. Smoke real de download QCL e validação do esquema existente no ZIP oficial. O código e fixtures isolados não bastam.
2. Licença por operação, atribuição, cobertura, datas, flags e comparação contra dados oficiais de referência FAO/CONAB.
3. Banco central do NIVON: credenciais e BigQuery/Google Cloud somente após verificação dos projetos existentes, permissão e custos; nunca inferir ambiente configurado.
4. Backup e restauração, trilha de revisões e publicação no motor de tendência só após backtest com vintages documentados.

O código atual NÃO ativa tarefas agendadas, NÃO cria serviços pagos, NÃO habilita publicação de números nos produtos e NÃO afirma histórico carregado no banco do NIVON.
