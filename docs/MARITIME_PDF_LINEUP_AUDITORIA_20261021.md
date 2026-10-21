# NIVON — Auditoria técnica de line-ups PDF (21/10/2026)

**Âmbito:** Paranaguá e Itaqui. **Estado:** `CODE_TESTED_SYNTHETIC_ONLY` / `REAL_DATA_GATED` / `RELEASE_BLOCKED`. Nenhum arquivo PDF oficial efetivo foi baixado/interpretado nesta PR. Não há comprovação de direitos de coleta, retenção ou publicação.

## Achados P0 e correções

1. **Hora de chegada inexistente:** o parser herdado de PDFs aceitava datas sem relógio e `strptime()` fornecia `00:00` como efeito colateral. A versão corrigida não inventa horário. Mantém linha programada incompleta no resultado, com ETA vazia; o adaptador PDF contabiliza a exclusão e o gate de vintage completa falha com motivo claro.
2. **Ano presumido:** formatos `dd/mm hh:mm` / `dd/mm/yy hh:mm` podiam derivar o ano da data de referência. O parser registra `eta_year_inferred`. A ponte de escala exige ano de **quatro dígitos e hora original explícita**. Um horário `00:00` somente é aceito quando estiver expressamente no documento.
3. **Identidade da escala:** o campo `N. Prog` de Paranaguá é referência de programação; não é automaticamente um DUV. IMO identifica navio, não visita. O parser preserva DUV apenas se houver **coluna explicitamente rotulada DUV** (correspondência exata do cabeçalho, não por substring como `Dúvida` ou `Observação DUV`). A ponte nunca usa `call_id` derivado de `N. Prog`, IMO, nome ou posição de linha como identidade da escala.
4. **Linhas múltiplas da mesma DUV:** o adaptador não as contabiliza como escalas independentes nem soma produtos. Mantém a primeira candidata e marca duplicatas para normalização explícita da relação escala (1) → lotes/produtos (N). Um vintage não pode ser promovido com linhas excluídas.
5. **Fontes misturadas e revisões:** `bridge_official_pdf_document()` compara a interpretação PDF com a saída normalizada do coletor preexistente e usa seu contrato de URL, SHA-256, MIME, data de coleta e gate de direitos de coleta. Aceita somente programação; Itaqui `ATRACADO` e `FUNDEADO` **não** confirmam eventos operacionais neste fluxo. Em desacordo de interpretação, falha de modo seguro.
6. **Restrições materiais:** os PDFs precisam do parser `pdfplumber`; páginas escaneadas não podem ser presumidas processáveis. Limite offline da ponte: 20 MB. O relógio local fixo UTC−3 é hipótese contratual piloto e depende de verificação por autoridade, data e documento.

## Preparação por porto

| Porto | Fonte de identidade que permite candidato de escala | Sem DUV | ETA sem hora/ano pleno | Edições reais auditadas nesta PR |
| --- | --- | --- | --- | --- |
| Itaqui | Coluna documental expressa de DUV, se existir no layout | Candidato excluído | Linha retida para revisão, candidato excluído | 0 |
| Paranaguá | Coluna documental expressa de DUV, se existir no layout | Não converter `N. Prog` em DUV; candidato excluído | Linha retida para revisão, candidato excluído | 0 |

**Não há garantia de que os PDFs oficiais atuais possuam coluna DUV.** Caso não exista, o projeto precisa de vínculo de escala autorizado e auditado por outra fonte oficial; **não** deve criar uma chave artificial de escala a partir de navio, IMO ou número de lote.

## Testes e rastreabilidade

- `src/nivon/_agrolog_portos_pdf.py`: preserva linhas e distinção de precisão temporal.
- `src/nivon/maritime/official_lineup_bridge.py`: adaptador seguro `bridge_official_pdf_document`, estado `SHADOW_NOT_HOMOLOGATED`.
- `tests/test_maritime_pdf_lineup_bridge.py`: **24 testes sintéticos** com tabelas `PdfTable` simuladas; os bytes rotulados como PDF são testes de contrato e **não** PDFs extraídos por `pdfplumber`.
- Primeira CI de implementação no SHA `6092461458f173c46737622b79efca2d2cf20309`: [suíte Python (1.138 testes, 5 ignorados, 0 falhas)](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39605034024) e [build marítimo aprovado](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39605034098). As duas novas regressões de cabeçalho DUV requerem verificação da CI no SHA final.

## Critérios de próxima entrega

1. Obter **por meios autorizados** três PDFs originais independentes por fonte e por série de Paranaguá considerada, mais três edições de Itaqui. Aguardar verificação legal antes de retenção dos bytes.
2. Inspecionar visualmente a legenda, cabeçalho e linhas de cada PDF contra a extração por página, identificando colunas ausentes e mudanças de layout. Preservar SHA original, URL, MIME, tamanho, competência, referência, publicação comprovada e coleta.
3. Documentar se existe **DUV realmente publicada** ou somente `N. Prog`; definir reconciliação oficial rastreável quando necessário. Não promover escala sem essa identidade.
4. Confrontar duas coletas sucessivas para descobrir programações novas, retiradas e ajustes de ETA, sem classificar cancelamento ou saída como operação realizada.
5. Só após licença e revisão independente, aprovar integração com `LineupVintageLedger`, histórico as-of e reconciliação AIS devidamente licenciado. Release e publicação continuam bloqueados.

**Documentos originais e licenças não foram adicionados ao GitHub nesta rodada.** Revisão técnica do código não equivale à homologação das fontes.
