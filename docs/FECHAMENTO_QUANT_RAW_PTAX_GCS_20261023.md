# NIVON — Lote 23/10/2026: Mercados, Fretes semânticos e quarentena GCS

**Corte GitHub consolidado:** commit Quant `cbacf1af6a5e009254c210a78623f560210ddfa5`,
PR #20 (`feat/quantitativo-validacao-asof-probabilidades-20261020`).
Código de Mercados incorporado por SHA até
`f4d5ffcd890902d170cd854af024b5b0064ed0d9`, em merges de dois
pais `3e3e1a87`, `9ef3b8f1` e `cfe6c10c`. A PR #21 pode
ter commits posteriores: **não estão cobertos por este corte**.
As PRs continuam `draft`. Sem merge à `main`.

## Entregas de código

### 1. Proveniência e conteúdo original de frete

`fretes_raw_ponte_quant.py` exige correspondência de ID, fonte,
publicação, SHA dos bytes, HMAC emitido pelo coletor e sequência temporal
válida antes do corte. Adicionada `fretes_raw_semantica.py` e
`verificacao_semantica=NIVON_FRETE_JSON_ESTRUTURADO_V1` no pipeline
quantitativo. A nova validação percorre **17 campos por registro**,
incluindo preços `Decimal`, carga de pedágio e frete cheio,
identidade econômica, descarga, produto, equipamento e PF/PJ.

O validador opera **somente** quando o provedor publicou originalmente
os bytes em JSON estruturado no schema V1. Recusa campos ambíguos,
duplicados, adulteração dos valores normalizados, números não finitos,
formatação monetária duvidosa, schema inesperado e conteúdo textual/
WhatsApp apresentado falsamente como JSON originalmente estruturado.
**Transcrição, OCR, áudio ou mensagens WhatsApp livres não estão
semanticamente validados.** HMAC não prova autoria do anunciante,
licença, origem independente ou veracidade econômica.

`scripts/ensaio_fretes_semantica_raw.py` percorre 28 registros, 4
séries de pares econômicos, 2 painéis R01, 28 HMACs, igualdade semântica,
preços alterados e formatos rejeitados. Sem previsão/publicação real.

### 2. Mercados PTAX e preparação para Google Cloud

A frente Mercados adicionou `ptax_cobertura_mercados.py`,
`ptax_quarentena_coleta.py`, `ptax_google_cloud.py`, scripts
de importação local individual e em lote e testes. Incorporados
sem sobrescrever componentes da PR #20; sem chamadas automáticas
à API BCB ou a GCS. A quarentena SQLite mantém objetos RAW e metadados
separados do ledger de mercado; aceita amostras fornecidas externamente,
valida conteúdo e SHA, protege alterações via triggers append-only,
não promove cotação a dado publicável e não presume autenticidade de fonte.

`scripts/ensaio_quarentena_ptax_gcs.py` valida recebimento, idempotência,
consultas, RAW/manifesto preparados para GCS, checksum de cada objeto,
bloqueio de upload padrão, alteração de digest e proibição de
`UPDATE`. Testes adicionais verificam HTTP/WAF e ausência de promoção
para `nivon_snapshots`. **Nenhum bucket foi criado, nenhum objeto foi
enviado e nenhuma cobrança cloud foi autorizada.** O adaptador de
upload exige confirmação explícita de direitos e orçamento; apenas
seus caminhos offline foram executados.

### 3. CI completo, em lote

- [GitHub Actions #39984387787](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39984387787):
  **SUCCESS, 1.818 testes Python, zero falhas, 5 skipped**, comando
  `python -m unittest discover -s tests -v`.
- E2E PTAX integrado **17 etapas sintéticas**, incluindo cobertura,
  editoria, quarentena e preparação GCS; E2E Fretes R01/Quant
  **10 etapas**; E2E frete estruturado **12 etapas**; E2E
  quarentena→GCS **11 etapas**. São execuções determinísticas adicionais
  no workflow da PR.
- Houve falha transitória anterior: `docker compose version`
  ficou sem resposta por 12 segundos no runner compartilhado.
  A sondagem opcional agora registra `SKIPPED` por timeout, em vez
  de confundir indisponibilidade do Docker com falha do núcleo. Testes
  estáticos de segurança de containers seguem obrigatórios, e Compose
  retornando schema inválido continua reprovado quando disponível.

## Bloqueios que continuam reais

1. **P0:** autenticação semântica de mensagens WhatsApp livres originais,
   extração com prova por campo, resolução de entidades e recebimento
   autorizado — não pode ser simulada por JSON criado após a extração.
2. **P0:** revisão do integrador das PRs e bases, com CI no merge
   definitivo; issue #25 depende dessa aceitação.
3. **P1:** direitos/licenças, origem externa confiável e vintages
   imutáveis; fonte coletada posteriormente não equivale a dado
   disponível na data prevista.
4. **P1:** execução real Google Cloud, IAM, bucket, orçamento,
   recuperação e observabilidade — **NÃO realizada**.
5. **P1:** validação prequential/hindcast real, pré-registro do holdout,
   comparabilidade econômica, drift e probabilidade calibrada.

**Garantia do lote:** código integrado e testado offline, não sistema
em produção nem fonte/forecast homologados.
