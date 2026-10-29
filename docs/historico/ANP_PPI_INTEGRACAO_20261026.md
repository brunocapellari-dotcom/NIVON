# Integração oficial do PPI da ANP — NIVON

## Estado e escopo

**Código integrado em branch/PR, ainda NÃO ativado em nuvem, NÃO homologado.**
A inclusão do coletor não afirma coleta executada na infraestrutura do NIVON.

Fonte primária: [ANP — PPI](https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-de-paridade-de-importacao)
Arquivo XLSX oficial: [ppi.xlsx](https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/arq-ppi/ppi.xlsx)

Referência de engenharia: [jmagomez/anp-ppi-dashboard](https://github.com/jmagomez/anp-ppi-dashboard). O coletor NIVON adapta padrões de extração e análise de planilha deste repositório (código MIT; aviso em `docs/licencas/anp-ppi-dashboard-MIT.txt`). Não instala o dashboard do autor nem depende de GitHub Pages para funcionar.

## Produtos e unidades

- Diesel A S10: PPI em R$/litro por terminal.
- Gasolina A: PPI em R$/litro por terminal.
- QAV: PPI em R$/litro por terminal.
- GLP: PPI em R$/13kg por terminal.

Dados são **INFORMADOS pela ANP**, por semana e terminal. A planilha publica PPI **sem tributos**; não é preço de bomba, preço pago por transportadora, realização das refinarias ou margem. Nunca agregar terminais como média nacional sem metodologia fundamentada. Nunca utilizar no motor de fretes como custo efetivo pago sem modelagem separada.

## Entrada no pipeline existente

`src/nivon/anp_ppi.py` baixa exclusivamente URL oficial, valida assinatura XLSX, quatro abas, cabeçalhos, semana, unidade e preços positivos, preserva sha256 bruto e normaliza para `BR_ANP_PPI_SEMANAL`.

`gravar_lote` registra RAW imutável, snapshots, revisões e registros no SQLite do NIVON. O operador `scripts/operar_fontes_reais.py` foi ligado por opção `--anp-ppi`; compartilha o mesmo exportador JSONL e a carga BigQuery existente. Nenhuma infraestrutura extra, credencial nova ou serviço autônomo é criado por este PR.

## Execução controlada

Testes offline (sem chamadas externas):

```bash
pip install -e '.[excel]' pytest
pytest -q tests/test_anp_ppi.py
```

Coleta somente PPI com RAW e registros locais:

```bash
python -m nivon.anp_ppi --executar
```

Coleta integrada no operador existente (também coleta fontes-padrão do operador):

```bash
python scripts/operar_fontes_reais.py --anp-ppi
```

Para BigQuery, somente após homologação e autorização explícita: usar `--bigquery --projeto <GCP_PROJECT> --dataset <BQ_DATASET>` no operador. A operação aproveita o contrato atual de `carga_bigquery_fontes.py`, com credenciais externas. Não habilitar publicação automática no M1.

## Critérios para habilitação operacional

1. Confirmar HTTP 200 e download XLSX no ambiente de execução Cloud (redirecionamento bloqueado).
2. Conferir número de semanas/terminais, frescor e preços com documento oficial da ANP.
3. Executar duas coletas e uma revisão simulada: observações idempotentes e RAW imutável.
4. Validar staging JSONL, custo/dry-run e ingestão BigQuery já autorizado.
5. Exibir no terminal apenas séries com referência, fonte, unidade, natureza e carimbo de coleta.
6. Não misturar PPI com série de revenda ANP nem preços de produtores/importadores. Defasagem tributária e modelagem de custo de frete exigem conectores e validação próprios.

## Qualidade e limitações

- Alertas locais de frescor quando o último fechamento tem mais de 14 dias; não é suspensão automática de publicação da ANP.
- Datas de publicação não presentes na planilha ficam ausentes; não inferir a partir da coleta.
- Sem pretensão de validar automaticamente a defasagem: a aplicação externa tem diferenças de base tributária e de calendário que exigem mais fontes e auditoria.
- O painel externo não é embutido: HTML, e-mail e infraestrutura paralela são desnecessários para o NIVON.
