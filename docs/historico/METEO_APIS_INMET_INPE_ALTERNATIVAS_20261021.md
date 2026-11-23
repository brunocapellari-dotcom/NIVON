# NIVON — alternativas públicas a BDMEP expirado (INMET / CPTEC-INPE)

Data da investigação: **21/10/2026**. Projeto NIVON de **uso não comercial**.
Estado: **implementado em branch com testes sintéticos offline**; não implica coleta
ativa nem conformidade/licença homologada.

## Causa do bloqueio

O proprietário informou que a URL privada BDMEP utilizada no live #39666951875
expirou. Não repetir tentativas desse link. O log original só
informou LINK_OU_DOWNLOAD_NAO_VALIDADO, sem status HTTP discriminado.
PR #86 trata diagnóstico seguro para links futuros, mas não é necessária
para acessar alternativas públicas. Nunca copiar URL tokenizada ao GitHub.

## Fontes oficiais e referências open-source

| Projeto/endpoint | Função | Classificação |
| --- | --- | --- |
| INMET https://apitempo.inmet.gov.br/estacoes/T e /M | Inventário de estações, código, UF, coordenadas, situação | Primária para METADADOS; não para observações |
| INMET https://portal.inmet.gov.br/dadoshistoricos/ | ZIPs históricos anuais 2000–2026, ano corrente parcial | Primária histórica; ingestão não habilitada |
| CPTEC/INPE https://servicos.cptec.inpe.br/XML/ | Busca por códigos, previsão 4/7 dias, estendida, METAR, ondas | Primária de documentação/previsão, verificar estabilidade |
| BrasilAPI https://brasilapi.com.br/api/cptec/v1/clima/previsao/{codigo}/{dias} | Previsão pontual JSON 1–6 dias | Agregador, não observado e não IBGE |
| GitHub ThiagoRBM/API_INMET | Script R de estação/catálogo | REFERENCE; não presumir observações horárias acessíveis |
| GitHub vbasilioo/crawler-dados-inmet | Levantamento de fontes e limitações de acesso horário | REFERENCE; não contornar bloqueios |
| GitHub rpradosiqueira/cptec | Cliente R: códigos, previsão, METAR, UV e ondas | REFERENCE; código GPL-3 e dados sujeitos a termos |
| GitHub framework-CPTEC/Sazonal | Pacote Python de previsão sazonal CPTEC | EVALUATE LATER |

Referências:
- https://portal.inmet.gov.br/dadoshistoricos/
- https://servicos.cptec.inpe.br/XML/
- https://www6.cptec.inpe.br/
- https://github.com/ThiagoRBM/API_INMET
- https://github.com/vbasilioo/crawler-dados-inmet
- https://github.com/rpradosiqueira/cptec
- https://github.com/framework-CPTEC/Sazonal
- https://github.com/BrasilAPI/BrasilAPI/issues/767
- https://github.com/BrasilAPI/BrasilAPI/issues/803

## Conectores NIVON implementados

1. **INMET** — src/nivon/inmet_estacoes_publicas.py
   - Uma consulta GET explícita a /estacoes/T ou /estacoes/M.
   - Valida campos e coordenadas; não afirma meteorologia medida ou dados atuais.
   - Rede off por padrão; sem redirects; timeout e bytes limitados.
2. **CPTEC/INPE via BrasilAPI** — src/nivon/cptec_previsao_brasilapi.py
   - Uma única localidade por código CPTEC já conhecido, até seis dias.
   - Identifica PROJETADO e separa fonte CPTEC de agregador BrasilAPI.
   - Preserva data de atualização, mas frescor_verificado=false.
   - UV zero não significa medição UV homologada (há divergências conhecidas).
   - Rede off por padrão; sem redirects; timeout e bytes limitados.
3. **Testes offline** — tests/test_meteo_publica_inmet_cptec.py
   - Fixtures sintéticas sem chamadas HTTP reais; validação de limites,
     parsing, erros sanitizados, códigos territoriais e natureza dos dados.

Não contornar bloqueios horários por browser headless ou scraping, não baixar
BDMEP expirado, não publicar nem carregar o BigQuery, não criar agendas.
Código aberto e endpoint público não implicam licença irrestrita.

## Próximos gates

1. Uma consulta de catálogo INMET pontual e uma previsão CPTEC de localidade
   conhecida, registrando somente métricas agregadas e status sanitizados.
2. Avaliar frescor, cobertura e qualidade contra a fonte primária CPTEC/INPE;
   confirmar termos de uso/atribuição/armazenamento do uso não comercial.
3. Para séries históricas observadas, usar ZIPs anuais oficiais INMET após
   homologação de licença e esquema e com armazenamento persistente controlado.
4. Somente então integrar contratos de dados NIVON, persistência e pipelines.

REGRA: metadado de estação não equivale a medição meteorológica; previsão
é PROJETADO, jamais OBSERVADO; toda coleta traz fonte e data de referência.
