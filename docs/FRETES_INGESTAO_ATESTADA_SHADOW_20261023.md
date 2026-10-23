# NIVON — Lote P0: WhatsApp AI atestado → SQLite → baseline shadow

**Branch:** `feat/frete-ingestao-atestada-lote-20261023` | **Status:** implementado OFFLINE em PR draft; sem acesso real a WhatsApp, cloud ou fontes licenciadas.

## 1. Entrada atestada em lote

`nivon.fretes_ingestao_atestada:ingerir_lote_whatsapp_atestado` recebe até 500 envelopes:
- `evento` estruturado no contrato `FreightEvent`, `resolucao` independente e `autorizacao` independente;
- `data_coleta` com timezone; `raw_bytes` originais como bytes **apenas em memória**;
- `recebido_em` do relógio do processo, cabeça SHA-256 anterior recebida de armazenamento independente;
- chave de pseudonimização de tenant e duas chaves HMAC **distintas**, com emissores separados para `DIREITOS` e `RESOLUCAO`.

O fluxo exige que a `resolucao` já ASSINADA contenha tanto `evento_sha256` quanto `raw_sha256`, e compara este com `sha256(raw_bytes)`. A resolução atestada deve preservar a atualidade comercial do próprio anúncio, origem/destino, carga, transportadora e identificação econômica. A autorização atestada deve cobrir `LEITURA`, `ARMAZENAMENTO` e `ANALISE` para o tenant/fonte. A janela online exige `0 ≤ recebido_em - data_coleta ≤ 300 segundos`; replay histórico necessita fluxo de backfill separado e **não** é rotulado como observação de hoje.

Uma só inconsistência impede a gravação do lote. Repetições de **mesmo registro, valor e comprovantes** são idempotentes, sem transformar mensagens em eventos comerciais adicionais; eventos divergentes são bloqueados. As contagens separam publicações recebidas, registros individuais inseridos e repetições idempotentes. O store não faz média municipal nem infere tonelagem, cotação negociada ou contratação.

Somente hashes de RAW, dos documentos assinados de autorização/resolução, pseudônimo do tenant e os atributos comerciais `OfertaFrete` são preservados. **O RAW não é armazenado** no store SQLite. O operador deve manter os originais em repositório privado autorizado com suas próprias retenções e direitos. SHA/HMAC não comprovam por si mesmos que a fonte REAL concedeu licença ou que os signatários realmente são independentes.

## 2. CLI privado de entrada

O `scripts/ingerir_fretes_atestados_local.py` permite receber um arquivo local `.jsonl` de envelopes assinados pré-coletados e gravá-los em um banco `.sqlite` já inicializado, sem abrir rede.

Os arquivos `config.json`, `recebidos.jsonl` (que contém o RAW codificado em base64) e `fretes.sqlite` devem ser privados (modo `0600` no Linux), regulares e sem symlink. Cada linha JSONL tem **exatamente** `evento`, `resolucao`, `autorizacao`, `data_coleta` e `raw_base64`. O base64 é decodificado somente para verificar o SHA assinado; conteúdo de mensagens e credenciais não aparece no stdout nem stderr.

Exemplo de `config.json`, sem segredos nem dados pessoais:

```json
{
  "arquivo_ofertas_sqlite": "/var/lib/nivon-privado/fretes.sqlite",
  "arquivo_envelopes_jsonl": "/var/lib/nivon-privado/recebidos.jsonl",
  "cabeca_anterior_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "emissores_atestacao": {
    "DIREITOS": "emissor_direitos_homologado",
    "RESOLUCAO": "emissor_resolucao_homologado"
  }
}
```

O digest de 64 zeros é o GENESIS e **só vale para o primeiro lote com banco comprovadamente vazio**. Nos demais, exige-se a cabeça SHA-256 exata recebida do serviço externo de evidências. Configuração com cabeça stale falha fechada.

Credenciais via ambiente seguro, sem valores fixos no repositório:
`NIVON_FRETE_DIREITOS_KEY_HEX`,
`NIVON_FRETE_RESOLUCAO_KEY_HEX`,
`NIVON_FRETE_PSEUDO_KEY_HEX`.

```bash
PYTHONPATH=src python scripts/ingerir_fretes_atestados_local.py --config /caminho/seguro/config.json
```

O comando emite um único objeto JSON com quantidades e `nova_cabeca_sha256`. Não grava o recibo fora do SQLite nem configura custódia de chaves; **o operador deve ancorar o novo SHA independentemente** antes de continuar. Este é um caminho offline de arquivos, NÃO um coletor do WhatsApp ou deploy ativo.

## 3. Primeira emissão shadow: previsão baseline sem mudança

`nivon.fretes_baseline_shadow:preparar_intencoes_baseline_frete` constrói INTENÇÕES não assinadas de previsão D+7, D+30 e D+90 **dias corridos**, com `delta_previsto_brl_t="0"`. É a referência ingênua de persistência de frete-base **anunciado**, e não uma alegação de skill. Não transforma série descritiva em previsão comercial.

A função recusa QUALQUER observação coletada ou publicada depois de `emitido_em`, mudanças de fonte, condições de rota incompatíveis ou menos de dois pares ponto/transportadora presentes no dia da emissão. O hash de snapshot é construído a partir das ofertas efetivamente disponíveis na origem. O ID é determinístico por identidade de modelo/rota/horizonte. NÃO preenche `registrado_em`, NÃO assina e NÃO escreve no ledger.

Um emissor externo deve anexar seu horário de registro independente, verificar custódia e assinar o contrato completo com a chave apropriada **antes** da gravação no `fretes_ledger_persistente`. Sem isso não existe forecast arquivado confiável. O resultado da emissão shadow é `publicavel=false` e `probabilidades_calibradas=null`.

## 4. Testes e próximos gates

- `tests/test_fretes_ingestao_atestada_e2e.py`: evento + RAW + atestações sintéticas → SQL transacional → R01 com seis sessões, rollback e idempotência.
- `tests/test_fretes_ingestao_cli_e2e.py`: arquivo privado → processo CLI real → SQLite e SHA de confirmação, sem expor segredos ou guardar RAW.
- `tests/test_fretes_baseline_shadow_e2e.py`: emissão as-of → assinatura HMAC de TESTE por emissor fictício → ledger de previsões → comparação posterior D+7/30/90; valores MAE artificialmente previsíveis não comprovam modelagem real.

**Gates ainda bloqueados:** integração com provedor real e consentimento/licença verificáveis; coleta e conservação segura de bytes RAW por tenant; atestadores reais com revogação/custódia; recibo de tempo/WORM externo; recepção automática autorizada; forecast assinado pelo próprio serviço em tempo real; e holdout fora da amostra com dados reais e benchmark comparável. Nenhum agendamento, cloud, emissão para clientes ou despesa foi habilitado.


## 5. Comando único para preparar previsões shadow

`scripts/preparar_shadow_fretes_local.py` é **somente leitura**. Recebe SQLite de ofertas com a cabeça SHA-256 fornecida externamente, filtra explicitamente a identidade econômica, usa o relógio **atual** do processo (não aceita `as_of` histórico pela CLI) e cria **propostas não assinadas** D+7, D+30 e D+90.

Exemplo `shadow.json` local e privado (modo `0600`, sem chaves):

```json
{
  "arquivo_ofertas_sqlite": "/var/lib/nivon-privado/fretes.sqlite",
  "cabeca_ofertas_sha256": "CABECALHO_SHA256_FORNECIDO_INDEPENDENTEMENTE",
  "condicoes": {
    "origem_ibge": "5107925",
    "destino_ibge": "5107602",
    "descarga_entity_id": "terminal:exemplo",
    "produto": "SOJA",
    "equipamento": "RODOTREM",
    "regime": "PJ",
    "pedagio": "ADICIONAL"
  },
  "fonte_id": "FONTE_ATESTADA",
  "emissor_id": "EMISSOR_CREDENCIADO",
  "horizontes_dias": [7, 30, 90]
}
```

Os códigos e nomes acima são apenas exemplos de formato, não evidência de mercado real. A cabeça deve ter **64 caracteres hexadecimais** e corresponder exatamente ao store. Na ausência de ao menos dois pares da mesma rota/produto/equipamento/regime no dia da emissão, a função recusa o lote, sem utilizar preços de outros estabelecimentos.

```bash
PYTHONPATH=src python scripts/preparar_shadow_fretes_local.py --config /caminho/privado/shadow.json
```

O JSON contém `previsoes_para_assinatura_externa` sem `registrado_em` ou `assinatura_hmac_sha256`. Isso é **uma intenção de emissão**, não uma previsão existente no ledger. A integração com o assinador externo e a gravação imediata e verificável do resultado continuam pendentes. Testes de integração agora executam os **dois comandos subprocess** (`ingerir_fretes_atestados_local.py` → `preparar_shadow_fretes_local.py`) sobre o mesmo banco SQLite privado e verificam que a preparação não o altera.
