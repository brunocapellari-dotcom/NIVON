# NIVON — Conciliação agrobr × catálogo canônico (21/10/2026)

**Escopo:** uso não comercial; auditoria documental; **nenhuma conexão ativada**.

## Evidências
- agrobr oficial: [índice de fontes](https://github.com/bruno-portfolio/agrobr/blob/9360f80f8aad7c6eaf946dce2f9ed61d4b1d2156/docs/sources/index.md), fixado em SHA `9360f80f8aad7c6eaf946dce2f9ed61d4b1d2156`, declara 41 fontes.
- NIVON: `config/fontes_nivon_master.v1.json` é a **única fonte de verdade**. Nessa branch-base declara 101 fontes, 139 datasets, 42 P0; todas as coletas e operações agendadas estão desativadas.
- Integração agrobr existente: `src/nivon/conab_agrobr.py` na PR #3 usa progresso semanal CONAB. A existência do adaptador não comprova operação dos demais conectores.

## Incremento executável
- `config/agrobr_crosswalk.v1.json`: vínculos entre 41 slugs documentais do agrobr e source_ids NIVON existentes, sem criar fontes ou datasets.
- `src/nivon/agrobr_crosswalk.py`: valida IDs, integridade do upstream, escopo não comercial, exclusões e direitos; calcula cobertura sem dupla contagem. **Nenhuma chamada de rede ou coleta.**
- `tests/test_agrobr_crosswalk.py`: casos positivos e adversariais para duplicatas, fonte inexistente, uso comercial, hashes, exclusão e ativação indevida.

Rodar com:

```bash
PYTHONPATH=src python -m nivon.agrobr_crosswalk --resumo
PYTHONPATH=src python -m unittest discover -s tests -p 'test_agrobr_crosswalk.py' -v
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Critério de decisão
- **MAPEADA:** fonte já canônica; auditar o dataset e o coletor NIVON antes de comparar com o agrobr.
- **NAO_MAPEADA:** avaliar se há benefício setorial e se fonte canônica deve ser acrescentada por revisão independente.
- **FORA_DO_ESCOPO:** não integrar motor de receituário nem módulo de inteligência corporativa.

**Permissões separadas e explícitas:** consulta, coleta, armazenamento, processamento, exibição e redistribuição. Uso não comercial não concede automaticamente nenhuma dessas autorizações.

**Limitações:** correspondência com o catálogo e contagem documental não validam API, estabilidade da fonte, histórico, parsing, custo, direitos ou autenticidade de dados reais. O SHA upstream é uma referência auditável, não uma prova de acessibilidade atual. Qualquer código de terceiros dependerá de auditoria de dependências, licenças, E2E e integração na árvore de build do NIVON.

## Próximo passo
Auditar primeiro os conectores agrobr relacionados a CONAB, IBGE, BCB, MDIC, ANP, ANTT, ANA e USDA contra os módulos nativos; selecionar amostra real autorizada com metadata; testar cobertura histórica e persistência sem transformar dados documentais em fatos observados.
