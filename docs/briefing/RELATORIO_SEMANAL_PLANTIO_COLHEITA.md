# Relatório Semanal de Plantio e Colheita — NIVON

**Decisão do proprietário — 26/10/2026.** Relatório visual complementar e **separado** do Resumo Estratégico do Agronegócio, entregue **toda terça-feira de manhã** após as divulgações de segunda-feira da **CONAB** e do **IMEA**. O briefing diário continua com sua programação e modelo próprios.

## Modelo gráfico aprovado

- Usar a **imagem de referência anexada pelo proprietário na conversa de 26/10/2026** como base de estilo, hierarquia, cores e disposição dos percentuais; esta especificação registra as regras funcionais, mas não substitui o próprio arquivo visual de referência.
- **Um mapa independente para cada combinação de CULTURA + OPERAÇÃO.** Não juntar diferentes lavouras, plantio e colheita em um só mapa. Não há número máximo arbitrário de mapas.
- **Exemplo canônico de terça com três atividades:** (1) COLHEITA da SOJA — mapa próprio; (2) PLANTIO do MILHO — mapa próprio; (3) PLANTIO do ALGODÃO — mapa próprio. Não são dois mapas nesse caso: são **três**.
- Se a mesma cultura exigir mapa de plantio e de colheita, produzir dois mapas específicos.
- A composição semanal pode ter um, dois, três ou mais mapas conforme atividades realmente acompanhadas e dados disponíveis. Dispor os mapas em páginas adicionais se não couberem legivelmente; não comprimir até perder leitura.
- Título/legenda identificam de forma destacada **CULTURA**, **PLANTIO ou COLHEITA**, **SAFRA**, **DATA DE REFERÊNCIA**, **FONTE** e **PORCENTAGEM (%)**, com variação semanal em **pontos percentuais (p.p.)** somente após confrontar observações comparáveis.
- Respeitar a **granularidade geográfica efetiva publicada**. CONAB pode informar Brasil/UF; IMEA pode informar o estado/regiões de MT. Nunca colorir município ou microrregião com percentual estadual sem divulgação nesse nível.
- Quando CONAB e IMEA publicarem indicadores com recortes/metodologias diferentes, preservar mapas ou painéis separados e identificados. Não calcular média arbitrária nem tratar fontes como intercambiáveis.
- Manter estilo consistente com as artes anteriores sem inventar cartografia, percentuais, delimitação de regiões, fontes ou datas.

## Coleta, tempo e conteúdo

- A terça-feira usa as **publicações efetivamente disponibilizadas na segunda-feira anterior**, mas deve conferir se foram realmente divulgadas; calendários e horários podem mudar.
- Para cada observação registrar: `fonte`, `url`, `data_publicacao`, `data_referencia`, `data_coleta`, `safra`, `cultura`, `operacao`, `localidade_id`, `escala_geografica`, `percentual`, `metodologia`, `status_evidencia`, e, se aplicável, `variacao_pp`.
- Percentual é **avanço acumulado da área**, conforme metodologia oficial; não confundir com produção em toneladas, produtividade ou área absoluta.
- Manter histórico semanal por fonte e recorte geográfico para comparação temporal.
- Se a fonte atrasar, estiver indisponível ou não trouxer dados de granularidade suficiente para o mapa: informar **não publicado/sem atualização verificada** e usar quadro textual/tabela curta verificada, **sem colorir áreas com dados antigos**.
- Não preencher mapas a partir de projeções ou extrapolações sem autorização e rotulagem explícita.
- A comunicação pode incluir um resumo textual de atualização, mas não substituir os mapas por notícias gerais.

## Entrega e aceite

- **Canal inicial:** conversa no ChatGPT, na terça de manhã, sem instalar aplicativos no computador ou celular.
- **Independência:** não modificar o relatório diário de cotações, fretes e notícias; a terça-feira terá dois produtos separados.
- **Implantação futura no NIVON:** reaproveitar os conectores e a camada canônica CONAB/IMEA e o mesmo pipeline editorial; não criar banco, app, frontend ou serviço novo para esta publicação.
- **Aprovação da edição:** percentuais auditados contra documentos originais, polígonos geográficos corretos, mapas distintos por cultura/operação, datas identificadas, legibilidade no celular e nenhuma comparação semanal sem períodos comparáveis.
- **Estado inicial:** especificação editorial salva; **não** confundir com coleta automatizada, mapas gerados com dados reais, deploy ou publicação operacional via NIVON.
