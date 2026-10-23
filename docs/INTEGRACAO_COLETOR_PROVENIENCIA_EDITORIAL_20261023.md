# NIVON — Integração do coletor à proveniência editorial

**Data:** 23/10/2026. **PR:** #53, branch de integração, status draft.
**Modo:** offline; nenhum coletor externo, envio ou deploy foi ativado.

## Implementação end-to-end

O pipeline passou a aceitar opcionalmente os artefatos de aquisição
já capturados pelo próprio NIVON e as atestações da origem, mantendo
a separação entre metadados observados e fatos verificados:

1. RSS/Atom: usar os bytes originais do coletor, identificados pelo
   SHA-256. Reexecutar o parser original, exigir fonte, URL, título,
   data de publicação e hora/fuso idênticos ao registro editorial.
   O horário de coleta nunca substitui published.
2. Página: receber o objeto já capturado por coleta_web.adquirir_fonte,
   conferir URL e hash do HTML. Interpretar exclusivamente o JSON-LD
   NewsArticle/Article e exigir datePublished único, com timezone e
   URL canônica da mesma notícia. Updated/dateModified não servem.
3. Duas evidências assinadas: PUBLICACAO_ORIGINAL pelo papel
   REVISAO_EDITORIAL e DIREITOS_PUBLICACAO pelo papel
   DIREITOS_PUBLICACAO. Assinaturas HMAC-SHA256 sobre fonte, URL,
   horários, licença, operações permitidas e hashes dos dois RAWs.
   Emissores previamente provisionados no registry SQLite, ativos
   e com chaves distintas. A revogação de emissor reprova provas
   anteriormente válidas.
4. Decisão editorial: exigir evento_id e evidencia_evento_id para
   a identidade do acontecimento; não derivar o ID de um RSS.
5. Somente quando toda a cadeia for coerente, produzir as notícias
   com publicacao_original_verificada=True para o preflight. A
   conciliação manual deixou de aceitar um ID isolado como prova
   dessa verificação.
6. Integração direta em pipeline_briefing.gerar_edicao_offline:
   páginas, atestados, eventos e chaves devem vir todos juntos.
   O resultado preserva as evidências originais não homologadas,
   acrescenta evidencias_origem_verificadas e preflight_com_origem.
   Sem inputs de comprovação, ambos ficam None e o preflight
   original permanece bloqueado.
7. Custódia opcional em SQLite: nivon_proveniencia_editorial grava
   apenas hashes de edição, URL, feed, página e atestados, fonte,
   data original e IDs de evidência. O registro é idempotente e
   bloqueia qualquer substituição incompatível. A gravação ocorre
   sob uma transação; falhas não deixam custódia parcial. HTML,
   XML, tokens e dados pessoais não são armazenados nessa tabela.

## Provas e regressões

A suíte de integração percorre o contrato real (em memória) do
coletor HTML autorizado, os RAWs do parser RSS, o registry
preprovisionado, as duas assinaturas, a identidade do evento, a
custódia e o preflight editorial da edição final.

Tentativas de adulteração testadas: XML modificado, HTML trocado,
SHA divergente, dateModified sem datePublished, divergência de
data original, licença trocada ainda que reassinada, emissor
revogado, assinatura inválida, comprovante ausente, URL divergente,
ID editorial ausente, prova substituída após persistência,
pacote parcial e edição com SHA divergente.

## Distinções obrigatórias de status

- ORIGEM_VERIFICADA_OFFLINE_SEM_PUBLICACAO: as assinaturas e hashes
  correspondem à cadeia fornecida; não é autorização de distribuição.
- CANDIDATOS_NAO_HOMOLOGADOS: resultado padrão do pipeline, quando
  não há atestados externos e capturas completas.
- preflight_com_origem.apto_revisao=False: mesmo com notícia verificada,
  preços, fretes, sessões e outras evidências ausentes continuam
  bloqueados. Não converter um sucesso de origem em aval global.
- enviado=False e envio_habilitado=False: nenhum callback de envio
  é liberado por esta integração.

## Dependências para produção

As chaves sintéticas não representam emissores reais. Antes de usar,
a operação deve validar quem administra os emissores, suas licenças
de coleta/armazenamento/publicação, o registro confiável de captura
HTTPS/TLS com origem canônica, armazenamento exportável de RAW,
revisão humana/independente e os acordos de uso. A consistência
criptográfica de bytes informados não prova sua origem na internet.

Os adaptadores de CEPEA, IMEA, CONAB, preços físicos, diesel, fretes,
portos e fechamentos exigem contratos próprios de evidência. Não
inferir frete negociado ou operação realizada a partir de divulgação,
nem permitir média municipal de frete.

O transporte Meta/WhatsApp segue bloqueado. Sem merge na main,
coleta real, cron, deploy, custo ou mensagens enviadas.
