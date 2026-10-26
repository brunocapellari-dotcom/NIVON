# NIVON — ANTT MDF-e/RNTRC, volume rodoviário origem–destino

**Entrega 22/10/2026 — Código de importação pronto; extração contínua de matriz MDF-e ainda não homologada.**

Fonte: https://www.gov.br/antt/pt-br/assuntos/cargas/dadostrc/movimentacao-de-cargas

## Como usar

O operador precisa primeiro obter e verificar uma exportação agregada CSV da ANTT. Ela deve conter, no mesmo grão geográfico, competência, origem, destino e toneladas.

```bash
PYTHONPATH=src python scripts/ingest_antt_mdfe.py \
  --csv /caminho/antt-exportacao.csv \
  --db /dados/nivon.sqlite --nivel RGI \
  --recorte mt_sorriso_pa_itaituba_soja_2026 \
  --competencia-resumo 2026-09
```

Para fontes identificadas com CSV público direto na ANTT, pode-se usar `--url-oficial` (somente caminho direto HTTPS em `dados.antt.gov.br`, redirecionamentos recusados, CSV até 32 MiB). **Não há endpoint oficial de CSV MDF-e/RNTRC verificado nesta entrega**; o código de acesso HTTP não equivale a coleta real.

## Dados armazenados

Duas tabelas SQLite: `antt_mdfe_lotes` (recorte, SHA-256, data, arquivo, fonte, versão ativa) e `antt_mdfe_od` (competência, origem/destino, nível, NCM, categoria, toneladas, MDF-e, viagens mínimas e TKU quando presentes).

O recorte é a identidade estável do conjunto de filtros. Uma nova exportação sob o mesmo recorte cria uma revisão preservando a anterior. Arquivo idêntico é idempotente. **Não agregar recortes que possam se sobrepor**. Nenhum dado de terceiros é incorporado ao repositório público.

## Regras de qualidade

- Os valores de teste são inteiramente sintéticos. CSV importado não é automaticamente fonte homologada: status `IMPORTADO_NAO_HOMOLOGADO`.
- O painel é baseado em MDF-e associado ao RNTRC. MDF-e possui exclusões e não cobre todo o transporte rodoviário.
- NCM pode estar ausente; cortes por produto são amostrais. Nunca inferir toda a soja, todo o milho ou toneladas nacionais a partir de recortes NCM.
- Uma viagem pode gerar múltiplos MDF-e; contagens não equivalem a viagens realizadas.
- Rejeitar linha de total, mistura de total e detalhe, dimensões repetidas, quantidade inválida e competência ilegível.
- Não transformar o número de MDF-e em frete negociado nem comparar livremente volumes de origens/destinos em grãos geográficos diferentes.
- Município com indústria e terminal portuário deve permanecer ambíguo quanto ao destino final da carga até existir prova adicional.

## Situação e dependências para integração automatizada

1. Confirmar exportação pública e estruturada na ANTT para matriz OD + competência + produto, ou solicitar fornecimento agregado formal.
2. Testar os campos reais e mapear os rótulos/níveis originais; não usar engenharia reversa da API interna do Power BI.
3. Conectar o modo URL apenas após URL oficial, granularidade, periodicidade e direitos verificados; então agendar coleta incremental, capturar snapshots e tratar revisões.
4. Confrontar por amostras os resultados importados com os números do painel e definir cobertura/denominadores.
5. Integrar banco canônico do NIVON e camadas de análise de tendências/fretes, mantendo etiqueta `AMOSTRAL_NCM` quando aplicável.

**Nenhum cron, deploy, acesso a base privada ou tonelagem real foi ativado por este PR.**

## Monitor de catálogo após integração no main

O workflow `.github/workflows/antt-mdfe-catalogo.yml` inspeciona diariamente a API oficial de metadados CKAN ANTT e produz relatório JSON auditável em artefato do GitHub Actions com retenção de até 90 dias. Este agendamento é apenas para descoberta de fontes, **não baixa nem armazena tonelagem de MDF-e**. Na falta de um CSV oficial verificável, o painel continua sendo fonte consultável manualmente e os volumes permanecem não coletados.

A extração operacional em arquivo, persistência em Google Cloud e habilitação de indicadores ficam condicionadas à publicação/fornecimento de dados estruturados, homologação do universo de transporte e configuração segura de credenciais. Não inserir segredos ou arquivos particulares no repositório público.
