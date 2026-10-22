# CONAB — integração confirmada de safra e balanços (21/10/2026)

## Componentes reais
- Origem: CONAB oficial via agrobr 2.0.0; cada edição validada contra `conab.levantamentos()` (78 edições identificadas no primeiro teste).
- Safras: `nivon_conab_safras`, soja e milho de MT, 1º levantamento 2026/27 e 12º levantamento 2025/26; quatro linhas registradas em Neon PostgreSQL.
- Balanços: `nivon_conab_balancos`, sete períodos por produto para a edição 2026/27, 1º levantamento; 14 linhas reais de soja e milho registradas.
- Trilha de execução: `nivon_conab_ingestions`, com quantidade validada, inserida, origem, edição e data da coleta.
- Auth: GitHub Actions OIDC → Neon Function `conabingest`; tokens temporários, sem senhas do banco no GitHub.
- Source SQL: `database/neon_conab_schema.sql` e `database/neon_conab_balancos.sql`.
- Workflows: `.github/workflows/conab-neon-ingest.yml`; build separado `.github/workflows/build-neon-conab.yml`.

## Evidência e metodologia
- Safras recentes/históricas, com deduplicação: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39699925004
- Balanço, 14 registros (7 soja + 7 milho), zero alertas no diagnóstico, persistência OIDC: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39700543320
- Teste de proteção das duas rotas sem autenticação: https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39700736633
- A seleção de edições respeita data de publicação. O **número de levantamento pertence à edição**, não deve ser confundido com safra ou data do dado.
- Safras são **PROJETADO** quando provenientes do levantamento; não classificar como produção efetiva.
- Balanço preserva estoque inicial/final, produção, importação, consumo, exportação, suprimento e demanda (mil toneladas), incluindo valores negativos e nulos publicados.
- Alertas de identidades contábeis sinalizam incoerências sem reescrever valores originais.
- As séries distintas têm PK lógica com produto, período, edição e hash do conjunto de valores; versões anteriores não são sobrescritas.

## Limitações
- Histórico incompleto; dois levantamentos de safra e um balanço já foram testados, não todos os produtos/anos/UFs.
- A PR #58 permanece draft e o cron de quarta-feira na branch principal **não está ativo** até merge.
- O agendamento e as rotinas de coleta foram testados em CI manual/push, mas ainda não comprovados em dias sucessivos.
- Revalidar de tempos em tempos revisão metodológica, licença, origem, número de linhas e ano-safra.
- Não realizar full scan, bypass de CAPTCHA ou downloads massivos sem limites/términos homologados.
- CEPEA e IMEA são as outras fontes P0, ainda sem coleta estrutural homologada.

## Próximas ações
1. Confirmar idempotência do balanço com segunda execução real.
2. Expandir backfill dos levantamentos CONAB em lotes controlados; ampliar oferta/demanda às edições anteriores.
3. Avaliar catálogo/arquivos oficiais do SICARM sem contornar o mecanismo de consulta.
4. Concluir CI e merge controlado para liberar programação semanal, com monitoramento de freshness e backup.
