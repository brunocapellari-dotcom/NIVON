# ANTAQ — Base Histórica Marítima NIVON (offline, sem go-live)

Data da pesquisa: **20/10/2026**. Estado: **CODE_TESTED_SYNTHETIC_ONLY**. Principal restrição externa: download histórico da ANTAQ indisponível no endereço original.

## Fonte primária e localização

- Fonte primária: ANTAQ — https://www.gov.br/antaq/pt-br/acesso-a-informacao/dados-abertos
- Estatístico Aquaviário, painel de downloads anterior: https://estatistica.antaq.gov.br/ea/sense/download.html
- Arquivos anuais históricos documentados: `https://estatistica.antaq.gov.br/ea/txt/{ANO}.zip` — **não presumir disponibilidade atual**. O índice original redirecionou em 20/10/2026 para aviso oficial de indisponibilidade.
- Método técnico de referência (secundário): https://github.com/bruno-portfolio/agrobr/blob/main/docs/sources/antaq.md e o pipeline agrobr; o site deles registra que a fonte está indisponível desde 23/06/2026. A documentação externa NÃO substitui validação de direitos ou de arquivo real.
- Catálogo canônico do NIVON: `config/rotas_coleta.v1.json`, dataset `ANTAQ_MOVIMENTACAO`. O novo módulo utiliza a mesma entidade, sem cadastrar uma segunda fonte concorrente.

## Formato esperado e proveniência

Amostra de esquema documentada (a ser homologada com arquivos reais) no ZIP anual:
- `{ANO}Atracacao.txt`: `IDAtracacao`, `Ano`, `Mes`, `Porto Atracação`, `Terminal`, `SGUF`
- `{ANO}Carga.txt`: `IDAtracacao`, `CDMercadoria`, `VLPesoCargaBruta`, `Sentido`, `Natureza da Carga`, `Tipo Navegação`
- `{ANO}Mercadoria.txt`: `CDMercadoria`, `Nomenclatura Simplificada Mercadoria`

TXT separado por `;` com `UTF-8 BOM`, decimais `pt-BR`. Validadores exigem headers, links, pesos não negativos, meses conhecidos, ID de atracação único, mercadoria sem mapeamento conflitante e limite de tamanho/quantidade do ZIP. Apenas leitura de bytes fornecidos localmente, sem extrair caminhos nem executar macros ou scripts.

**Unidades e grão:** peso bruto publicado em toneladas, por linha de carga; uma atracação pode ter muitas linhas de carga. `COUNT(Carga)` não equivale `COUNT(DISTINCT IDAtracacao)`. O agregado permitido é: ano/mês de competência publicados × porto × terminal × UF × mercadoria × sentido × natureza da carga × navegação. Nada disso comprova por si só navios AIS presentes ou carga individual já embarcada.

**Temporalidade:** `Ano/Mes` do registro pode divergir do mês de `Data Atracação`. Nenhuma inferência de fuso, volume realizado por embarcação ou publicação original é feita sem fonte. Campos armazenáveis da análise: competência, período de referência, data da publicação (quando comprovada), coleta UTC, hash do ZIP, source_id e evidence_id da publicação.

## Motores NIVON

- `src/nivon/maritime/antaq_archive.py` — `analyze_antaq_archive`: join offline, agregados mensais, linhas sem atracação e códigos desconhecidos expostos, sem zero fabricado.
- `compare_antaq_archive_vintages`: compara revisões de uma mesma fonte e competência. Ausência de grupo em uma nova versão é rotulada AUSENTE, **não** queda para zero toneladas.
- `src/nivon/maritime/antaq_archive_cli.py` — interface manual local sem download ou escrita do resultado.
- Regressões `tests/test_maritime_antaq_archive.py` e `tests/test_maritime_antaq_archive_cli.py`: ZIPs 100% sintéticos, reprodutíveis, negativos, revisões e vazamento temporal.

### Uso manual de validação (apenas arquivo próprio legalmente obtido)

```bash
PYTHONPATH=src python -m nivon.maritime.antaq_archive_cli \
  --zip /caminho/arquivo-oficial-2024.zip \
  --year 2024 \
  --source-id ANTAQ_EA_2024 \
  --collected-at 2026-10-20T14:00:00Z \
  --rights-verified
```

O parâmetro `--rights-verified` é uma declaração de operador, não valida licença automaticamente. **Não inserir uma data de publicação fictícia**: sem documento verificável, não fornecer `--source-published-at`, `--publication-evidence-id` ou `--as-of` para backtest. Para estudos de previsão, os três parâmetros só podem ser fornecidos se a data de publicação e a captura são efetivamente rastreáveis no corte temporal.

A saída apresenta somente metadados, contagens e flags. Não persiste linhas no Nivon, não transfere dados para LLM e não publica métricas.

## Limitações atuais

- Nenhum ZIP histórico oficial foi adquirido, processado ou homologado neste PR. Qualidade de dados reais, mudanças de layout, encodings e direitos precisam de teste com arquivos legítimos.
- Estatísticas retrospectivas estão sujeitas a revisão; backtests exigem vintages comprovadas publicadas/coletadas antes de cada data de previsão. **O valor atual de uma série antiga não comprova o que era conhecido naquela época.**
- A ANTAQ publica dados estatísticos, não feed AIS por embarcação. A avaliação de fluxo portuário e linha de frete depende de normalização de terminal, produto e horizonte, sem causalidade presumida.
- A plataforma de coleta SDP reaberta em outubro de 2026 para envio por instalações não é autorização para acessar o upload privado nem substitui downloads públicos indisponíveis.
- Direitos de coleta, conservação, uso em previsão, exposição pública, redistribuição e retenção devem ser considerados separadamente. Não executar scraping para contornar WAF.
- Antes de go-live: amostras reais com hash, auditoria da metodologia ANTAQ, cobertura por ano/porto, degradação/freshness, restauração de arquivos, segurança e licenças.
