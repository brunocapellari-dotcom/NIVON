# NIVON | Recuperação pós-commit de recibos de frete (P0)

**Implementado:** 23/10/2026. **Estado:** código de execução local e testes sintéticos; PR draft, sem implantação, publicação, coleta real ou despesas.

## Problema operacional resolvido

No fluxo R01, um processo pode gravar três previsões shadow D+7/30/90 em uma transação SQLite e falhar antes da emissão do recibo separado. Reexecutar a previsão após a falha seria perigoso: pode duplicar emissões, mudar o snapshot ou criar falsos registros históricos.

O novo `fretes_recuperacao_poscommit.recuperar_recibo_poscommit_frete` **recupera somente a evidência faltante**, sem emitir novamente forecast e sem modificar o SQLite. O `scripts/recuperar_recibo_fretes_local.py` implementa a mesma recuperação a partir de configuração privada, usando `mode=ro` e `PRAGMA query_only=ON`.

## Pré-condições obrigatórias

- **Checkpoint externo anterior:** cabeça SHA-256 e número de previsões da última posição previamente reconhecida; não obter ambos do mesmo SQLite que está sendo auditado.
- **Cabeça de ofertas igualmente verificada:** SHA-256 da cadeia de ofertas, conservado separadamente.
- **Identidade econômica exata:** origem e destino IBGE, descarga, produto, equipamento, PF/PJ, pedágio e fonte. Cada transportadora e cada ponto de embarque seguem separados; é proibido calcular média de frete por município.
- Chaves HMAC distintas de previsão e recibo, fornecidas pelo runtime; emissor de previsão e de recibo declarados. HMAC não substitui assinatura externa/WORM.
- Exatamente um lote com os horizontes declarados. A quantidade atual deve ser a quantidade anterior somada aos horizontes previstos.
- Verificação SHA/HMAC integral do ledger e do prefixo confiável; reconstrução do baseline a partir do snapshot `as-of` da emissão original. Divergência em hora, valor, fonte, identidade, horizonte ou assinatura bloqueia a recuperação.

O mecanismo não busca outra cotação para preencher lacunas nem utiliza frete contratado ou volume transportado como alvo.

## Comportamento de recuperação

1. Consulta SQLite apenas para leitura e valida cadeia e ponto de partida. Se houver previsão ausente/extra, recusa sem tentar completar automaticamente.
2. Compara **todos os campos** de cada forecast persistido às intenções que seriam geradas somente com a informação efetivamente disponível na data original.
3. Se já existe recibo local íntegro, reutiliza-o e não cria outro.
4. Na ausência de recibo, cria novo documento com hora **atual da recuperação**, persistido em arquivo exclusivo `0600` numa pasta `0700`. Não regrava previsões.
5. Se a recuperação for em dia comercial diferente, por padrão **bloqueia**. Com `permitir_recuperacao_tardia=true`, admite a nova evidência, porém com status `RECIBO_TARDIO_CRIA_APENAS_EVIDENCIA_DE_INTEGRIDADE_ATUAL`, sem alegar emissão antiga comprovada.
6. Qualquer recibo tardio continua `apto_para_avaliacao_oos_homologada=false`; em hipótese alguma o mecanismo permite afirmar que um forecast realmente existia antes do alvo sem uma âncora confiável daquela época.

## Comando único (somente arquivos privados)

Configuração `recuperacao.json` sem segredos e **modo 0600**:

```json
{
  "arquivo_sqlite": "/caminho/privado/fretes.sqlite",
  "cabeca_previsoes_anterior_sha256": "SHA256_EXTERNO_ANTERIOR",
  "quantidade_previsoes_anterior": 0,
  "cabeca_ofertas_sha256": "SHA256_EXTERNAMENTE_VERIFICADO_DAS_OFERTAS",
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
  "emissor_previsao": "EMISSOR_DE_PREVISOES",
  "emissor_recibo": "EMISSOR_DE_RECIBOS",
  "diretorio_recibos": "/caminho/privado/recibos",
  "horizontes_dias": [7, 30, 90],
  "permitir_recuperacao_tardia": false
}
```

Os campos SHA no exemplo são **placeholders**, não valores executáveis. A cabeça de zeros (`GENESIS`) só é permitida quando o checkpoint anterior realmente corresponde a zero previsões. Os códigos territoriais e nomes são apenas exemplos de esquema, não confirmações de operação comercial.

Passar duas chaves diferentes pelo mecanismo seguro do ambiente, sem inseri-las no arquivo ou no GitHub:

- `NIVON_FRETE_PREVISAO_KEY_HEX`
- `NIVON_FRETE_RECIBO_KEY_HEX`

```bash
PYTHONPATH=src python scripts/recuperar_recibo_fretes_local.py --config /caminho/privado/recuperacao.json
```

O comando imprime somente status, cabeça/quantidade e caminho do recibo. Sem chave, checkpoint confiável, coincidência de dados ou permissões locais, o processo retorna código 2 e estado `RECUPERACAO_BLOQUEADA`, sem vazar chaves, anúncios ou credenciais.

## Validação e limitações

As suítes `test_fretes_recuperacao_poscommit_e2e.py` e `test_fretes_recuperacao_cli_e2e.py` exercitam o ciclo SQLite→falha após COMMIT→recuperação por subprocesso→recibo e conferência; incluem reexecução idempotente, checkpoint truncado/errado, forecasts adulterados, assinatura inválida, recibo já existente, recusa de retrodatação, recuperação tardia explícita e entrada sem chave.

A execução utiliza dados artificiais e chaves HMAC de fixture. **Não comprova** custódia independente das chaves, existência passada de um forecast, integridade de RAW de grupos reais, licença, consentimento, WORM, carimbo temporal independente, qualidade estatística OOS ou integração real com GCP/WhatsApp AI.

### Próximos gates

1. Implementar testemunha independente e de mínima permissão (por exemplo, recibo assinado por identidade externa e objeto versionado/retido no bucket GCP autorizado), com custódia e relógio verificáveis.
2. Exigir controle de integridade do checkpoint fora do SQLite e alarme de falha pós-commit; sem checkpoint, não habilitar recuperação automática como evidência confiável.
3. Homologar a cadeia real WhatsApp AI → direitos/RAW/resolução → store de ofertas → assinatura externa → ledger → recibo independente.
4. Só após dados realmente coletados, iniciar forecasts prospectivos arquivados e validação OOS/holdout por corredor, com baseline de variação zero. Manter `operational_enabled=false` e `previsao_homologada=false` até autorização explícita e critérios técnicos.

Nenhuma captura live, publicação, merge, provisionamento GCP ou cobrança foi executada.
