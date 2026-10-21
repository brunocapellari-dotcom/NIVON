# NIVON — integração conservadora de referências BrasilAPI, Siscomex, IBGE e PTAX (21/10/2026)

## Estado verificável nesta branch

- **Código incorporado**: normalizadores offline de consulta **NCM individual** e **taxas sem referência temporal** em `src/nivon/brasilapi_referencias.py`, com testes sintéticos e amostra de esquema fornecida pelo usuário.
- **Catálogo mestre e rotas**: NCM oficial Siscomex, NCM BrasilAPI complementar e Taxas BrasilAPI sem data cadastrados com `enabled=false`, `collection_authorized=false`, `runtime_enabled=false` e `scheduled_enabled=false`. Não existe agendamento de requisições.
- **IBGE oficial**: já há `src/nivon/ibge_municipios.py` (normalização municipal com código **sete dígitos** e UF) na branch de integração; não duplicar pelo endpoint BrasilAPI/IBGE, que também pode listar localidades de nove dígitos que não são municípios.
- **PTAX BCB**: já há normalização `src/nivon/bcb_ptax.py`, planejador `src/nivon/ptax_plano.py` e ingestão local controlada. O trabalho separado da [PR #58](https://github.com/brunocapellari-dotcom/NIVON/pull/58) tem coletor real, SQLite e testes do backfill; **não foi mesclado nesta branch**. Reaproveitar/reconciliar, não manter coletor PTAX duplicado.
- **CPTEC**: previsão e ondas continuam em **avaliação**, sem habilitação, por risco de frescor, inconsistência e regras de uso. O NIVON não publicará previsão sem data de atualização, horizonte, localidade e qualidade auditada.

## Hierarquia correta de fontes

| Domínio | Autoridade dos dados | Complemento | Risco controlado |
| --- | --- | --- | --- |
| NCM | Siscomex/Classif (vigência e atos) | BrasilAPI NCM individual | código antigo, alteração de vigência, sem volumes |
| Câmbio | Banco Central / PTAX OData | BrasilAPI Câmbio | fechamento PTAX não é dólar spot nem fechamento de mercado |
| Taxas | BCB/SGS e órgãos primários para índices | BrasilAPI Taxas | resposta sem referência por indicador; bloqueio de briefing |
| Geografia | IBGE Localidades (município código 7 dígitos) | BrasilAPI IBGE | não confundir município e distrito/vila de 9 dígitos |
| Meteorologia | INMET/CPTEC e demais bases homologadas | BrasilAPI CPTEC | previsão diferente de observação, atraso e dados não atuais |

## Contrato dos dois novos normalizadores

`normalizar_ncm_individual(payload, codigo_consultado, coletado_em)`:

1. Só aceita **objeto de um NCM** correspondente ao código requisitado; a listagem integral da BrasilAPI **não é consumida**, respeitando a restrição anti-varredura.
2. Código canônico com oito dígitos, início/fim da vigência, ato normativo, `sha256_original`, data da coleta com fuso e URL origem.
3. `9999-12-31` significa ausência de encerramento definido, **não garante vigência na data atual**. Necessária conciliação com Siscomex.
4. `publicacao` e `referencia` ficam nulos se não estão na resposta. `apto_publicacao_automatica=false`.

`normalizar_taxas_sem_data(payload, coletado_em)`:

1. Valida o esquema básico e retém valores **como retornados**, sem declarar unidade, competência ou data do índice.
2. `apto_briefing=false`, `apto_tendencias=false`, `apto_serie_historica=false`.
3. Em eventual uso de Selic, CDI e IPCA, consultar série oficial datada, frequência, unidade e modalidade antes da publicação.

## Testes e procedimento de validação

```sh
PYTHONPATH=src python -m unittest tests.test_brasilapi_referencias tests.test_brasilapi_catalogo -v
PYTHONPATH=src python -m nivon.catalogo_fontes --resumo
PYTHONPATH=src python -m nivon.rotas_coleta --resumo
PYTHONPATH=src python -m unittest discover -s tests -v
```

O CI do PR executa a suíte offline. Para homologação real futura, primeiro testar **uma consulta pontual** a cada endpoint, com timeout/MIME/sha e a data efetiva da observação, comparando Siscomex e BCB. Não executar ciclos de varredura da BrasilAPI; cargas oficiais completas devem usar canais oficiais permitidos e seus limites. Não publicar valores de exemplo.

**Status operacional**: integração de código e contratos versionada, **não coletor ativo, não deploy e não fluxo em produção**. O endpoint BrasilAPI/Taxas forneceu JSON em consulta externa em 21/10/2026; a existência de NCM individual foi documentada e exemplificada, mas não tivemos resposta HTTP verificável ao NCM oficial/auxiliar neste ambiente. Não alegar operação contínua até testes end-to-end em executor com rede e armazenamento persistente.
