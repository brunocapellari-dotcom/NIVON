# NIVON / IVO — Continuidade incremental e retomada dos lotes PAM

**Corte técnico:** 23/10/2026. **Tipo de entrega:** implementação no GitHub em PR draft e CI automático, sem nova coleta real, deploy ou custos. **Responsabilidade:** o planejador orienta a operação; um executor autorizado continua sendo necessário para qualquer comunicação HTTP.

## Integração que já funciona

```text
Capturas SIDRA -> SQLite operacional + bytes/recibos em quarentena
                            │
                            ▼
            Auditoria de integridade completa
      (SQLite, chaves, SHA, URL, município, cultura, ano)
                            │
                            ▼
                Planejador incremental
                 ├── captura recente
                 ├── sem captura
                 ├── captura desatualizada
                 ├── erro de lote anterior
                 └── revisão ENTRE capturas (não release oficial)
                            │
                            ▼
      relatorio_continuidade.json + proximas_tarefas.json
                            │
                            ▼
         Próxima execução pelo COLETOR AUTORIZADO
       (não é disparada por este módulo)
```

### Artefatos entregues

- `src/nivon/ivo_pam_continuidade.py`: consulta somente leitura às tabelas `pam_capturas` e `pam_vintages`, exige um catálogo de 1–30 recortes canônicos SIDRA 1612, verifica integridade SQLite/bytes com `ivo_pam_qualidade`, analisa a última captura e a janela de frescor, emite plano de novos trabalhos, aceita resultados de execução anterior para retentativas dirigidas. O algoritmo não cria tarefas para recortes recentes, salvo falha explícita de execução.
- `tests/test_ivo_pam_continuidade_e2e.py`: E2E de capturas recentes, ausentes e vencidas, revisão de valor, repetição sem mudança, não vazamento de SHA futuro em replay `as-of`, retomada de falhas, corrupção SQLite/bytes, entradas inválidas, CLI, idempotência e exportação da lista de tarefas.
- `scripts/smoke_ivo_pam_lote.py`: execução integrada sintética inclui **3 capturas de 2 recortes**, uma mudança real **somente dentro das fixtures**, um terceiro recorte sem captura, detecção de um alerta e uma pendência; verifica backup/restauro e que nenhuma ação de promoção aconteceu.
- `docs/IVO_PAM_OPERACAO_UNIFICADA_20261023.md`: documentação do pipeline anterior, SQLite, backup, reauditoria e restauração.

### Contrato temporal / epistemológico

`corte_coleta` representa apenas o momento até o qual os bytes foram CAPTURADOS. Ano civil é a competência PAM. **Não confundir qualquer uma dessas datas com a publicação oficial**. Se as mesmas células forem obtidas em dois dias com valores diferentes, o máximo que o monitor pode inferir é que uma alteração tornou-se observável **entre as duas capturas**, sem atribuir o dia de correção do IBGE. SHA local e auditoria validam integridade do arquivo recebido, não autenticidade/documento ou direitos reais.

Os alertas estruturados `REVISAO_OBSERVADA_ENTRE_CAPTURAS` não carregam valor numérico publicável e preservam o SHA dos bytes originais e a data da coleta observada. O módulo nunca calcula média de município nem promove dados para modelos.

### Uso sem comandos manuais por recorte

Com os arquivos do piloto localmente preservados, execute o planejador **uma vez** para todo o JSON de tarefas:

```bash
PYTHONPATH=src python -m nivon.ivo_pam_continuidade \
  --db dados_operacionais/ivo_pam.sqlite \
  --acervo dados_operacionais/quarentena_pam \
  --tarefas config/ivo_pam_piloto_mt.v1.json \
  --corte 2026-10-23T12:00:00-04:00 \
  --idade-dias 7 \
  --saida relatorios/pam_continuidade.json \
  --proximas-tarefas relatorios/pam_tarefas_pendentes.json
```

O horário acima é **exemplo**, não horário verificado ou agendado. `relatorios/` deve existir; arquivos anteriores só podem ser reutilizados com bytes idênticos. O relatório gera `pendentes`, `situacoes`, `alertas_de_revisao`, `integridade_local_verificada=true` e `manifesto_sha256`. O arquivo `pam_tarefas_pendentes.json` contém exatamente a lista esperada por `--tarefas` do coletor operacional. **Não executar** o coletor se a lista estiver vazia; o planejador em si nunca faz rede.

Para retomar especificamente falhas de um lote anterior, acrescentar o parâmetro opcional `--resultado-anterior relatorios/resultado_lote.json`, preservando a MESMA ordem de recortes na lista de tarefas. Um resultado anterior não confiável, incompleto ou com contagens alteradas é recusado sem sugerir uma retentativa inconsistente.

A ferramenta pode ser chamada como etapa de um futuro workflow CI/Cloud Run Job desde que haja persistência privada de SQLite/objetos, autenticação, termos de uso, custo aprovado e atomicidade/backup. **Não foi ativado agendamento permanente**.

### Evidências reproduzíveis

- [CI #39982901455](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39982901455): 1.427 testes (1.419 aprovados), smoke com uma revisão e uma pendência detectadas.
- [CI #39983221011](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983221011): 1.429 testes (1.421 aprovados), rejeição adicional de SQLite e bytes adulterados.
- [CI #39983425858](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983425858): **1.430 testes, 1.422 aprovados e 8 ignorados**, mais exportação compatível de tarefas; zero falhas. Todos os testes de continuidade são offline.

**Coleta real pré-existente:** piloto PR #7 no [Actions #39890755981](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39890755981), seis consultas IBGE/SIDRA, auditadas em staging, sem confirmação de licença externa nem arquivo de vintage anterior. A nova rotina não executou requisições extras.

## Prioridades seguintes (por dependência)

1. **P0** Testar restauração de backup real já arquivado em espaço autorizado e conferir inventário/checksum ao concluir; requer acesso ao artefato e armazenamento habilitado.
2. **P0** Homologar direitos por fonte e operação, registros de tempo, prova da publicação/vintage, assinatura independente e identidade real no Hermes; impedimentos descritos na issue #131.
3. **P1** Acoplar a rotina incremental ao mecanismo de persistência privada no Google Cloud sem criar infraestrutura cobrada, com controle de versão, restore, supervisão e limites.
4. **P1** Criar monitoramento periódico somente após persistência, autorização e confirmação de consumo/custo; produzir alertas das mudanças entre capturas e exportar somente dados autorizados.
5. **P2** Cruzar PAM anual com CONAB, CEPEA e IMEA em bases operacionais e metadados separados, preservando definições, direitos e data de cada fonte.

**Regra de segurança:** `integridade_local_verificada` não equivale a `homologacao_de_fonte`. O programa devolve explicitamente `autoriza_coleta=false`, `autoriza_publicacao=false`, `autoriza_treinamento=false`, `escrita_no_sqlite=false`.
