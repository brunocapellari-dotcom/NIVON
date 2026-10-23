# NIVON — Proveniência textual original WhatsApp para fretes (23/10/2026)

**Branch:** PR #20 (`feat/quantitativo-validacao-asof-probabilidades-20261020`).
**Estado:** implementado e testado com fixtures; não ativado na Meta,
na nuvem, em grupos reais ou em sistema de publicação.

## Cadeia de evidências executada

`scripts/ensaio_fretes_texto_whatsapp.py` exercita a cadeia real
entre módulos com **28 webhooks originais sintéticos**:

1. Recebe os **bytes exatos** de um envelope WhatsApp Cloud API.
2. Confere HMAC `X-Hub-Signature-256` com segredo do runtime, sem
   reconstruir/reescrever o JSON para verificar a assinatura.
3. Exige um único evento/mensagem `text`, seu
   `provenance.source_event_id` idêntico ao ID da mensagem e
   timestamp de origem consistente com o do `FreightEvent`.
4. Confere `entry.id` contra `waba_id` do **atestado assinado de
   DIREITOS** e valida, por chaves de runtime independentes, as
   atestações de DIREITOS e RESOLUÇÃO de entidades do WhatsApp AI.
   Atividade de teste não implica que a Meta validou direitos de uso
   comercial do provedor ou o cadastro dos estabelecimentos.
5. Extrai, da mensagem textual **estritamente rotulada**, exatamente
   os 11 campos: FRETE (R$/t), PEDÁGIO, PRODUTO, ORIGEM, DESTINO,
   EMBARQUE, TRANSPORTADORA, DESCARGA, EQUIPAMENTO, REGIME (PF/PJ)
   e DATA. Verifica menção literal e compara `Decimal` de preços
   com `OfertaFrete`, sem inferir pedágio, tarifa cheia ou regime.
6. Armazena **apenas em memória** offsets em caracteres do corpo e
   hashes SHA dos trechos, sem devolver telefone, RAW, nomes originais
   ou texto de mensagens nos resultados. Esses offsets **não** são
   offsets de bytes no envelope JSON original.
7. Passa `OfertaFrete` tipada ao consolidador e motor de tendências
   pareadas R01, preservando identidade por
   `municipio+pickup+transportadora+destino+descarga+produto+equipamento+PF/PJ`
   e separação das condições de pedágio, sem média por município.
8. Mantém o Quant **bloqueado para uso preditivo real**:
   `asof_pronto=False`, `publicavel=False`. O exercício de Meta
   autenticado por HMAC **não** atesta receipt imutável de fonte
   externa nem licença/retenção do WhatsApp.

## Controle de replay e quarentena

- `executar_lote_whatsapp_rotulado_offline`: modo
  **atômico/fail-closed**. Se um dos eventos falha, não entrega
  painel do lote como se tudo estivesse validado.
- `triar_lote_whatsapp_em_quarentena_offline`: modo de triagem
  **não persistente**, que retém apenas anúncios aprovados para
  análise descritiva separada e devolve, dos rejeitados, somente
  SHA do RAW e estado `QUARENTENA_SEM_PROMOCAO`. Reenvios com
  `source_event_id` ou RAW repetido não são contados como novos.
- Com 30 pacotes de fixture (28 admissíveis, um texto livre e um
  replay), somente **28** entram em 4 séries individuais e 2 painéis
  descritivos; **2** seguem para quarentena de saída em memória.
- Não foi criado repositório persistente para RAWs ou rejeições:
  **quarentena offline != armazenamento imutável**. Definir
  direitos, retenção e proteção de dados antes de persistir.

## Critérios de rejeição implementados

Assinatura Meta ausente/incorreta; conta receptora diferente da
autorizada; atestação de direitos ou resolução adulterada; ID ou
timestamp divergente; webhook com múltiplas mensagens ou status;
texto sem os onze rótulos esperados, rótulos duplicados ou campo
ausente; frete/pedágio divergente; data comercial antiga;
produto/transportadora/embarque/descarga incompatíveis com a menção
literal; condições de pedágio/regime ambíguas; replay no lote ou
amostra posterior ao corte.

**Nunca** inferir a identidade canônica simplesmente da menção
textual. O ID canônico continua subordinado a resolução assinada,
não comprovada por um teste com chaves fictícias.

## Evidência CI

- [GitHub Actions #40000366597](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40000366597):
  primeira integração offline, **1.827 testes, zero falhas, 5 skipped**.
- [GitHub Actions #40000698731](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40000698731):
  vínculo obrigatório com WABA autorizada e bloqueio de replay,
  **1.829 testes, zero falhas, 5 skipped**.
- [GitHub Actions #40001225772](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40001225772):
  triagem de quarentena sem PII, **1.831 testes, zero falhas,
  5 skipped**, mais E2E de 28 mensagens e cenário de 30 pacotes.

Os scripts E2E existentes de PTAX, Fretes R01, RAW JSON estruturado e
quarentena PTAX→GCS permanecem executados no mesmo workflow;
ninguém ativou coleta real, upload GCS ou cobrança cloud.

## Estado de integração e próximos lotes

- Mercados PR #21 incorporada até SHA
  `3f0f04d0d36a3bb643ec9305544abaa79e3d89eb`,
  por merge `77f8d30b784de477560aee0bc68bb164d20a5b83`.
  A PR #21 seguia ativa e possuía commits posteriores, incluindo
  coletores PTAX e sincronização GCS; não estão homologados por este CI.
- P0: ampliar interpretação com evidências para mensagens textuais
  livres, sem confundir OCR/IA/transcrição com RAW assinado.
- P0: corpus original autorizado e governança de tenant/WABA,
  eventual prova externa do provedor, resolução geográfica independente,
  tratamentos de republicações e direitos de armazenamento.
- P1: quarentena persistente sob autorização e retenção protegida;
  correlação com data de publicação e coleta real, e auditoria temporal.
- P1: dados históricos reais para testes cegos de previsão e gates
  de calibração. Não produzir scores preditivos em produção a partir
  desta validação de contratos.

**Não houve deploy, merge em `main`, escrita no Google Cloud nem
envio de WhatsApp neste ciclo.**
