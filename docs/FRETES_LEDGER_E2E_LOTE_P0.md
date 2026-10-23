# NIVON — Lote P0 de fretes: persistência, execução E2E e backtest declarado

**Implementado em branch draft:** 22/10/2026. Subordinado a PR #91 → PR #82 → integração logística #42. Não há merge em `main`, ativação de GCP, cobrança, agendamento, WhatsApp live nem publicação.

## Entrega — cinco etapas conectadas

| Etapa | Interface | Comportamento |
|---|---|---|
| 1. Fonte e identidade | `fretes_adapter_whatsapp.adaptar_evento_whatsapp`, `fretes_registros.OfertaFrete` | Consome apenas anúncios com resolução/autorização atestadas na camada de origem; apenas ofertados, nunca contratados |
| 2. Snapshot as-of | `fretes_previsoes_arquivadas.preparar_compromisso_base_frete` | Resume os mesmos pares ponto/transportadora, preços-base, fonte e instantes de coleta já disponíveis na emissão |
| 3. Persistência | `fretes_ledger_persistente.inicializar_ledger_frete` e `anexar_lote_previsoes_frete` | SQLite em arquivo persistente, lote atômico de até 500 previsões **pré-assinadas**; encadeamento SHA-256, HMAC de emissor e bloqueio lógico de UPDATE/DELETE |
| 4. Maturação e auditoria | `fretes_cobertura_horizontes.auditar_cobertura_horizontes_frete` | Reconta cobertura exata de 7/30/90 **dias corridos**, ausência de alvo e identidade pareada |
| 5. Avaliação | `fretes_ledger_persistente.avaliar_ledger_frete` | Confronta forecasts pré-existentes com variação posterior das mesmas ofertas; MAE, RMSE, baseline **delta zero**, flags não homologados |

A integridade do ledger depende de uma cabeça SHA-256 **guardada fora do banco**. A função de verificação recebe explicitamente a cabeça esperada, não a "descobre" na tabela que está auditando. Cada previsão contém ID, modelo/versão, emissor, origem/destino/descarga/produto/equipamento/regime/pedágio, fonte, origem, alvo, horas com fuso, base snapshot e delta previsto. Uma previsão duplicada, antiga, forjada, fora da data comercial ou assinada com chave diversa bloqueia o lote inteiro.

Os timestamps de recebimento são entradas do runtime; uma pessoa com acesso ao SQLite **e à chave** ainda poderia simular registros passados. SQLite não é WORM, triggers não resistem a um administrador privilegiado e HMAC não oferece carimbo de tempo confiável por si só. Faltam implementação de ancoragem externa independente (com receipt), retenção/WORM controlado, gestão de chaves em secret manager e validação de relógio/anti-backfill fora da máquina.

## Comando único de auditoria offline com arquivos autorizados

O script `scripts/auditar_fretes_ledger_local.py` lê SQLite **somente em modo leitura** e um `.jsonl` local estrito exportado de fonte autorizada. Nunca modifica os arquivos nem aciona serviços externos. O JSONL deve ter exatamente os campos da estrutura `OfertaFrete`; preço em **texto decimal**; datas ISO; timestamps com fuso; 7 dígitos IBGE. Não admite macros, scripts, chaves no JSON, URI remota ou upload automático.

Crie um arquivo de configuração privado **sem credenciais** com:

```json
{
  "arquivo_sqlite": "/caminho/privado/previsoes.sqlite3",
  "arquivo_ofertas": "/caminho/privado/ofertas_autorizadas.jsonl",
  "cabeca_externa_sha256": "INSERIR_SHA256_DE_64_CARACTERES",
  "as_of": "2026-10-22T17:00:00-04:00",
  "emissor_esperado": "EMISSOR_CONFIAVEL",
  "modelo_versao": "VERSAO_EXISTENTE",
  "fonte_id": "FONTE_AUTORIZADA",
  "horizontes_dias": [7, 30, 90],
  "condicoes": {
    "origem_ibge": "5107925",
    "destino_ibge": "5107602",
    "descarga_entity_id": "DESTINO_RESOLVIDO",
    "produto": "MILHO",
    "equipamento": "RODOTREM",
    "regime": "PJ",
    "pedagio": "ADICIONAL"
  }
}
```

Esses códigos e identificadores são apenas **exemplo sintético de formato**, não constituem uma rota comercial disponível nem registro real. Não adicionar chaves ou informações de grupos ao repositório.

Em ambiente isolado e com autorização:

```bash
export NIVON_FRETE_HMAC_KEY_HEX="<HEX_DA_CHAVE_DE_VERIFICACAO_FORNECIDA_PELO_SERVICO>"
PYTHONPATH=src python scripts/auditar_fretes_ledger_local.py --config ./auditoria-local.json
```

A variável de ambiente deve vir de mecanismo seguro; não se recomenda introduzir literalmente segredos em histórico do shell. O script exige a chave, lê o ledger com a cabeça externa recebida e produz um único JSON de cobertura e desempenho por horizonte; sem forecasts elegíveis, retorna bloqueio, **não cria previsões a posteriori**.

## O que os testes E2E realmente demonstram

A suíte `tests/test_fretes_ledger_persistente.py` executa SQLite em memória/arquivo, fecha e reabre, assina apenas fixtures sintéticas, grava lote misto, rejeita rollback, corrige duplicatas e verifica SHA/HMAC, UPDATE/DELETE, anti-backfill, entrega de alvo, MAE/RMSE e três horizontes. A suíte `tests/test_fretes_pipeline_cli_e2e.py` exporta ofertas sintéticas no contrato JSONL, cria o SQLite, executa o **script real via subprocess**, compara respostas, verifica banco imutado, bloqueia segredo ausente, arquivo inválido e cabeça adulterada.

Não demonstram existência de histórico real, direitos de uso, credibilidade do provedor, confirmação de entrega, confiabilidade de relógio, ausência de sobrevivência ou qualidade de previsão em dados reais. Valor MAE=0 em fixture desenhada para ser linear não é `edge`.

## Próximos gates por ordem de risco

1. Confirmar origem de arquivos históricos realmente autorizados e identificadores canônicos do WhatsApp AI, com proveitos e direitos separados por canal/tenant.
2. Registrar eventos e forecasts *no momento em que forem gerados*, sob custódia independente, ancorando cada cabeça fora do SQLite e verificando integridade RAW do WhatsApp.
3. Validar calendário/coleta e cobertura real por corredor e safra; cumprir bloqueio contra preços sem condições econômicas equivalentes, sem média municipal.
4. Ativar validação temporal OOS/holdout purgado e comparação com baseline/climatologia e modelos razoáveis, antes de qualquer previsão pública.
5. Só após homologação, planejar banco escalável/exportação ao Google Cloud, deployment e integração de indicadores ao IVO/briefing, sempre com autorização para custos e direitos.

**Nunca habilitar flags operacionais por resultado de CI sintético.**


## Etapa adicional — store permanente das próprias ofertas

Além do ledger de previsões, existe `fretes_ofertas_store.py`: tabela SQLite local `nivon_frete_ofertas_v1` com registros `OfertaFrete` individuais, identidades econômicas, horas de publicação/coleta e metadados **declarados** sobre `raw_sha256`, `direitos_sha256`, `resolucao_sha256`, pseudônimo de tenant e provedor. A importação ocorre em lotes de até 500 registros, com SQL transacional e cadeia SHA-256 separada do ledger de forecasts. Não produz média municipal nem reúne transportadoras/preços distintos. Reposts devem ser deduplicados no adaptador/camada comercial anterior; `registro_id` repetido é recusado.

**Handoff do WhatsApp AI:** somente `OfertaFrete` que já passou por `adaptar_evento_whatsapp` e atestações independentes pode ser enviada ao store no runtime efetivo; os hashes de evidência fornecidos **não comprovam por si só** RAW, licença, resolução ou consentimento. A operação está desligada e nenhum evento externo foi capturado nesta implementação.

O comando `scripts/auditar_fretes_ledger_local.py` agora suporta duas origens **mutuamente exclusivas** para suas observações:

- **Arquivo JSONL**: campo `arquivo_ofertas` no JSON, no exemplo acima.
- **SQLite de ofertas**: substituir `arquivo_ofertas` pelos dois campos `arquivo_ofertas_sqlite` e `cabeca_ofertas_sha256`. O arquivo pode ser o mesmo SQLite local usado para previsões; ambas as cadeias são conferidas separadamente. Nesse modo o script não exige JSONL exportado e não faz escrita.

O comando em ambos os casos produz JSON restrito, com identidade da origem (`JSONL_EXPORTADO` ou `SQLITE_STORE`), estado da cabeça de ofertas, cobertura histórica e avaliação de forecasts. O banco SQLite de origem também é aberto em **read-only**; não há acesso por rede nem atualização automática. Testes E2E verificam o store e executam o CLI contra as duas fontes, em arquivos temporários.

**Persistência operacional no Google Cloud ainda NÃO configurada:** este store é exclusivamente local, sem migração ou conexão com banco remoto.
