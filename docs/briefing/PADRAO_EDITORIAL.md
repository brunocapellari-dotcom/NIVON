# Resumo Estratégico do Agronegócio — padrão editorial canônico v2

**Decisão de 26/10/2026.** Substitui as versões anteriores de uma página com conteúdo diferente e as versões intermediárias em duas páginas. A planilha final enviada pelo proprietário determina os indicadores; a última arte verde/dourada aprovada determina o estilo. **Este documento não comprova integração operacional ou homologação.**

## Formato visual aprovado

- **UMA ÚNICA PÁGINA VERTICAL:** agricultura e pecuária no mesmo documento, para leitura no celular, PDF e PNG.
- Título público: **RESUMO ESTRATÉGICO DO AGRONEGÓCIO**, sem marca/logotipo NIVON na imagem.
- Visual igual à referência aprovada: verde-escuro, verde-agro e dourado, fundo claro, faixas com seções, cards arredondados compactos, destaque de variações com setas verde/vermelho, cabeçalho com data e horário de corte de Mato Grosso.
- Ordem fixa: **cabeçalho → cotações em DUAS COLUNAS → fretes → notícias em DUAS COLUNAS**.
- Nas cotações, cada linha tem nome, valor, contrato/unidade e variação quando comprovados. **Remover cabeçalhos “Valor / Tipo / Variação”**; não remover a unidade correta do instrumento.
- **Não incluir fontes nem observações de fontes no rodapé da imagem.** Metadados completos, URLs, datas, unidade, metodologia e evidências **permanecem preservados na edição estruturada/auditoria interna**.
- Fretes mostram **apenas valor em R$/t**, sem volume, t/dia, capacidade ou linha de ausência de volume.
- Até **oito notícias**, com as posições 1–4 na primeira coluna e 5–8 na segunda; somente fatos divulgados dentro das **24 horas anteriores ao horário do corte**. Não preencher espaços com notícias antigas ou inventadas.
- Não adicionar outros blocos, indicadores, marketing, propaganda, CTA, impactos, resumo executivo final ou seção “monitorar”.
- Uma única fonte de dados alimenta PDF, PNG e texto de acompanhamento. Não editar as cotações manualmente sobre uma imagem.

## Cotações — coluna esquerda (ordem EXATA)

1. **CHICAGO (CBOT/CME):** Soja; Milho; Farelo de soja; Óleo de soja; Boi gordo; Gado vivo.
2. **NOVA YORK (ICE):** Café; Algodão; Açúcar.
3. **BM&F (B3):** Soja; Milho; Café; Boi.
4. **BOLSA DE ROSÁRIO:** Soja; Milho.

**Nota técnica:** nomes do quadro são campos escolhidos pelo proprietário e não constituem prova de contrato efetivamente listado. Não inventar cotação para instrumento sem negociação ou contrato oficialmente identificável, particularmente itens pecuários em Chicago e alguns futuros da B3.

## Cotações — coluna direita (ordem EXATA)

**MERCADO FÍSICO (14 itens)**

1. Soja Paranaguá (CEPEA)
2. Soja Sorriso (IMEA)
3. Milho (CEPEA)
4. Milho Sorriso (IMEA)
5. Pluma Algodão à Vista (CEPEA)
6. Açúcar Cristal SP (CEPEA)
7. Açúcar FOB Santos (CEPEA)
8. Café Arábica (CEPEA)
9. Boi Gordo (CEPEA)
10. Bezerro (CEPEA)
11. Boi Gordo a Prazo Sorriso (IMEA)
12. Vaca Gorda a Prazo Sorriso (IMEA)
13. Bezerro 12M MT (IMEA)
14. Escala de Abate MT (IMEA)

**COMBUSTÍVEL E MOEDA (6 itens)**

1. Brent
2. Paridade Importação
3. Diesel S10 Sorriso
4. Diesel S10 Rondonópolis
5. Etanol (B3)
6. Dólar

A **escala de abate é duração, em dias**, não preço. Paridade de importação requer a metodologia e produto da fonte. O dólar precisa de modalidade informada. Não substituir os dois diesel municipais por “média Brasil”.

## FRETES E LOGÍSTICA — somente R$/t

| Corredores principais | Outras rotas — referência |
|---|---|
| Sorriso → Rondonópolis | Sorriso → Paranaguá |
| Sorriso → Dom Aquino | Sorriso → Santos |
| Sinop → Miritituba | Sorriso → Uberaba |

Não exibir volumes, **nem mesmo volume de referência**. Quando não existir frete auditável e atual, usar **Não verificado**, sem reciclar números da demonstração. Frete anunciado/informado não deve ser tratado como frete pago/contratado.

## NOTÍCIAS DAS ÚLTIMAS 24 HORAS

Até oito matérias não repetidas de agricultura ou pecuária: **até quatro na coluna esquerda e quatro na direita**. Cada notícia deve ter tema, título curto, síntese de uma ou duas linhas e horário original verificado. Não reproduzir matéria antiga para preencher card.

## Segurança editorial e unidades

- O arquivo `templates/briefing/edicao_exemplo_2026-10-21.json` e as capturas de tela são **referências históricas/visuais**, não dados atuais. Não alimentar a edição diária com essas cifras.
- Para publicar uma cotação exigir: fonte, URL, data de referência, praça, contrato/ativo, moeda, unidade, natureza do dado e comparação homogênea para variação. Em caso de falta, **Não verificado**.
- **Nunca confundir US$/bu com ¢/bu; US$/t com R$/sc; ¢/lb com R$/sc; R$/@ com R$/cabeça; R$/L com R$/m³.** Cada instrumento pode ter data de fechamento diferente; a faixa superior não deve afirmar fechamento universal inexistente.
- Indicadores de previsão ou estimativas são rotulados; não se apresentam como observados.
- Notícias exigem data e hora originais, link, fonte e avaliação dos direitos de uso. Omitir o rodapé de fontes é apenas decisão de layout: a cadeia de evidências continua obrigatória.
- **Proibido adicionar CRB, WTI, Diesel S10 média Brasil**, ração, milho extra ou energia extra, volumes, fretes da pecuária separados, blocos ou métricas não autorizados.
- Em demonstrações sem dados reais, indicar explicitamente **MODELO — SEM DADOS REAIS**; nunca preencher com números plausíveis inventados. Modelo aprovado não implica autorização de publicação ou integração com Google Cloud/WhatsApp.
- Não recriar a arte livremente por geração de imagens a cada edição. Manter **template editável fixo** que só recebe dados validados.

## Arquivos e status

- `templates/briefing/modelo_visual.html` — arte editável, uma página.
- `templates/briefing/modelo_sem_dados.json` — campos vazios para prévia sem cotações fabricadas.
- `scripts/briefing/render_briefing.py` — renderização de PDF, não coleta ou envia conteúdo.
- `templates/briefing/edicao_exemplo_2026-10-21.json` — histórico v1 **descontinuado para produção**, preservado apenas para rastreabilidade.

**Controle de mudança:** qualquer inclusão, exclusão ou realocação de indicador exige decisão explícita do proprietário e alteração da especificação, não apenas modificação de imagem.
