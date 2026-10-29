# NIVON — Preparação da primeira carga ANTT no Google Cloud

Escopo: obter o CSV ferroviário da ANTT/SIADE 2026, validar SHA/manifesto, contagens e toneladas, e inspecionar bucket/tabela **somente por metadados**, sem gravar no Google Cloud.

## Ambiente verificado

- Projeto: nivon-data.
- Dataset: nivon_raw, em southamerica-east1.
- Bucket: nivon-data-raw-2026, em southamerica-east1.
- Conta de serviço: nivon-coletor-de-dados@nivon-data.iam.gserviceaccount.com.
- WIF: nivon-github / github-actions; restrito à branch main do repositório.
- Teste real de OIDC e leitura de metadados: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39980530880 — **sucesso**.

## Prova read-only

O workflow nivon-antt-piloto-readonly.yml executa os testes e baixa o CSV ANTT/SIADE real **somente de 2026**. O coletor monta staging e valida SHA, registro e competência; o novo módulo nivon.antt_gcp_preparar_piloto consulta somente metadados do BigQuery/Storage. O relatório lista o SHA, tamanho de arquivo, registros, toneladas úteis, existência da tabela ANTT e existência do objeto de arquivo no bucket. **Não executa SQL, jobs BigQuery, upload, criação de tabela, bucket ou views.**

Restrições: um ano por prova, até 16 MB CSV, até 30 mil registros, ambos os recursos na mesma região. Falha se staging, metadata ou schema forem incompatíveis. Arquivos brutos são descartados do runner após execução. Apenas o resumo é salvo como artefato por 30 dias. Executar GitHub Actions consome minutos e chamadas de API de leitura podem ser faturáveis.

## Ativação da escrita — separada e ainda bloqueada

O workflow de carga existente ant t-ferrovia-gcp.yml (remover espaço no nome ao abrir arquivo) exige duas variáveis de aprovação:
- NIVON_ZERO_COST_BQ_APPROVED=true
- NIVON_RAW_ARCHIVE_APPROVED=true

A primeira criação de tabela exige ainda NIVON_BQ_BOOTSTRAP_TABLE_APPROVED=true. Nenhuma destas flags é habilitada pela prova de leitura.

O nome legado ZERO_COST **não é garantia de ausência de cobranças**. Antes de ativar escritas, configurar orçamento e alertas no Google Cloud; alertas não bloqueiam gastos automaticamente. O plano de piloto deverá confirmar se a tabela já existe, evitando bootstrap desnecessário.

## Próximos gates

1. Executar prova real contra 2026 e obter bytes, linhas, hashes e status dos recursos.
2. Limitar a **primeira carga real** a 2026; verificar permissões reais de escrita e conciliação pós-carga.
3. Auditar idempotência, custos, cobertura SIADE, granularidade e versões antes do backfill 2006–2025 e antes da rotina recorrente.
4. Não confundir toneladas úteis ferroviárias com descarga rodoviária ou transbordo físico comprovado.

Os dados ferroviários foram coletados em GitHub Actions, mas a primeira gravação no BigQuery só estará comprovada após execução live de persistência, com logs e validação dos dados.
