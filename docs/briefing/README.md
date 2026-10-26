# Produtos editoriais NIVON

## 1. Resumo Estratégico do Agronegócio — diário

Modelo oficial fixado em [PADRAO_EDITORIAL.md](PADRAO_EDITORIAL.md) (versão 2, 26/10/2026): **uma página**, agricultura e pecuária juntas, verde/dourado, mercado físico e futuros, diesel municipal, seis fretes somente em R$/t, até oito notícias em duas colunas, **sem rodapé de fontes na arte**. Preservar fontes e datas no pacote de auditoria da edição.

- `../../templates/briefing/modelo_sem_dados.json`: esqueleto v2 sem números reais.
- `../../templates/briefing/modelo_visual.html` e `../../scripts/briefing/render_briefing.py`: **renderizador legado em processo de atualização** para a v2; **não usar para publicar a versão aprovada enquanto não houver compatibilidade completa**, principalmente eliminação de volumes e notas de rodapé.
- `../../templates/briefing/edicao_exemplo_2026-10-21.json`: edição histórica v1, **nunca usar como fonte atual**.

## 2. Relatório Semanal de Plantio e Colheita — terça-feira

Novo produto **separado** do briefing diário. Leia [RELATORIO_SEMANAL_PLANTIO_COLHEITA.md](RELATORIO_SEMANAL_PLANTIO_COLHEITA.md).

- Base de atualização: CONAB e IMEA publicadas na segunda-feira anterior, verificadas na terça.
- **Um mapa por cultura + operação**. Exemplo: colheita da soja, plantio do milho e plantio do algodão = **3 mapas**; não misturar atividades em um mapa.
- Respeitar a granularidade geográfica oficial e mostrar fonte, safra, percentual e data; sem preenchimento sintético.
- Destino inicial: ChatGPT na terça de manhã. Coleta automatizada, mapas de produção e integração NIVON **não estão homologados** por esta especificação.

## Regras transversais

Não criar outro aplicativo, banco ou projeto de infraestrutura para estes produtos; no futuro, reutilizar os conectores CONAB/IMEA, os registros auditados e o template editorial existente. Nenhuma alteração em cronograma ou prompt de entrega comprova coleta real no Google Cloud.
