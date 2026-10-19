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
