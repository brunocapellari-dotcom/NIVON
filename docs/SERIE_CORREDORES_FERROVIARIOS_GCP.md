# NIVON — Série mensal de corredores e consulta BigQuery

## Resultado operacional da mudança

O coletor ferroviário ANTT/SIADE já existia e foi exercitado com dados reais (2006–ago/2026). Esta entrega **não duplica nem substitui a ingestão**: reutiliza `nivon.antt_bigquery.montar_lote`, que confere CSV de origem, SHA-256, manifesto, competência e número de linhas.

O motor `nivon.serie_corredores_antt` agrupa por **mês, estação de origem com nome geográfico exato, produto e estação de destino**. Ao exportar a série, informa as revisões SHA e metadados por ano, toneladas úteis e variação do mesmo mês do ano anterior (quando ambos têm registro).

## Separações mandatórias

- Trata-se de **produção em ferrovias federais concedidas**, não todo o sistema ferroviário do Brasil. Dom Aquino, por exemplo, pode estar fora da cobertura deste conjunto.
- Nome de estação igual ao do município **não** homologa terminal particular nem origem rodoviária.
- Uma ausência de registro **não é zero**. Percentual interanual sem denominador positivo retorna nulo.
- As nomenclaturas `Grãos - Milho`, `Soja` e `Farelo de Soja` são convertidas apenas por correspondência textual exata. O nome original nunca é descartado.
- Toneladas úteis na ferrovia não são tonelagem física única ao atravessar outros modais. Não somar com MDF-e, ANTAQ ou line-up sem reconciliação.
- A série inclui dados das origens de estação reconhecidas; **não atribui as linhas ferroviárias das estações não reconhecidas aos polos**. Isso produz cobertura parcial conhecida, sem extrapolações.
- Em relatórios, `data_referencia` refere-se ao primeiro dia do mês, `data_coleta` vem do snapshot fonte, `data_publicacao` permanece nula quando não autenticada.

## Pipeline existente no GitHub Actions

O workflow `nivon-corredores-ferroviarios.yml` baixa os CSVs 2025–2026 **uma vez**, produz o ranking mensal, YoY e o novo `antt-serie-corredores-2025-2026.json` em artefato por execução. O ambiente efêmero é limpo após o trabalho; artefatos são auxiliares de investigação e **não** banco operacional de longo prazo.

```bash
PYTHONPATH=src python -m nivon.coleta_antt --inicio 2025 --fim 2026 --destino /dados/antt-staging --live
PYTHONPATH=src python -m nivon.serie_corredores_antt --staging /dados/antt-staging --anos 2025 2026 --uf-origem MT --output /dados/relatorios/serie.json
```

## Integração incremental no Google Cloud

`nivon.corredores_bigquery` produz a *view* `vw_nivon_corredores_ferrovia_mensal` sobre `vw_antt_ferrovia_od_atual`, que já seleciona o snapshot ferroviário mais recente de cada ano.

Sem duplicação de toneladas em outra tabela. Quando o arquivo SIADE é atualizado, a visualização lê automaticamente a revisão ativa. Os objetos brutos permanecem no GCS histórico, as linhas normalizadas na tabela BigQuery particionada e a view utiliza apenas a última versão de cada ano.

A view preserva município/estação literal, produto ANTT, produto normalizado, destino ferroviário, data de coleta, SHA, quantidade de registros e status explícito `transbordo_confirmado=false`. O schema base utiliza `data_referencia` e `competencia`, enquanto a view fixa `data_publicacao=NULL` até evidência oficial.

**Modo seguro (sem rede, sem custos):**

```bash
PYTHONPATH=src python -m nivon.corredores_bigquery --projeto <PROJECT_ID> --dataset <DATASET>
```

**Modo autorizado:** apenas com Google ADC/WIF válido, dataset e view SIADE existentes e aprovados:

```bash
PYTHONPATH=src python -m nivon.corredores_bigquery --projeto <PROJECT_ID> --dataset <DATASET> --live
```

A view só será publicada automaticamente no fim de `antt-ferrovia-gcp.yml` se todas as condições já obrigatórias da carga ferroviária estiverem satisfeitas e a variável de repositório **`NIVON_CORREDORES_VIEW_APPROVED=true`** estiver explicitamente configurada. A opção não cria projeto, bucket, dataset nem exporta volumes sem credenciais. Nunca presumir a existência dessas variáveis.

## Próximos gates

1. Verificar testes e fluxo E2E com dados SIADE reais; confrontar com totas por estação/mês.
2. Validar projeto Google Cloud, bucket, dataset e WIF e executar uma carga real com controle de custos. **Nenhuma carga Cloud foi confirmada por esta PR.**
3. Homologar o cadastro de estações, garantindo que o identificador geográfico reflita a estação real e não apenas o nome compartilhado.
4. Integrar o escopo hidroviário/portuário com fonte ANTAQ oficial autorizada, contemplando cargas únicas e dupla contagem em etapas modais.
5. Matriz rodoviária MDF-e por origem–destino e NCM completo: issue #142.

Fonte primária ferroviária: https://dados.antt.gov.br/dataset/sistema-de-acompanhamento-do-desempenho-operacional-das-concessionarias-siade
