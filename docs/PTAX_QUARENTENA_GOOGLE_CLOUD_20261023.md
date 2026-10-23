# NIVON — Recepção PTAX em quarentena e armazenamento no Google Cloud

**Atualização:** 23/10/2026. **Implementação:** PR #21, ainda em rascunho.

## Objetivo e classificação

Fluxo disponível: **captura externa autorizada → arquivo JSON OData
original + manifesto de coleta → importação atômica em quarentena SQLite
→ verificação de bytes, URL, timestamp e lote → preparação de objetos
Google Cloud Storage → arquivamento condicionado à autorização**.

A existência da captura externa não prova a origem ou hora de publicação
independente: o importador não cria essa prova. Nenhum arquivo importado
nesta via entra em `nivon_snapshots` ou no briefing; toda entrada
permanece `AMOSTRA_EXTERNA_NAO_HOMOLOGADA`.

### Fontes e licença

- Catálogo BCB: https://dadosabertos.bcb.gov.br/pt_BR/dataset/dolar-americano-usd-todos-os-boletins-diarios
- Documentação OData: https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/documentacao
- O BCB classifica o dataset em ODbL. A licença ODbL permite inclusive
  uso comercial, **condicionado** às suas regras de atribuição, avisos,
  compartilhamento quando cabível e disponibilização de base derivada
  ao público nos cenários especificados. Texto completo:
  https://opendatacommons.org/licenses/odbl/1-0/
- Uso **interno** e **redistribuição pública/WhatsApp** são operações
  diferentes; antes de divulgação revisar a maneira de apresentar os
  avisos de fonte/licença e se a construção é obra produzida ou
  base de dados derivada.
- A política operacional da fonte no NIVON mantém `enabled=false`,
  `collection_authorized=false` e
  `commercial_redistribution_authorized=false`. Este PR não
  altera esses parâmetros.

## 1. Arquivos que o coletor precisa produzir

Uma captura deve preservar **bytes recebidos** e um
manifesto JSON, sem reserializar a resposta OData antes de calcular SHA.
Exemplo de estrutura do manifesto, com valores fictícios:

```json
{
  "fonte_declarada": "BCB_PTAX",
  "moeda": "USD",
  "consulta_url": "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)?%40dataInicial=%2710-20-2026%27&%40dataFinalCotacao=%2710-20-2026%27&%24format=json&%24top=500",
  "coletado_em": "2026-10-20T18:00:00+00:00",
  "status_http": 200,
  "cabecalhos_http": {
    "Content-Type": "application/json",
    "Content-Length": "123",
    "Date": "Tue, 20 Oct 2026 18:00:00 GMT"
  },
  "raw_sha256": "HASH_SHA256_REAL_DO_ARQUIVO_RECEBIDO"
}
```

Valores fictícios não devem ser usados em produção. O `Content-Length`
deve corresponder aos bytes reais quando fornecido. O campo
`coletado_em` precisa preservar timezone; `Date` HTTP não equivale
ao horário oficial da publicação PTAX. A URL deve vir de
`planejar_consultas_ptax`, sem parâmetros extras.

Boletins ausentes: `{"value":[]}` é registrado como **resposta vazia**
(não necessariamente feriado) e **nunca** como cotação zero. A via
operacional anterior, que exige observações, permanece inalterada.

## 2. Importação de um arquivo e importação em lote

Uma captura, sem rede:

```bash
PYTHONPATH=src python scripts/importar_ptax_quarentena.py \
  --raw /dados/ptax/odata_0.json \
  --manifesto /dados/ptax/manifesto_0.json \
  --banco /dados/nivon_ptax_quarentena.db
```

Para uma pasta com até 50 pares de arquivo+manifesto, declarar
`lote.json` (nomes de arquivos da mesma pasta, sem caminhos externos):

```json
{
  "versao": "NIVON_PTAX_IMPORTACAO_LOTE_V1",
  "capturas": [
    {"raw": "odata_0.json", "manifesto": "manifesto_0.json"},
    {"raw": "odata_1.json", "manifesto": "manifesto_1.json"}
  ]
}
```

Executar um único comando:

```bash
PYTHONPATH=src python scripts/importar_lote_ptax_quarentena.py \
  --pasta /dados/ptax \
  --lote lote.json \
  --banco /dados/nivon_ptax_quarentena.db
```

O lote pré-valida **todos** os itens; falha de uma captura reprova
o lote inteiro e não grava mudanças parciais. A quarentena é
content-addressed e idempotente; múltiplas coletas de mesmos bytes
preservam eventos distintos. Triggers bloqueiam UPDATE/DELETE
acidentais, mas um administrador do SQLite ainda pode alterar
o arquivo ou os triggers. Portanto **não é WORM**.

## 3. Google Cloud Storage

O arquivo `src/nivon/ptax_google_cloud.py` prepara **dois objetos**
para cada evento, com chaves determinísticas:

- `gs://<bucket>/<prefixo>/raw/<raw_sha256>.json`
- `gs://<bucket>/<prefixo>/manifestos/<evento_sha256>.json`

Antes do envio, reconfere SHA do raw e a consistência do
manifesto. Para o envio, depende de `google-cloud-storage`
instalado no ambiente autorizado, credencial de serviço
com IAM mínimo, bucket **privado** existente, revisão de direitos
e orçamento aprovada. `enviar_objetos_gcs_ptax` exige
`permitir_upload=True`, `referencia_direitos` e
`referencia_custo`. Usa `if_generation_match=0` para não
sobrescrever o objeto existente.

O processo não cria bucket, não configura cobrança, não implanta
Cloud Run, não agenda job e não habilita automaticamente escrita.
Em caso de falha depois do primeiro objeto, reconciliar o estado do
bucket; não fazer overwrite silencioso nem afirmar transação
distribuída atômica. GCS pode gerar custos operacionais; o teste
local não comprova enquadramento no nível gratuito.

Para execução futura no Google Cloud, a infraestrutura deverá
garantir: service account com escopo restrito ao bucket/prefixo,
logs auditáveis, retenção/snapshots exportáveis, verificação do
custo real, atribuição da ODbL, alertas de falhas, procedimento
de recuperação e separação entre pesquisa e dados homologados.

## 4. Evidências e pendências

**Código integrado e testado:** `ptax_quarentena_coleta.py`,
`ptax_google_cloud.py`,
`scripts/importar_ptax_quarentena.py`,
`scripts/importar_lote_ptax_quarentena.py`,
`tests/test_ptax_quarentena_cloud.py`,
`tests/test_importar_lote_ptax_quarentena.py`.

`scripts/ensaio_ptax_integrado.py` inclui 17 etapas offline,
incluindo quarentena e bloqueio de envio cloud, com execução em
`.github/workflows/testes.yml`.

**Faltam comprovar externamente:**
1. Captura real HTTP 200 do endpoint BCB na janela escolhida,
   inclusive esquema e resposta de dia sem cotação.
2. Independência/precisão de relógio e atribuição de data
   de publicação do Banco Central para estudos point-in-time.
3. Evidência de licença e autorização administrativa conforme a
   modalidade de uso pretendida.
4. Bucket/cloud IAM e custo verificados, upload real,
   download/restauração independente.
5. Promoção para histórico operacional somente por outro processo
   governado, sem pular auditorias; integração às séries e ao
   briefing somente após esses gates.

**Não declarar** que um arquivo armazenado na quarentena é valor
atual da PTAX ou que foi certificado pelo Banco Central.
