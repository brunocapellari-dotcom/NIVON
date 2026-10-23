# NIVON — Ciclo Shadow integrado de fretes e evidência externa

**Data:** 23/10/2026. **Estado:** pronto para revisão e execução exclusivamente em ambiente isolado; nenhum acesso real ao WhatsApp, Google Cloud ou armazenamento WORM foi efetuado.

## 1. Entrega de ponta a ponta

`fretes_ciclo_shadow.executar_ciclo_shadow_frete_local` faz o seguinte em uma chamada:
- Confere a cabeça SHA-256 do `fretes_ofertas_store` e a do `fretes_ledger_persistente` **recebidas externamente**, nunca descobertas da própria tabela.
- Seleciona somente ofertas comerciais `OfertaFrete` com o mesmo código de origem e destino, mesmo terminal de descarga, produto, equipamento, regime PF/PJ, condição de pedágio e fonte. Cada transportadora e ponto de embarque permanecem distintos no painel; NÃO calcula média municipal.
- Bloqueia observação publicada/coletada após `recebido_em`, sem criar previsões com dados futuros.
- Prepara benchmark de persistência (`delta_previsto_brl_t = 0`) para D+7/30/90 dias **corridos**, usando o snapshot **as-of** disponível na emissão.
- Para **simulação local**, cria HMAC de cada previsão com chave de verificação fornecida exclusivamente pelo runtime e salva o lote de três previsões em SQLite em **uma transação**. A mesma rota/modelo/dia não pode ser reemitida. Este HMAC não representa serviço independente.
- Emite recibo HMAC versionado de nova cabeça, com sequencia, nonce e tempo local; escreve arquivo JSON exclusivo `O_EXCL` em pasta `0700`, efetua `fsync` e pode conferir MAC e cadeia SQLite. O arquivo é separado do SQLite, mas **não** equivale a um registro independente/WORM.
- Se o recibo falhar DEPOIS do commit SQLite, retorna `PREVISOES_GRAVADAS_SEM_RECIBO_LOCAL` mais a nova cabeça e indica recuperação. O banco **não** é revertido nem um novo ciclo é silenciosamente iniciado.

## 2. Executar ciclo em um único comando (somente simulação local)

`scripts/executar_ciclo_shadow_fretes_local.py` usa `datetime.now(timezone.utc)` internamente, evitando uma data histórica arbitrária por argumento. Só acessa um SQLite já existente e pasta privada de recibos, nunca cria serviços, não faz rede nem habilita agendamento.

`ciclo.json` (permissão `0600`, sem segredos):

```json
{
  "arquivo_sqlite": "/var/lib/nivon-privado/fretes.sqlite",
  "diretorio_recibos": "/var/lib/nivon-privado/recibos",
  "cabeca_ofertas_esperada": "SHA256_DE_64_HEXADECIMAIS",
  "cabeca_previsoes_esperada": "SHA256_DE_64_HEXADECIMAIS_OU_GENESIS",
  "condicoes": {
    "origem_ibge": "5107925",
    "destino_ibge": "5107602",
    "descarga_entity_id": "terminal:exemplo",
    "produto": "SOJA",
    "equipamento": "RODOTREM",
    "regime": "PJ",
    "pedagio": "ADICIONAL"
  },
  "fonte_id": "FONTE_HOMOLOGADA",
  "emissor_previsao": "EMISSOR_SIMULACAO",
  "emissor_recibo": "EMISSOR_RECIBO",
  "horizontes_dias": [7, 30, 90]
}
```

Os IDs acima apenas ilustram o contrato e não atestam uma rota real. O arquivo deve ser privado e não enviado ao GitHub. Chaves HMAC distintas são injetadas por mecanismo seguro do runtime: `NIVON_FRETE_PREVISAO_KEY_HEX` e `NIVON_FRETE_RECIBO_KEY_HEX`. Nunca incluir os valores em comandos persistidos no histórico de shell ou arquivos de commit.

```bash
PYTHONPATH=src python scripts/executar_ciclo_shadow_fretes_local.py --config /caminho/privado/ciclo.json
```

Saída em JSON possui cabeças antigas/novas, número de previsões e `recibo_local_caminho`. O processo retorna **0** se a gravação e o recibo local tiverem sucesso, **2** se um controle impedir a operação antes da escrita, **3** se a gravação ocorreu, mas o recibo não foi criado (nesse caso a nova cabeça permanece no stdout para recuperação). Recebimento e assinatura continuam SEM validação por relógio independente.

## 3. Adaptador preparado para Google Cloud Storage

`fretes_recibos_gcs.py` implementa `gravar_recibo_gcs_condicional` e `conferir_recibo_gcs_generation`, sem credenciais embutidas e sem importar bibliotecas Cloud no carregamento do módulo:

- Recebe `bucket` de um cliente `google-cloud-storage` previamente autenticado/configurado pelo serviço (não cria bucket/projeto).
- **Desligado por padrão:** só tenta escrita com `autorizar_escrita=True`, uma autorização de runtime distinta da aprovação para provisionar recursos pagos.
- Valida MAC e esquema antes do upload; grava objeto em namespace `nivon/fretes/recibos/v1/...` com `if_generation_match=0`: pré-condição que só permite criação quando não existe versão viva do objeto (documentação oficial: https://docs.cloud.google.com/python/docs/reference/storage/latest/generation_metageneration).
- Confere a `generation` devolvida, baixa essa geração com pré-condição correspondente e compara bytes na íntegra. Objeto divergente, upload duplicado ou pré-condição falha resulta em erro; nenhuma sobrescrita silenciosa.
- O ciclo shadow permite `bucket_recibo_gcs` e `autorizar_escrita_gcs=True` por injeção **apenas** em runtime explicitamente aprovado; o script CLI padrão não passa bucket e NÃO faz chamadas Cloud.
- Se upload ou read-back remoto falhar após commit local, retorna `SHADOW_LEDGER_GRAVADO_GCS_NAO_CONFIRMADO` e marca `recuperacao_gcs_necessaria=true`, com cabeça local retida.

**Atenção:** `if_generation_match=0` NÃO garante WORM/retention/imutabilidade: objeto apagado pode voltar a ser criado e privilégios de administrador permanecem. São necessários controle IAM, política de retenção separada, isolamento de contas, orçamento e verificação de carimbo externo. Cloud Storage pode cobrar armazenamento e operações; a política de soft delete padrão pode gerar custos adicionais (https://docs.cloud.google.com/storage/docs/soft-delete).

Nenhuma dessas garantias externas foi configurada ou demonstrada aqui. Testes com `BucketFalso` só verificam contrato SDK, pré-condição, geração, leitura e falhas simuladas; não constituem teste integrado real de Google Cloud.

## 4. Critérios para homologação real

1. Aprovação dos direitos de acesso e conservação dos RAW de WhatsApp AI, com escopo por tenant e provedor.
2. Separação real de serviços e chaves: **emissor de previsão**, **atestador de direitos**, **resolvedor**, **assinador de recibos**, serviço de relógio com proteção contra retrodatação e armazenamento externo não controlado pela mesma credencial.
3. Provisionamento explícito de bucket/serviço Google Cloud no projeto autorizado, política mínima de retenção/backup, orçamento e cotas. **Não** habilitar cobrança/recursos implicitamente.
4. Teste ponta a ponta com provedor real, dados auditáveis e anchors verificados por **segunda identidade**, não só por código e mocks.
5. Avaliação OOS de previsões realmente emitidas antes do resultado, comparando desempenho contra o baseline zero por corredor, ponto, transportadora, safra e horizonte; monitorar viés de sobrevivência e ausência de anúncios.

A publicação e o scheduling seguem OFF no manifesto. Nenhuma média de preço por município é calculada. Valores continuam sendo `FRETES_ANUNCIADOS`, nunca cotações negociadas ou fretes realizados.
