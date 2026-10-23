# IVO — Execução em lote: PAM/IBGE do planejamento ao dado REAL (22/10/2026, America/Cuiaba)

## Objetivo e decisão

Substituir dezenas de comandos unitários por uma única cadeia operacional:
**API pública SIDRA -> parser existente -> validação semântica ->
quarentena original e SHA -> SQLite incremental -> painel IVO ->
auditoria completa -> cópia no Google Drive**.

Foi mantido o uso **não comercial** e foi removida a dependência de
flags de licença do catálogo **neste coletor público operacional**; não
alteramos as restrições de fontes privadas nem a fonte de verdade de
outros conectores. O cadastro geral `IBGE_PAM` não foi alterado.

## Plano de prioridades e resultado

| Prioridade | Atividade | Estado verificável | Teste/critério |
|---|---|---|---|
| P0 | Integrar consulta pontual SIDRA, normalização, arquivo e SQLite | **CONCLUÍDO** | Pipeline completo + coleta real |
| P1 | Atualização incremental por SHA/data; deduplicação e revisões | **CÓDIGO CONCLUÍDO**, reincidência REAL no mesmo banco ainda não ensaiada | E2E de versões, sem/alteração e cortes históricos |
| P2 | Painel anual legível pelo IVO | **CONCLUÍDO** | Consulta por município, cultura, ano, variável e corte |
| P3 | Lotes independentes e tolerância a falhas por tarefa | **CONCLUÍDO** | E2E com 2 válidas + 1 inválida |
| P4 | CLI para dados locais ou API pública; exemplo MT | **CONCLUÍDO** | E2E da CLI + piloto remoto |
| P5 | Reconciliar SQLite, arquivos brutos e recibos | **CONCLUÍDO** | Auditoria de conteúdo real + testes de corrupção |
| P6 | Preservar piloto além do artefato GitHub | **CÓPIA PONTUAL CONCLUÍDA** | ZIP verificado no Google Drive; backup automático ainda pendente |
| P7 | Agendar coleta contínua, backup persistente e alertas de mudanças | **PRÓXIMO BLOCO OPERACIONAL** | E2E recorrente, restauração e monitoração |
| P8 | Construir benchmark anual REAL robusto | **DEPENDÊNCIA: vintages antigas, datas e recortes** | Backtest estritamente as-of sem leak |

## Código implementado

- `src/nivon/ivo_pam_operacao.py`: ingresso HTTP público ou
  arquivo local por tarefa, até 30 por execução, armazenamento
  content-addressed, tabelas `pam_vintages` e `pam_capturas`,
  detecção de revisões, isolamento de falhas, query as-of de coleta,
  idempotência e CLI. Evita retrodatação das capturas em comparação à
  última edição do mesmo alvo.
- `src/nivon/ivo_pam_consulta.py`: painel por município/ano/produto,
  com valores anuais, diferenças e variações SOMENTE entre anos
  consecutivos; nunca confunde PAM com resultado mensal.
- `src/nivon/ivo_pam_qualidade.py`: percorre banco e arquivos originais,
  verifica SHA dos bytes, integridade do recibo, URL, célula, unidade,
  valor/estado, chaves estrangeiras e `PRAGMA integrity_check`;
  somente leitura.
- `tests/test_ivo_pam_operacao_e2e.py`: testes ponta a ponta,
  não apenas mocks isolados, cobrindo ingestão, reabertura, versões,
  retrodatação, ausências, reprocessamento, consulta, CLI, lote misto,
  auditoria de corrupção e comparação anual.
- `config/ivo_pam_piloto_mt.v1.json`: seis consultas pontuais
  para Tangará da Serra, Lucas do Rio Verde e Sorriso.
- `.github/workflows/ivo-pam-piloto.yml`: piloto real em PR, com
  limites de rede e tempo, sem secretos, sem deploy, sem agendamento
  automático. Preserva cópia ZIP temporária por 3 dias.

### Como executar em um único comando

Com Python 3.11 e `PYTHONPATH=src`:

```bash
PYTHONPATH=src python -m nivon.ivo_pam_operacao \
  --modo PUBLICO_IBGE \
  --tarefas config/ivo_pam_piloto_mt.v1.json \
  --db dados_operacionais/ivo_pam.sqlite \
  --acervo dados_operacionais/quarentena_pam
```

Para consultar o painel do IVO:

```bash
PYTHONPATH=src python -m nivon.ivo_pam_consulta \
  --db dados_operacionais/ivo_pam.sqlite \
  --municipio 5107958 --produto 2713 --variavel 214 \
  --inicio 2021 --fim 2024
```

O piloto do GitHub não escreve em banco cloud: persistiu os resultados
num artefato e foi copiado para o Drive associado ao projeto. Execuções
recorrentes precisam de armazenamento permanente, credenciais separadas
de serviço se necessário e backup/restauração comprovados.

## Coleta realmente executada e verificada

**Fonte:** SIDRA, tabela 1612, variável 214, categoria C81 2713,
nível territorial municipal n6. **Momento da coleta:**
23/10/2026 02:39:33–02:39:34 UTC
(22/10/2026 22:39:33–22:39:34 America/Cuiaba).

GitHub Actions:
- [Inspeção pública com seis downloads bem-sucedidos](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890755981).
- [Suíte integrada de 1.242 testes, com 8 ignorados](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890755934).
- SHA da implementação em teste: `c7bc110e2115e88a5f28144a4a6f815ba0a00c9b`.

| Município (código IBGE) | Ano | Soja informada (toneladas) | Hash original SHA-256 |
|---|---:|---:|---|
| Tangará da Serra (5107958) | 2021 | 382.800 | `9db1e767b08f08be0acc0cdbd7e24112274cc2a6f611c29867ffafdb1662c7f5` |
| Tangará da Serra (5107958) | 2022 | 400.200 | `05860eb7ed3f34f0a4a34d5c6c33d4ba54e53a790f1762361f2ad8027a2fdadb` |
| Tangará da Serra (5107958) | 2023 | 423.540 | `58d13ab11c9a21b6351f51ac89fac449a4f1025a715dbf34dcca9a425b31fce2` |
| Tangará da Serra (5107958) | 2024 | 364.048 | `6cc4e7b267b67d95fddb09f6bdd81fbc2e90ad935dea01d3b844cc728e313bd4` |
| Lucas do Rio Verde (5105259) | 2024 | 744.720 | `98cfcda97af39287c646ba58a361cb9ec70f0866fbaaf5afa80053f4bacaf649` |
| Sorriso (5107925) | 2024 | 2.084.520 | `3c5bda7b7b717b08fd5486f83b6e8503a14404fb41ce570e337afe4276ebafba` |

**Resultado de auditoria:** 6 requisições concluídas, zero falhas,
6 edições, 6 capturas, integridade SQLite `ok`, zero violações de
chaves estrangeiras, zero erros de comparação contra bytes brutos.

A cópia do ZIP no Google Drive conectado a **agrologmt@gmail.com**
foi aceita e teve leitura posterior de metadados concluída:
[NIVON_PAM_IBGE_MT_2026-10-23_coleta_real_validada.zip](https://drive.google.com/file/d/1uXsCXgBPppn5ACdb4Mfzu0pgpuTOiYrR/view?usp=drivesdk).
Pasta:
[NIVON - Evidencias de Coleta](https://drive.google.com/drive/folders/1P0RxlFua6H73mE7aOlkXGSNOND5DcvH9).
O ZIP inclui banco SQLite, seis respostas SIDRA originais, hashes,
recibos e relatórios de execução/auditoria.

**Ressalva histórica indispensável:** são estatísticas anuais tal como
obtidas no momento da consulta. Uma captura feita depois da errata de
setembro de 2026 NÃO reconstrói automaticamente a edição divulgada
antes da errata. Não publicar falsa métrica de performance preditiva
`as-of 2021` sem seu histórico original.

## Próximo lote independente do usuário

1. Criar rotina de atualização recorrente com um **destino durável**
   seguro no Google Cloud ou Google Drive conectado, evitando uploads
   manuais e definindo política de versões/retention.
2. Guardar histórico incremental das mesmas células (revisões entre
   consultas), alertar quando SHA ou valores mudarem e reconstruir
   banco em teste a partir do acervo.
3. Ampliar seleção de anos/municípios/culturas conforme necessidade,
   limitar taxa de requisição e evitar full scan do IBGE.
4. Ligar resultados a relatórios do IVO com proveniência e separar
   números PAM, CONAB e IMEA por definição estatística.
5. Só usar histórico de previsões e vintage para benchmark retrospectivo
   quando existirem timestamps confiáveis de publicação e captura
   anteriores à data simulada, sem fabricar versões antigas.

**Decisões sensíveis ainda não realizadas:** ativação de serviços pagos,
deploy, merge do PR, compartilhamento público de arquivo privado, mudança
de política de outras fontes ou substituição de fontes de verdade.
