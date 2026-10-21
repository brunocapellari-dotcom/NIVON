# Histórico de Santos — legado AgroLog M01 (candidato à recuperação)

Importado como **evidência documental secundária de legado**, não como valores oficiais homologados. Registro fonte: [M01_Santos_Historico_v0_1.md](https://drive.google.com/file/d/1xOzarLrDnebMlS9sXb_dlqmmoJb8f9DF/view) encontrado no Google Drive do projeto.

O documento legado, datado de **24/08/2026**, afirma:
- Mensários SPA 2020 a 2022: 36 PDFs.
- Mensários SPA 2023 a 2024: 24 PDFs.
- Mensários SPA 2025 a junho de 2026: 18 PDFs.
- Total de 78 mensários e 76 valores mensais supostamente extraídos.
- Lacunas registradas em janeiro e fevereiro de 2023.
- Junho/2026 citado no documento: movimentação total de 17,13 Mt, embarques 12,8 Mt, desembarques 4,4 Mt, semestre acumulado 92,8 Mt e 2.850 atracações no semestre.

**Não foi encontrada, nesta rodada, cópia verificável dos 78 PDFs ou da série tabular validada.** Os dados acima devem ser tratados como alegações históricas do relatório interno, não medição atual, nem como observação de produção aprovada.

## Plano de recuperação sem duplicar fonte

1. Encontrar os PDF originais dos mensários SPA e o script/manifesto original de M01, em armazenamento autorizado.
2. Para cada competência e documento, preservar source_id=SPA_MENSARIO, URL/autoridade, hash SHA-256, competência, referência, publicação e coleta.
3. Reconstruir **76 valores extraídos** contra seus PDF correspondentes e revisar as duas lacunas janeiro/fevereiro 2023 manualmente antes de preencher séries.
4. Auditoria de aditividade: total mensal versus embarques + desembarques considerando arredondamento; atracações em uma métrica SEPARADA; nenhum carregamento duplicado por linha de produto.
5. Confrontar eventuais dados ANTAQ com mensários SPA apenas como **duas metodologias distintas**. Não mesclar valores automaticamente nem calcular diferenças sem reconciliar definição de porto, terminal, recorte de carga e referência temporal.
6. Usar o histórico só em backtesting após provar disponibilidade **as-of** de cada edição para evitar antecipação de revisões.

## Implicações para Nivon Maritime

- O módulo `maritime.antaq_archive` é o importador estatístico ANTAQ por ZIP anual; **não** serve para interpretar PDF dos mensários SPA.
- Se os PDFs forem localizados, reaproveitar extrator PDF e parser com contratos específicos de SPA, com fixtures reais e revisão independente.
- O cockpit pode exibir esse histórico SPA **somente** após homologação e com classe `INFORMADO_OFICIAL_HISTORICO`, nunca confundindo-o com AIS ao vivo.
- Nenhum dos números listados foi colocado no briefing, banco canônico de métricas ou API operacional nesta entrega.

Status: `LEGACY_CLAIMS_DISCOVERED_SOURCE_ARTIFACTS_MISSING`.
