# IVO — Rodada 9: IBGE PAM anual como candidata, nunca verdade presumida

**Verificação em 20/10/2026.** O normalizador SIDRA/PAM 1612 já existia no
NIVON. Esta rodada **não criou segundo coletor**, nem fez HTTP, download,
scraping, atualização de base real, operação em cloud ou promoção de modelo.

## Resultado de pesquisa metodológica

- A [Produção Agrícola Municipal (PAM), IBGE / SIDRA](https://sidra.ibge.gov.br/pesquisa/pam/tabelas/)
  é uma estatística **anual**, publicada em múltiplos níveis geográficos,
  incluindo município. Sua estimativa consolidada não é medida física por
  fazenda ou produtividade semanal e exige interpretação metodológica.
- O [LSPA, IBGE](https://www.ibge.gov.br/estatisticas/economicas/agricultura-e-pecuaria/9201-levantamento-sistematico-da-producao-agricola.html)
  fornece previsões e revisões mensais referentes ao **ano civil inteiro**,
  NÃO volumes colhidos a cada mês.
- As [notas metodológicas PAM/IBGE](https://www.ibge.gov.br/biblioteca/visualizacao/periodicos/66/pam_2021_v48_br_notas_tecnicas.pdf)
  descrevem consolidação de estimativas por informantes e técnicos e não
  justificam chamar cada valor anual de medição exata da colheita.
- A API SIDRA pode retornar valores numéricos e **marcadores especiais**,
  que têm semânticas diferentes: nulo/sigilo, zero absoluto declarado e
  zero arredondado. Nenhum marcador é transformado em valor exato
  para treino sem revisão própria da variável.

## Código entregue

### `src/nivon/ivo_pam_bridge.py`

Consome **o JSON original já capturado** através do
`sidra_pam.normalizar_pam_1612`, usando os identificadores municipais,
variáveis e produtos C81 numéricos explicitamente fornecidos por mapping
previamente controlado. Não infere o código pelo nome comercial.

Requer `registro_snapshots` do NIVON com correspondência exata de:
dataset `IBGE_PAM`, fonte `IBGE`, SHA256 dos **bytes originais**,
tamanho, MIME, versão do schema `sidra_pam_1612_v1`, referência de ano
civil, competência anual, data de publicação declarada, data de coleta
e tipo de arquivo. Um snapshot ausente, data fora do corte ou formato
alterado bloqueia a conversão. O módulo **não escreve** no ledger.

Gera `historico.Observacao` com:
- `fonte=IBGE`, `calendario=ANO_CIVIL`, `natureza=INFORMADO`;
- `competencia=AAAA` e `referencia=AAAA-12-31`;
- `regiao=MUN_<codigo_IBGE>`, produto `C81_<codigo>`,
  variável `PAM_<codigo>`, unidade declarada do JSON;
- SHA256 da edição, publicação **declarada no ledger** e coleta.

**Importantíssimo:** `normalizar_pam_1612` retorna
`publicacao=None`; o JSON pontual **não traz prova da data oficial de
publicação**. O módulo registra a natureza declarada dessa data de
forma explícita, sem certificá-la. Mesmo snapshots classificados
`REAL_AUTORIZADO` não habilitam treino, nem dizem que há licença
jurídica assinada. O retorno marca
`treino_real_autorizado=False`,
`label_final_certificado=False` e
`homologacao_externa_verificada=False`.

### `tests/test_ivo_pam_bridge.py`

E2E usando os **módulos originais** `sidra_pam` e
`registro_snapshots` e fixtures sintéticas. Testes cobrem valores
anuais, bloqueio sem snapshot, data ausente, data posterior,
SHA/tamanho incoerente, coleta tardia, zero arredondado, zero absoluto,
sigilo, unidade diferente, produto não homologado, fonte adulterada,
schema divergente, tratamento anual versus safra comercial, e a
impossibilidade de usar imediatamente no treinador mensal do IVO.

## Conclusão e próximos gates

**Implementado:** ponte read-only de evidência PAM com rastreabilidade
de bytes e contrato semânticos anuais. **Não comprovado:** dados
do SIDRA coletados de fato, direitos comerciais, data oficial de
publicação verificada fora do JSON, classificação de valor PAM como
ground truth realizável, ambiente com MLForecast/River/DuckDB,
backtest real ou modelo homologado.

Próxima ação: desenvolver mecanismo de **atestação documental de
publicação/edição IBGE PAM por ano** — com fonte oficial datada e
metadados de release guardados no `registro_snapshots` — seguido de
revisão metodológica independente. Só depois testar benchmark anual
por município/UF com definições apropriadas, evitando converter dados
PAM anuais ou CONAB por safra em séries mensais fictícias.

O PR continua draft; merge/deploy dependem de homologação e autorização.
