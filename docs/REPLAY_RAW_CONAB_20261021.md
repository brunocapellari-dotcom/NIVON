# NIVON — Replay executável RAW → observações para a CONAB

**Data:** 21/10/2026. **Classificação:** laboratório offline, não homologado para fonte CONAB.

## O que foi implementado

O módulo `src/nivon/conab_replay_raw.py` recebe **bytes reais do arquivo fornecido ao processo**, confere tamanho e SHA256, decodifica um CSV estrito de intercâmbio, normaliza por `conab_agrobr.normalizar_progresso` e produz mapa de observações da mesma semântica do armazenamento histórico. Ele informa um SHA256 do próprio arquivo do módulo, para facilitar identificar a versão de código que executou o replay (isso **não** equivale a uma assinatura digital).

O pré-voo de migração `preflight_migracao_conab.py` passa a executar esse parser quando e **somente quando** a versão declarada é `NIVON_INTERCAMBIO_CSV_TESTE_V1` e o MIME é `text/csv`. Em seguida exige equivalência total entre:
1. SHA256 dos bytes RAW recebidos;
2. observações produzidas **pela execução dos bytes**;
3. conteúdo do replay JSON informado no manifesto;
4. observações normalizadas do histórico legado.

Mesmo com essa prova técnica, os campos `parser_raw_reprodutivel_auditado`, `parser_conab_oficial_homologado`, `migracao_permitida` e os gates de direitos continuam falsos. O relatório distingue `csv_intercambio_reexecutado_localmente` de homologação CONAB.

## Contrato experimental CSV

CSV UTF-8, cabeçalho **exatamente** nesta ordem, sem colunas extras:

```
cultura,safra,operacao,uf,semana_atual,pct_ano_anterior,pct_semana_anterior,pct_semana_atual,pct_media_5_anos,revisado,n_estados,cobertura_area_pct
```

Frações numéricas de 0 a 1 usam **ponto decimal**, até 6 casas, sem notação científica. Campo da semana atual é obrigatório; demais frações opcionais. `revisado` admite `true`, `false` ou vazio. `MEDIA_ESTADOS` exige `n_estados` explícito (1–27), mas nunca se transforma em média nacional nem total Brasil. Máximo de 5.000 linhas ou 2 MB. Campos extras, cabeçalho alterado, duplicações, números não finitos, URLs não oficiais, timestamps sem fuso e publicação futura fazem a operação falhar.

A URL oficial e o timestamp de publicação são **insumos do manifesto/DB**, não atributos verificados pelo CSV; a função não presume que o CSV prove origem CONAB.

## Por que ainda NÃO suporta planilhas semanais oficiais

O contrato acima **não foi extraído de uma amostra oficial de XLS/XLSX da CONAB**. Um parser de laboratório para verificar a arquitetura de replay não substitui a interpretação da planilha oficial. Não renomear um arquivo XLS/XLSX para CSV nem inferir cabeçalhos, unidades ou percentuais. O uso do módulo em produção está proibido até:

- amostra RAW oficial adquirida licitamente e preservada em storage autorizado;
- leitura do layout real e identificação de versão do documento;
- parser oficial separado por tipo/versão, com testes por amostras, revisão editorial e validação científica;
- verificação RAW→parser→normalização, publicação e competência;
- auditoria de permissões para coletar, armazenar, derivar e distribuir;
- testes do processo completo com backup/restauração de dados reais.

## Segurança e regressões

Teste `tests/test_conab_replay_raw.py` cobre execução determinística com bytes, adulteração de SHA, alteração de valor, UTF-8, cabeçalho, colunas, percentuais inválidos, países inferidos, coberturas, duplicidade, publicação futura e direitos não presumidos. Testes integrados em `tests/test_preflight_migracao_conab.py` comprovam que valor alterado no RAW, mesmo com SHA atualizado, **não pode passar** diante de JSON/legado divergentes.

Zero HTTP; zero escrita em banco; zero migração; zero publicação; sem ativar agendamentos.

**Gates:** esta entrega comprova apenas o comportamento do parser experimental e a confiabilidade da comparação sob testes sintéticos. Não homologa bytes históricos oficiais ou operações comerciais.
