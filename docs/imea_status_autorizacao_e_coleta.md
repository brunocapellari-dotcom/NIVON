# IMEA — autorização informada e primeira coleta pública
Atualização: 22/10/2026.

## Autorização
O responsável pelo NIVON declarou em conversa: **“imea autorizado”**. Trata-se de declaração do responsável, **não de uma confirmação independente do IMEA**; o texto da autorização, se concedida pelo IMEA, e seu escopo exato ainda não foram apresentados.

Termo oficial: https://imea.com.br/imea-site/termo-de-uso.html.
As séries públicas da API IMEA são descritas em https://agrobr.dev/docs/sources/imea/ como `zona_cinza`, e o acesso público não implica automaticamente permissão genérica para redistribuição ou uso de arquivos não públicos. Não fazer bypass de controle, não compartilhar credenciais, não disponibilizar base bruta de terceiros publicamente.

## Validação real
Execução https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39891236618 :
- Soja: **4.568 registros de origem**, **107 candidatos a preço/frete**, última data de publicação 2026-10-22;
- Milho: **5.986 registros de origem**, **110 candidatos a preço/frete**, última data de publicação 2026-10-21;
- `meta.source=imea`, URLs oficiais `api1.imea.com.br/api/v2/mobile/cadeias/4/cotacoes` e `.../3/cotacoes` comprovadas;
- quatro testes isolados passaram (`tests/test_imea_publico.py`);
- Dados **não persistidos na tabela de preços**. Resultado de teste somente em memória;
- `reference_date` por linha: não fornecida; `published_at` é publicação, não cotação de referência.

## Implementado
- `nivon/imea_publico.py`: normalização por cadeia, ID textual (inclusive 18 dígitos), unidade, localidade, safra, hash para revisões; zero e semente fora dos preços físicos aprovados;
- `.github/workflows/imea-validacao.yml`: consulta pontual real sem persistência;
- `database/neon_imea_prices_staging.sql`: tabela separada no Neon para registros de publicação, com `reference_date` nullable;
- `nivon_imea_access_attestations`: registro da declaração do responsável; `provider_document_verified=FALSE`.
- Meta de fonte no PostgreSQL permanece bloqueada para automação de persistência enquanto a autorização documental e o serviço de gravação não estiverem homologados.

## Próximas ações
1. Precisar/registrar condições da autorização: conjunto de indicadores, armazenamento privado, atualização automática, limite de chamadas, possibilidade de reuso analítico.
2. Habilitar transmissão autenticada OIDC de batches validados para `nivon_imea_prices_staging` (a tentativa de publicação do endpoint de gravação foi bloqueada pelas configurações de segurança da ferramenta).
3. Testar 2 execuções em dias distintos, `ON CONFLICT`, revisão temporal e anomalias de zeros/duplicatas.
4. Estender para algodão, boi e frete, respeitando unidade, praça, tempo de referência, safra e classificações.
5. Não promover candidatos para preço diário operacional nem motor de tendência antes de resolver `data_referencia` ou dispor de metodologia explícita para indicadores de publicação.
