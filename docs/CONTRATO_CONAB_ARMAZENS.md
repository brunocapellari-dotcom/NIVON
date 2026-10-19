# CONAB / SICARM — importador de armazenagem (somente leitura local)

Fonte pública oficial do cadastro: https://www.gov.br/conab/pt-br/atuacao/armazenagem/saiba-mais-sobre-o-cadastro
Arquivo candidato: https://portaldeinformacoes.conab.gov.br/downloads/arquivos/ArmazensCadastrados.txt

O arquivo candidato ultrapassou o limite do navegador (4 MiB+) e a inspeção direta do arquivo inteiro não foi possível no ambiente disponível. **Layout, separador, codificação e grão do registro NÃO homologados**. A ferramenta `src/nivon/conab_armazens.py` exige passar `LayoutArmazens` explicitamente a partir de cabeçalhos e unidades comprovados; não presume schema, não aciona HTTP nem publica dados.

`python -m nivon.conab_armazens --inspecionar caminho.txt` lê somente o cabeçalho local, identifica contagens de colunas por separador e hash de amostra, sem imprimir valores de registros nem identificadores individuais.

Após obter amostra oficial de maneira lícita e confirmar os direitos por operação, verificar obrigatoriamente: 

1. Se cada linha é armazém ou célula de estrutura (evitar somar capacidade total repetida);
2. Campo de identificação da unidade e sua unicidade; UF, município e eventual código IBGE;
3. Se capacidade estática é expressa em toneladas ou quilogramas; convenção decimal;
4. Reconciliação de contagens e capacidade com dados oficiais de competência compatível;
5. Datas de publicação, referência e coleta distintas, hash original, versões, histórico e restauração;
6. Uso comercial e redistribuição somente mediante autorização própria.

O agregador retorna somente total de capacidade estática e quantidade de armazéns distintos por município/UF, sem armazenar CNPJ, razão social, nomes, endereço ou dados individualizados. Nome/UF sem tabela IBGE comprovada não é marcado como código IBGE canônico. Capacidade cadastrada não mede espaço livre, estoque ou ocupação.

Código e testes sintéticos não são homologação real. Runtime/agendamento seguem OFF, sem deploy nem custos.

## Inspeção de cabeçalho concluída em 19/10/2026

O teste descartável de leitura limitada (16.384 bytes; sem persistência) confirmou, no arquivo oficial, **16 colunas separadas por `;` e codificação CP1252**. Na amostra de 20 registros completos: IDs não repetidos, códigos IBGE com sete dígitos e capacidade estática em toneladas com formato decimal brasileiro (`n,dd`). Não houve inspeção do arquivo completo nem prova de que cada linha representa uma unidade inequívoca em toda a base.

O constante `LAYOUT_CONAB_SICARM_HEADER_V1` mapeia: `identificacao_armazem`, `nom_municipio`, `cod_ibge`, `uf`, `qtd_capacidade_estatica(t)`. Também existem colunas de capacidade de expedição e recepção, que **não podem ser somadas à capacidade estática**. O arquivo inclui campos pessoais/comerciais, que devem ser excluídos dos agregados.

A inspeção transitória do CI foi removida após comprovar o cabeçalho. O script continua manual, exigindo `--explicit-yes` e sem agendamento. Permanecem bloqueados a importação de dados reais como histórico homologado, a publicação comercial e o agendamento até revisão de direitos, reconciliação nacional e teste de recuperação.
