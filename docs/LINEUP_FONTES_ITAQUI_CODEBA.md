# NIVON — Fonte pública de line-up: Itaqui e CODEBA (19/10/2026)

Esta integração acrescenta **parsers HTML locais** e rotas oficiais, sem habilitar coleta ou publicação.

## Fontes oficiais pesquisadas
- Itaqui: https://www.portodoitaqui.com.br/porto-agora/navios
- Aratu-Candeias: https://www.codeba.gov.br/eficiente/sites/portalcodeba/pt-br/porto_aratu.php?secao=tportos_aratu
- Salvador: https://www.codeba.gov.br/eficiente/sites/portalcodeba/pt-br/site.php?secao=tportos_salvador
- Ilhéus: https://www.codeba.gov.br/eficiente/sites/portalcodeba/pt-br/site.php?secao=tportos_ilheus
- ANTAQ: https://www.gov.br/antaq/pt-br/noticias/2026/sistema-de-desempenho-portuario-esta-de-volta-em-nova-plataforma
- Painel estatístico ANTAQ (consulta pública, exportação ainda por homologar): https://aquarela.antaq.gov.br/

## Como integrar
1. Registrar permissões específicas por operação (coleta, armazenamento, derivação e redistribuição comercial).
2. `nivon.coleta_web.adquirir_fonte` preserva URL, hash e bytes, com domínio HTTPS e limites (bloqueado por padrão).
3. `nivon.ingestao_lineup_portais.processar_snapshot` valida hash/MIME/URL, decodifica e encaminha ao `nivon.lineup_portais.extrair_lineup_portal`.
4. Separa navios atracados, fundeados, esperados e, quando informados, despachados por seção e porto.
5. Não converte `Qtd.Carga` / `Qtd Carga Prev` em toneladas sem unidade verificada; não confunde despacho com tonelagem realizada.
6. Rejeita dados de linha com última atualização futura e sinaliza os desatualizados. CODEBA publica ETA, que não prova horário de publicação.
7. Não considera registros aptos ao briefing antes de licença, data de publicação e testes com HTML bruto atual.

## ANTAQ: reabertura não equivale a dataset já disponível
A ANTAQ reabriu o SDP em 08/10/2026 para o envio das informações pelos portos.
O SDP é o ambiente **de transmissão de dados das instalações**; não deve ser tratado
como API pública de leitura nem como line-up diário.
O painel aquarela/Estatístico Aquaviário é a rota candidata a dados realizados;
é necessário validar download, competência, API, cobertura e condições de uso.
O órgão informou prazos de regularização de informações atrasadas até janeiro de 2027.

## Evidência técnica
- Testes offline com fixtures sintéticas e validação de URL, hash, datas e unidade desconhecida.
- **Sem** captura HTML bruta em produção, homologação do parser, cronograma ou deploy.
- Branch de integração separada para não interferir nas alterações paralelas da PR #1.
