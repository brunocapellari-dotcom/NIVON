# IBGE PAM / SIDRA — tabela 1612, lavouras temporárias

Origem metodológica: https://sidra.ibge.gov.br/pesquisa/pam/tabelas/ e https://www.ibge.gov.br/estatisticas/economicas/agricultura-e-pecuaria/9117producaoagricolamunicipalculturastemporariasepermanentes.html.

`src/nivon/sidra_pam.py` prepara URLs oficiais para a tabela 1612, N6 município IBGE, ano civil e classificação 81 com código de cultura fornecido explicitamente. Uma única consulta por município/ano/variável/categoria limita tamanho e favorece histórico rastreável. O sistema não inventa identificadores de variáveis/culturas, unidades ou classificação: códigos dependem de tabelas de metadados/vigência e ainda precisam ser homologados antes de coleta.

O parser offline recebe resposta SIDRA com cabeçalho e registros, valida códigos e datas, preserva unidade original e distingue marcadores: `-` zero absoluto, `0` zero arredondado, `X` dado protegido por sigilo, `..` não aplicável e `...` indisponível. Nunca tratar suprimido como zero. Conservar o contraste entre PAM anual por ano civil, LSPA (estimativa mensal) e progresso semanal CONAB.

**Atenção histórica:** gergelim aparece como cultura PAM a partir da atualização referente a 2025, segundo IBGE; ausência anterior não é produção zero. Esta implementação não consulta a API real nem cria periodicidade automática, ainda exige homologação de direitos, esquema oficial, mudança territorial e total/consistência com o IBGE.

## Evidência real de estrutura da API SIDRA (19/10/2026)

Uma inspeção única, com limite de 128 KB e sem publicação dos valores, confirmou a resposta da tabela 1612 com o cabeçalho real: `D1C=Município (Código)`, `D2C=Variável (Código)`, `D3C=Ano (Código)`, `D4C=Produto das lavouras temporárias (Código)`. Esta ordem difere do parser preliminar anterior, que foi corrigido com testes de regressão. A consulta amostral usou município IBGE 5107925, ano 2024, variável 214, categoria c81 2702. Esquema verificado não significa dataset completo, totais reconciliados ou licença de publicação.
