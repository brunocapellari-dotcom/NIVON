# NIVON — Primeira auditoria de logística terrestre e combustíveis (20/10/2026)

## Base de comparação e integração

- `NIVON/main`: somente README; não é aplicação operacional.
- Branch de referência: `feat/motor-tendencias-transversal-20261020`, PR #12 (draft); esta mudança é EMPILHADA sobre seu HEAD congelado, não em `main`.
- Legado: `AgroLogMT/models/logistics_corridors.py`, `contracts/logistics_corridor.v1.schema.json`, `gateway/freight_ingest.py`, `models/logistics_gis_benchmark.py`. Reutilizar conceitos mediante revisão, não copiar agregações heterogêneas.
- Diesel NIVON: `anp_diesel.py` (CSV e semana calendário **inferida**), `anp_diesel_store.py` (vintages offline), `anp_ppi.py` (PPI estimada, diferente de revenda); ANP LPC semanal em branch editorial #8 precisa reconciliação separada.
- ANTT: `antt_ferrovia.py` e `antt_ferrovia_csv.py` são fluxos ferroviários TU/TKU, nunca MDF-e rodoviário.

## Risco crítico corrigido nesta PR

O motor de ofertas da PR #12 calculava uma mediana diária de preços de **lotes de diferentes estabelecimentos** identificados apenas por origem municipal e destino. Tal estimativa não poderia servir de referência de frete por município e violava o contrato comercial definido. Agora a tendência exige:
`pickup_entity_id`, `transportadora_id`, `descarga_entity_id` e `regime` além de origem/destino, produto, veículo, pedágio e lotes resolvidos.
O resultado permanece *observado histórico*, não previsão. Não emitir probabilidades calibradas sem dados e backtesting as-of.

Novo módulo `fretes_registros.py` preserva separadamente cada registro anunciado com base, pedágio, cheio, características e proveniência. Republicações dependem de uma `oferta_id` canônica resolvida; alterações de preço são preservadas como eventos diferentes. Indicadores por município se limitam a CONTAGENS de estabelecimentos, transportadoras e publicações com exibição explícita dos IDs; nenhum preço municipal médio, mediano ou representativo é produzido.

`distancia_e_custo` oferece R$/TKU derivado apenas com distância rodoviária verificada; R$/km por veículo exige carga efetiva informada, e é receita hipotética derivada de anúncio, **não custo real operacional**.

## Matriz de lacunas e bloqueios

| Prioridade | Componente | Estado verificado em código | Próxima ação e aceite |
| --- | --- | --- | --- |
| P0 | Fretes WhatsApp / identidade | legado tem ingestão, NIVON tendências heterogêneas corrigidas nesta branch | integrar prova de `pickup_entity_id` e transportadora com origem da mensagem, resolver aliases auditáveis, conferir com casos reais e direitos |
| P0 | Diesel semanal ANP | parser mensal e store offline; semanal oficial em PR #8 | reconciliar ramos, testar >=3 edições XLSX reais com publicação e cobertura, determinar direitos/horário, habilitar somente após homologação |
| P0 | Histórico e vintages | código parcial offline | armazenar RAW autorizados fora do Git, SHA-256, publicação, coleta, referência, competência, backfill e revisões |
| P1 | Distâncias, pedágios, rotas | contrato AgroLog e benchmark GIS | integrar SNV/DNIT e concessões ANTT; avaliar OSM/OSRM com licenças e benchmark, roteamento operacional OFF |
| P1 | Fluxos ferroviários | parser ANTT existe | reconciliar códigos de estação, concessão, fonte, unidade TU/TKU e calendário; teste com XLSX real |
| P1 | Pressão de safra | não demonstrado E2E | linkar produção CONAB/IBGE, demanda portuária, chuva e disponibilidade de rota apenas com dados e indicadores comparáveis |
| P1 | Tendência/probabilidades | PR #12 gera tendência histórica sem skill real | treino separado por corredor/estabelecimento/condições, walk-forward, calibração, intervalos e abstenção |
| P2 | Diesel internacional | PPI existe, câmbio/ANP fontes parciais | integrar preço produtor/importação, ANP PPI, PTAX, defasagens, tributos e direitos; não confundir revenda e paridade |

## Corredores-alvo, sem distâncias ou fretes inventados

Sorriso–Rondonópolis; Sorriso–Dom Aquino; Sinop–Miritituba/Itaituba; Santos/Guarujá; Paranaguá; Uberaba/Araguari; demais rotas nacionalmente relevantes após confirmação de estabelecimentos e destinos. **Miritituba é terminal/localidade em Itaituba/PA, não código municipal próprio.** Não somar fluxos de destino distintos sem reconciliação do terminal e sentido.

## Status de execução

Código/testes sintéticos são somente provas de regras. Não houve coleta/armazenamento de dados reais, contato com WhatsApp, ativação de scheduler, serviço externo, recurso OCI, cobrança, deploy, merge ou autorização de previsão. Exigir CI no SHA final e revisão crítica antes de incorporação na PR de integração #13.

## Evidência externa de fontes oficiais verificada em 20/10/2026

- ANP, últimas semanas: https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas — semana 11–17/10/2026 publicada na página; manter hora de publicação da **edição baixada**, não a data de alteração genérica da página.
- ANP, séries semanais consolidadas desde 2013: https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-revenda-e-de-distribuicao-combustiveis/shlp/semanal/ — separar séries de Brasil, UF e município, sem confundir médias **ANP de DIESEL** com média de **FRETES de anúncios**; o veto de média municipal vale a preços de FRETES anunciados, não ao indicador público de diesel por município.
- ANTT, produção origem/destino ferroviário 2026 (licença CC BY): https://dados.antt.gov.br/pt_BR/dataset/sistema-de-acompanhamento-do-desempenho-operacional-das-concessionarias-siade/resource/c2854ec9-1cc5-4554-a1ae-96c5f37b5df6 — colunas Mes_Ano, Ferrovia, Mercadoria_ANTT, Estacao_Origem, Estacao_Destino, TU, TKU. Metadados atualizados em 02/10/2026; **estação não equivale a município**.
- ANTT, praças de pedágio: https://dados.antt.gov.br/pt_BR/dataset/praca-de-pedagio/resource/9aa29243-c54c-4084-bc3d-c44a75c9bd7e — cadastro não é tarifa por categoria de veículo nem comprova trajeto percorrido; exigir tabela tarifária datada e percurso verificado.
- DNIT, PNV/SNV https://www.gov.br/dnit/pt-br/assuntos/atlas-e-mapas/pnv-e-snv — base de malha viária, **não** distância comercial porta-a-porta sem roteador/topologia validada.

## Sensibilidade do diesel implementada (offline)

`diesel_pressao.py` gera cenário matemático **hipotético**: litros = distância operacional validada × consumo específico informado; custo combustível por t = litros × preço diesel por litro / carga informada. Diferença de custo por t NÃO implica repasse ao frete anunciado/contratado. Proíbe mistura DIESEL/DIESEL S10, ausência de evidência, número não finito e premissa fora de faixa. O preço ANP de revenda é amostral, não custo observado do transportador. Testes em `tests/test_diesel_pressao.py`.

**Gates preservados:** não há coleta automática de combustível, integração operacional da ANP semanal, custo real de frota, pagamento de pedágio ou volume observado a partir destes módulos.
