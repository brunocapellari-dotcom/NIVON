# NIVON — Consolidação operacional de coletores e line-up (19/10/2026)

**PR de revisão:** https://github.com/brunocapellari-dotcom/NIVON/pull/8  
**Base:** `feat/nucleo-motores-v0-1-20261016` (PR #1)  
**Nenhum deploy, contrato pago, agendamento ou envio automático foi executado.**

## Entregas consolidadas

Esta PR concentra o trabalho que antes estava fragmentado nas PRs #4 e #5:

1. **Itaqui, Aratu-Candeias, Salvador e Ilhéus**: parser de HTML e integridade de snapshots, com páginas institucionais candidatas. Não converte `Qtd.Carga` em tonelagem sem unidade validada, nem atribui timestamp de publicação pelo horário da captura.
2. **CDP Santarém**: interpretação de tabela com múltiplas mercadorias por linha. WDT é identificador interno da tabela, e não DUV único da escala. Datas antigas são recusadas como situação atual.
3. **ANTAQ histórico 2010+**: arquivos ZIP anuais de atracações/cargas e catálogo de mercadorias, recebidos legalmente, importados offline para SQLite por edição SHA. Diferencia dados observados mensais de programação diária.
4. **ANTAQ HTTPS**: cliente opcional com URLs fixas e licença explícita, sem redirect/WAF bypass, sem envio de credenciais e sem execução automática.
5. **Ponte ao briefing**: somente DUV, produto, situação, data e licença aprovados entram em indicadores `PORTOS`. Catálogo canônico permanece com `enabled=false`, `collection_authorized=false` e `commercial_redistribution_authorized=false`: dados não homologados são rejeitados.
6. **Diagnóstico nacional**: `python -m nivon.diagnostico_portos` avalia 35 portos organizados e 10 candidatos privados, separando página institucional, índice de navegação e ausência de URL operacional. Um índice não equivale a coletor ativo.
7. **PortosRio**: endereço institucional oficial para **Rio de Janeiro, Itaguaí, Niterói e Angra dos Reis**, como `OFFICIAL_INDEX`, não como line-up homologado. A programação do Porto do Forno estava marcada como 'em breve'. Rio Grande possui referência oficial a Portoweb/relatório dinâmico, ainda sem validação de documento atual.

## Origem oficial dos dados

- ANTAQ dados abertos: https://www.gov.br/antaq/pt-br/acesso-a-informacao/dados-abertos
- ANTAQ Estatísticos Aquaviários: https://www.gov.br/antaq/pt-br/central-de-conteudos/publicacoes-da-antaq/estatisticos-aquaviarios
- ANTAQ ZIPs, **candidatos não homologados**: `https://estatistica.antaq.gov.br/ea/txt/{ANO}.zip`, `https://estatistica.antaq.gov.br/ea/txt/Mercadoria.zip`
- CDP: https://www.cdp.com.br/companhia-docas-do-para/programacao-de-navios/
- Itaqui: https://www.portodoitaqui.com.br/porto-agora/navios
- CODEBA: https://www.codeba.gov.br/
- PortosRio: https://portosrio.gov.br/pt-br/portos/programacao-de-navios
- Portos RS: https://www.portosrs.com.br/

URLs institucionais exigem comprovação dos direitos por operação antes de coleta,
persistência ou distribuição comercial. Não presumir que um endereço permita scraping.

## Critérios para homologação individual

- Captura de **três documentos reais em datas distintas**, de fontes legalmente permitidas, preservando hashes e cabeçalhos de publicação quando disponíveis.
- Sem quebra silenciosa de schema, colunas, codificação, datas, DST, tonelagem ou status.
- Reconciliação de DUV/IMO/lote e vínculo do terminal ao porto-pai sem dupla contagem.
- Confirmação do direito de leitura, armazenamento, transformação e publicação derivada.
- Compensação para fontes sem data de atualização: não mostrar 'atual', não inferir navios zero.
- Armazenamento histórico durável em servidor autorizado, backfill, atualização incremental e backup com teste real de restauração.
- Simulação editorial E2E com dados reais sob licença e confirmação de que nenhum envio nem modelo preditivo é habilitado apenas por teste sintético.

## Comandos offline

```sh
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m nivon.diagnostico_portos
PYTHONPATH=src python -m nivon.rotas_coleta --resumo
```

Para importar arquivos ANTAQ previamente obtidos de forma autorizada:

```sh
PYTHONPATH=src python scripts/importar_antaq_historico.py --ano 2024 \
  --anual /dados/2024.zip --mercadorias /dados/Mercadoria.zip \
  --banco /dados/antaq.sqlite --coletado-em 2026-10-19T22:00:00-03:00
```

A CLI usa SQLite local, não realiza backup automático nem resolve permissões de publicação.

## Dependências externas (não resolvidas por novos arquivos de código)

| Frente | Próximo desbloqueio |
|---|---|
| ANTAQ | ZIPs públicos realmente acessíveis; termo de uso e amostra real com schema vigente |
| Rio Grande, PortosRio, CODEBA, Itaqui, CDP | Endpoint final e documentação de atualização/uso; snapshots reais e revisão operacional |
| Arco Norte privado | Instalações autorizadas (Miritituba, Barcarena, Itacoatiara), permissão por operador |
| CME e ICE | Market data e licenças de retransmissão, ou fonte alternativa legalmente equivalente |
| Fertilizantes CFR Brasil | Boletins/preços com licença, periodicidade e metodologia contratualmente verificadas |
| WhatsApp | Conta Meta Business, opt-in, template, URL do briefing, webhook, aprovação de custo |
| Infraestrutura | Serviços em nuvem com scheduler e armazenamento durável: nada contratado/implantado aqui |

**Regra:** terminar a ingestão e a homologação de cada fonte antes de declarar
o briefing como operacional. Catálogo, parser ou simulação isolados não são go-live.
