# NIVON — qualidade do cadastro CONAB SICARM

**Módulo:** `src/nivon/qualidade_conab_armazens.py`. Execução offline: não há fetch HTTP, agendamento, deploy ou redistribuição.

Entrada: agregado municipal produzido por `conab_armazens.agregar_capacidade_local`. O auditor impõe whitelist de campos (para bloquear CNPJ, contato e endereço), SHA-256 do original, limites de tamanho, linhas iguais à soma de IDs distintos, nomes+UF não duplicados, códigos IBGE não colidentes, toneladas positivas e soma exata dentro de tolerância técnica explícita (padrão 0,001 t). Um total externo informado pelo operador pode ser comparado, mas o programa NÃO declara que esse total foi obtido do órgão oficial.

A ausência de IBGE só é permitida em análise diagnóstica (`exigir_ibge=False`). Para uso em mapas e junções operacionais, exigir resolução e validação temporal da tabela IBGE. Publicação e referência desconhecidas permanecem nulas.

**Resultado invariável:** consistência interna não homologa dado real, frequência, licença, uso comercial ou disponibilidade de espaço. `liberado_para_publicacao` sempre `false`. Pendências: direitos por operação, inspeção do arquivo inteiro, conferência dos totais oficiais, vigência temporal e backup durável fora do runner temporário.

Execução: `PYTHONPATH=src python -m unittest discover -s tests -v`.
