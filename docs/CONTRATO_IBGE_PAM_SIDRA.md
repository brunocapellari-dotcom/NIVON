# IBGE PAM / SIDRA — tabela 1612, lavouras temporárias

Origem metodológica: https://sidra.ibge.gov.br/pesquisa/pam/tabelas/ e https://www.ibge.gov.br/estatisticas/economicas/agricultura-e-pecuaria/9117producaoagricolamunicipalculturastemporariasepermanentes.html.

`src/nivon/sidra_pam.py` prepara URLs oficiais para a tabela 1612, N6 município IBGE, ano civil e classificação 81 com código de cultura fornecido explicitamente. Uma única consulta por município/ano/variável/categoria limita tamanho e favorece histórico rastreável. O sistema não inventa identificadores de variáveis/culturas, unidades ou classificação: códigos dependem de tabelas de metadados/vigência e ainda precisam ser homologados antes de coleta.

O parser offline recebe resposta SIDRA com cabeçalho e registros, valida códigos e datas, preserva unidade original e distingue marcadores: `-` zero absoluto, `0` zero arredondado, `X` dado protegido por sigilo, `..` não aplicável e `...` indisponível. Nunca tratar suprimido como zero. Conservar o contraste entre PAM anual por ano civil, LSPA (estimativa mensal) e progresso semanal CONAB.

**Atenção histórica:** gergelim aparece como cultura PAM a partir da atualização referente a 2025, segundo IBGE; ausência anterior não é produção zero. Esta implementação não consulta a API real nem cria periodicidade automática, ainda exige homologação de direitos, esquema oficial, mudança territorial e total/consistência com o IBGE.
