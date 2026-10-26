# Argentina — estimativas agrícolas MAGyP

Coletor: `src/nivon/argentina_magyp.py`. Fonte: Dirección de Estimaciones Agrícolas, https://datos.magyp.gob.ar/dataset/estimaciones-agricolas . Licença declarada no catálogo: CC BY 4.0; manter atribuição e indicação de transformações. O coletor bloqueia alteração dessa licença.

Execução no checkout (saída privada fora do repositório):

```bash
PYTHONPATH=src python3 -m nivon.argentina_magyp --destino "$HOME/nivon_dados/argentina_magyp"
```

Descobre o URL vigente via API CKAN e identificador fixo do recurso, baixa CSV completo (todos os cultivos), valida cabeçalho e número de colunas e registra SHA256, campanhas, culturas, quantidade de registros, data de coleta, modificação declarada e licença. Um snapshot por hash; repetição preserva o snapshot anterior. Não extrai ano civil da campanha nem converte ausências em zero. HTTPS restrito ao host oficial, sem redirects; timeout e tamanho limitado.

Natureza: estimativa oficial, não observação física. Área em ha, produção em t, rendimento em kg/ha. Validação atual é estrutural; não homologa números, duplicidades ou comparabilidade temporal. A data do nome do CSV não garante atualidade de todas as campanhas. Sem agendamento ou carga BigQuery nesta implementação. PAS, condição semanal da Bolsa de Cereales e preços não estão cobertos.

Testes: `PYTHONPATH=src python3 -m unittest discover -s tests -p test_argentina_magyp.py`.

## Integração ao núcleo atual

`scripts/coletar_argentina_magyp.py --base /diretorio/privado` mostra plano sem rede. Acrescentar `--executar` coleta e persiste dois snapshots: `ARGENTINA_MAGYP_CATALOGO` (inclui licença e URL) e `ARGENTINA_MAGYP_ESTIMACIONES`. Usa `ingestao_fontes_reais.gravar_lote` e `arquivo_raw_gcs.arquivar_gcs` da main; não implementa outro motor Cloud. Ambos ficam `QUARANTINED`, sem observações analíticas: campanha não pode ser forçada ao contrato mensal de referência.

`--executar --gcs --bucket BUCKET_EXISTENTE` usa ADC já configurado. Exige `NIVON_RAW_ARCHIVE_APPROVED=true` e `NIVON_ZERO_COST_BQ_APPROVED=true`, conforme gates do núcleo. Não cria bucket, tabela, credenciais ou agendamento. Não há dependência de BigQuery para a coleta. Upload parcial entre catálogo e CSV pode ser retomado pela mesma chamada; não há transação distribuída GCS/SQLite. Upload testado com cliente simulado, ainda sem prova GCS real nesta frente.

A reexecução de bytes idênticos preserva a primeira coleta do snapshot. Não representa um log completo de todas as tentativas HTTP. Alterações de metadados no catálogo são retidas quando o CSV muda; o catálogo original de uma edição idêntica é preservado. Validação estrutural não substitui homologação numérica. Integração com módulos SAGyP em PRs #122/#217 deve convergir seletivamente, sem promover automaticamente estimativas anuais ao contrato de observações diárias.

## Evidência executada nesta continuidade

Base de código: main `06c213e75ef2c09f3b8fef16a36d6ba23fe0797d`. Coleta oficial HTTP, ledger SQLite real e segunda execução sem alteração de código: 160.499 registros, safras 1969/1970–2024/2025; SHA256 `7a47a6d356258a69ce0010031f9b2f45ea4c873901d8f812c7c394d9946f9395`. Primeira coleta desta rodada: `2026-10-26T01:24:25.248305+00:00` (UTC; noite de 25/10 em MT). Duas execuções conservaram dois snapshots e zero observações analíticas. Essa data é coleta, não publicação. Oito testes focados passaram (inclui dois do arquivador existente); GCS exclusivamente simulado, sem carga BigQuery. RAW real permanece fora do repositório público.

## Caminho curto para operação no Cloud

Workflow manual `Argentina MAGyP - coleta e prova GCS` (`argentina-magyp-gcs.yml`): executa na main usando WIF e destino existentes, coleta duas vezes, arquiva por SHA e baixa os dois objetos para comparar bytes/SHA. Só imprime recibo agregado; não publica RAW como artifact. Exige os gates já utilizados no projeto (arquivo e custo), sem nova infraestrutura nem agendamento. Usa environment `nivon-gcp-producao`. Sem BigQuery neste passo. Se a fonte mudar entre as duas capturas, o teste exige repetição em vez de declarar falsa idempotência. A CLI faz readback obrigatório após upload. Teste adicional detecta corrupção com mesmo tamanho. Execução remota ainda depende do despacho do workflow; não foi demonstrada por CI sintética.
