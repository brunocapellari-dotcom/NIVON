# NIVON — Integrações nacionais: evidências, entregas e bloqueios

Data: 19/10/2026. Base da alteração: `feat/nucleo-motores-v0-1-20261016`.
A implementação em branch de revisão **não** é deploy, homologação nem autorização comercial.

## Mudanças implementadas

- `config/lineup_escopo_nacional.v1.json`: 35 portos organizados constantes na lista da ANTAQ mais dez candidatos privados/complexos relevantes (não é o universo completo de TUP).
- `config/fontes_nivon_master.v1.json`: de 90 a **126 datasets**; 45 `LINEUP_*`, um novo `ANP_PPI_COMBUSTIVEIS`.
- `config/rotas_coleta.v1.json`: 126 rotas 1:1, todas sem execução automática, direito ou redistribuição presumidos.
- `config/matriz_produtos_indicadores.v1.json`: 45 line-ups associados à frente marítima.
- `src/nivon/lineup_nacional.py`: normalização e consolidação de escalas por porto/produto/situação; diferencia programação, evento físico e carga realizada; exige DUV + ID de lote para conciliação de tonelagem.
- `src/nivon/anp_ppi.py`: parser XLSX com layout estrito e comparação PPI/produtor apenas com datas, unidade e tributos comparáveis.
- `src/nivon/fertilizantes.py`: agrega dados de importações por NCM, tonelagem e valor FOB sem representar média FOB como cotação CFR.
- `src/nivon/eventos_editoriais.py`: deduplicação conservadora de títulos relacionados, ligada ao briefing existente de notícias publicadas nas últimas 24h.
- `src/nivon/entrega_whatsapp.py`: contrato de template aprovado e opt-in para canal separado de envio WhatsApp; bloqueado para envios sem autorização comercial.

**As rotas estão desativadas**, inclusive as dos portos com URLs específicas já listadas na versão anterior.

## Cobertura geográfica / regra contra omissões

Fonte primária do escopo dos 35 portos organizados:
https://www.gov.br/antaq/pt-br/assuntos/instalacoes-portuarias/portos/tarifas-das-autoridades-portuarias

Fonte para descobrir TUP e instalações privadas:
https://www.gov.br/antaq/pt-br/assuntos/instalacoes-portuarias/instalacoes-privadas

Para o Arco Norte, o inventário considera Santarém, Vila do Conde/Barcarena, Belém, Santana,
Porto Velho, Manaus, além de candidatos como Miritituba e Itacoatiara. Santos, Paranaguá, Rio Grande,
São Francisco do Sul, Itaqui, Suape, Aratu, Vitória e Itaguaí também fazem parte do cadastro.

A fonte pode informar **escala planejada** sem mostrar atracação; AIS pode mostrar aproximação
sem informar mercadoria; estatística ANTAQ mensal não prova line-up de hoje.
Nunca somar TEGRAM/ITAQUI ou terminais de Barcarena com porto pai sem chave reconciliada.

## Bloqueios restantes, sem solução fictícia

| Área | Já codificado | Para entrar em produção |
| --- | --- | --- |
| 35 portos organizados | Cadastro e formato canônico, 45 rotas | Localizar fonte de navios de cada autoridade, licença, HTML/PDF real e testes em três coletas separadas |
| TUP/terminais privados | 10 candidatos por impacto agroindustrial | Descobrir e classificar o cadastro ANTAQ integral; autorização por operador e acesso a feed quando existir |
| ANTAQ realizado | Contratos separados de line-up | Verificar acesso atual ao Estatístico Aquaviário/SDP e URL/dados estruturados; não contornar WAF |
| ANP PPI | Dataset, URL, parser XLSX e spread tributário | Fixture real, layout, regras tributárias vigentes, publicação S&P e licença de redistribuição |
| Fertilizantes importação | Motor de NCM/FOB | Homologar tabela NCM vigente e cargas do MDIC, histórico, produtos brasileiros e correlações |
| Fertilizantes CFR | Contratos CME UFB/MFC e análise metodológica candidatos | Licença e publicação real de preços por fornecedor; sem isso mostrar indisponível, nunca criar cotação diária |
| CME/ICE e CEPEA | Fontes cadastradas com gate de direitos | Direito escrito de coleta/armazenamento/redistribuição, preços e períodos licenciados; dado atrasado não é live |
| Notícias | Janela 24h, autorização de publicação e agrupamento | Fontes com horário de publicação verificável e permissões, testes anti-repost e julgamento editorial |
| WhatsApp | Payload Cloud API para resumo/link e envio explícito | Conta Business, token, telefone, opt-in, template aprovado, URL do briefing, webhook de entrega, tarifa aprovada |
| Operação 24/7 | Nenhum deploy/agenda feito | Projeto Google configurado, backend agendado, storage durável, segredos e orçamento, homologação antes do deploy |

## Checklist da homologação, por fonte

1. Direitos documentados para `LEITURA`, `COLETA`, `ARMAZENAMENTO`, `PUBLICACAO_DERIVADA` e redistribuição comercial; fonte aberta não implica licença de republicação.
2. Três amostras reais em datas diferentes e parser que falha fechado quando o layout muda.
3. Validação de `competencia`, `referencia`, `publicacao`, `coleta`, fuso horário, NCM, unidade, município, DUV/IMO e IDs de lote.
4. Snapshot bruto/hash permitido, histórico retrospectivo permitido, atualização incremental, dedup e backup.
5. Alertas sobre fonte quebrada, cobertura, atraso, alterações, omissões e dados presumidos.
6. Para diário: notícia publicada entre `agora-24h` e `agora`; preço semanal/mensal identificado com sua **competência**.
7. Ensaiar geração e entrega de ponta a ponta em modo de homologação, confirmar destinatário e custo antes da ativação.

Comandos para ambiente de testes (sem deploy):

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m nivon.catalogo_fontes --resumo
PYTHONPATH=src python -m nivon.rotas_coleta --resumo
```

`openpyxl` só é necessário para testar o parser PPI: `pip install -e '.[excel]'`.

A revisão em PR pode executar workflows já presentes no repositório, mas **não deve** publicar
relatório como se esses coletores estivessem homologados.
