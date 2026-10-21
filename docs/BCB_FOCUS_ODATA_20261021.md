# NIVON — Conector Banco Central Focus OData (21/10/2026)

**API fonte primária:** https://dadosabertos.bcb.gov.br/dataset/expectativas-mercado (ODbL). Serviço anual: https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais

## Implementado

- Planner de consulta OData com filtro fixo por indicador permitido (Câmbio, Selic, IPCA, PIB Total) e período explícito de até 31 dias, com máximo 500 linhas por consulta; sem OData injetável.
- Normalizador de Media/Mediana por Data e DataReferencia (ano alvo), com validação de indicadores, datas, unidades, nulos, valores anômalos, duplicidade, paginação e hash SHA.
- Aquisição HTTPS pontual via módulo existente `nivon.apis_gratuitas_execucao`: sem redirects, limites e MIME JSON. Mantém default-deny, sem cron, publicação ou persistência.
- `scripts/smoke_bcb_focus.py` em modo explícito `--executar`, saída somente metadados de execução.

Uso em executor com rede, de maneira **pontual**:

    PYTHONPATH=src python scripts/smoke_bcb_focus.py --indicador Câmbio --inicio 2026-10-19 --fim 2026-10-20 --executar

## Semântica correta

Câmbio Focus é projeção de agentes consultados, não PTAX, dólar comercial ou projeção oficial BCB. Selic Focus é expectativa anual para ano-alvo, não meta ou taxa observada SGS 11. BCB oferece estatísticas diárias por pesquisa, mas a divulgação pública possui calendário e atraso próprios. `Data` é data da pesquisa, `DataReferencia` é ano-alvo e `publicacao` permanece NULL enquanto não houver evidência da data exata de disponibilização. Um backtest que use expectativas antes de sua divulgação sofrerá look-ahead; por isso `apto_backtest_asof=false`.

## Gates pendentes

- Teste com resposta HTTP real (esta implementação foi validada inicialmente contra transporte sintético);
- Datas exatas de divulgação pública, história de revisões e política de vintage;
- Licença ODbL por operação e atribuição, persistência privada com backups, inspeção de dados e observabilidade;
- Nenhuma atividade automática ativada, sem custo, deploy ou segredos.

A diferença entre código que consulta sob demanda, base persistida e produto operacional permanece explícita. A fonte BCB já existia no catálogo, foi reaproveitada sem novo source_id ou dataset redundante.
