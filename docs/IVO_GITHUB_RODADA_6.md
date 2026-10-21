# IVO — Rodada 6: incorporar capacidades do catálogo aos motores do NIVON

**Data:** 20 de outubro de 2026. **Status:** código em branch do PR #7, revisão e testes
sintéticos; **não é operação autônoma e nenhum modelo real está homologado**.

## Resultado implementado

Esta rodada implementou adaptadores, não uma cópia de todos os recursos
de MLForecast, River, DuckDB, LlamaIndex ou HierarchicalForecast. O princípio
é usar diretamente a biblioteca madura quando necessária e completar em
código próprio apenas contratos **específicos do domínio NIVON** (datas as-of,
permissões, safra, escopo territorial, unidades, baseline, auditoria, métricas).

| Componente | Biblioteca | Código da aplicação |
|---|---|---|
| Forecast supervisionado | MLForecast + scikit-learn Ridge **opcionais** | `ivo_mlforecast_adapter.py` |
| Walk-forward para comparar modelos | Usa adaptador MLForecast **opcional** | `ivo_benchmark_ml.py` |
| Feedback incremental, modelo de resíduos | River **opcional** | `ivo_river_adapter.py` |
| Consulta tabular eficiente Parquet | DuckDB **opcional** | `ivo_duckdb_adapter.py` |
| Recuperação de claims com evidência | LlamaIndex segue candidato; adaptador lexical **nativo** | `ivo_conhecimento_adapter.py` |
| Somas regionais consistentes | HierarchicalForecast segue candidato; bottom-up **nativo** | `ivo_hierarquias.py` |
| Intervalos de previsão | MAPIE candidato; quantil sobre histórico **nativo** | `ivo_intervalos.py` |
| Avaliação de resultados e drift | Evidently candidato; detector de degradação **nativo** | `ivo_monitor_modelos.py` |

O registro completo de 38 ferramentas candidatas está em
`config/ivo_ferramentas_github.v1.json`, com status HONESTO para cada uma.
Uma biblioteca opcional presente em `pyproject.toml` **não está instalada
por isso** e não valida sua compatibilidade com a versão do runtime.

## Especificações de segurança

- MLForecast exige dados observados com fonte, unidade, cultura, geografia,
  competência, calendário mensal e publicação/coleta; exige 36 meses
  contíguos conhecidos antes do alvo e admite atraso da fonte de até 3 meses.
  Treino Ridge usa lags 1, 2, 3, 12; sem otimização de hiperparâmetros
  escondida, sem exógenas futuras ou preenchimento artificial de lacunas.
- O benchmark chama o adaptador novamente em cada mês, calcula MAE, WAPE e
  vantagem sobre baseline sazonal, preserva meses descartados e mantém
  corte de avaliação dos rótulos. Utiliza última revisão conhecida nesse
  corte para resultado observado, sem afirmar que esta era a primeira
  publicação. O ledger continua capaz de reportar primeiras publicações.
- River recebe relatório de avaliação homogêneo e faz replay prequential:
  previsão primeiro, depois aprendizado dos rótulos publicados e registrados
  estritamente antes da próxima emissão. Não reclassifica BACKTEST como LIVE,
  não instala pesos nem promove versões.
- DuckDB apenas lê Parquet **local** num diretório autorizado, com SQL
  parametrizado fixo, filtro por série, limite de linhas/bytes, sem
  symlinks/path traversal e SHA256 conferido antes/depois da leitura.
  Cada registro é normalizado ao `historico.Observacao` do NIVON, depois
  selecionado no corte publicação/coleta. Arquivo local não é automaticamente
  dado oficial ou comerciável.
- Recuperação de claims é somente leitura sobre snapshots exportados.
  Bloqueia direitos não aprovados, claims rejeitados, fontes temporais
  ainda indisponíveis, eventos superseded e conteúdos sem hash. Mantém
  tipo observado, projeção, estrutural etc. **Não valida por si a
  autoridade da assinatura da Knowledge Factory.**
  Texto de fontes é sempre dado não confiável: nenhuma instrução é executada.
- Nenhum dos módulos chama APIs de LLM, instala pacotes, faz deploy ou
  escreve no Segundo Cérebro. Mudança de modelo e conhecimento canônico
  continua subordinada aos gates de auditoria de Hermes.

## Como habilitar em ambiente isolado, quando homologado

Os extras estão separados no `pyproject.toml`:

```bash
python -m pip install ".[ivo-ml,ivo-online,ivo-query]"
PYTHONPATH=src python -m unittest discover -s tests -p 'test_ivo_extras_reais.py' -v
```

Isto é **orientação técnica**, não execução feita em produção. Não rodar sem
auditar versões exatas, transitivas, rede do PyPI, licenças, quotas gratuitas,
backup e proteção de credenciais. No CI padrão, os testes das bibliotecas reais
ficam *skipped* porque dependências não são instaladas. Os testes de contratos
com backend injetado são executados automaticamente.

## Gates para operação completa

1. Homologação jurídica/técnica e repositório de dados reais retrospectivos
   da CONAB, IBGE, IMEA, MDIC, INMET, ANA, ANP, ANTAQ, bolsas, etc.
2. Pipeline cloud de backfill incremental e armazenamento imutável, com
   checksums, vintages, quality score e recuperação testada.
3. Adaptação do MLForecast e River aos tipos de alvos que exigem métodos
   distintos (mensal/diário/safra, taxa, preço, volume, vazão); **não
   forçar um único modelo à pecuária, meteorologia e logística**.
4. Treinamento real, teste de impacto temporal das variáveis exógenas,
   validação independente de probabilidades, shift de regime e estresse.
5. Contrato autenticado com Hermes/Research AI/Knowledge Factory,
   aprovação independente do knowledge snapshot e trilha de auditoria.
6. Disponibilização na ferramenta/agent IVO e WhatsApp somente após
   dados, APIs, segurança, observabilidade, quotas e testes E2E homologados.
7. Nenhum modelo entra em produção automaticamente só porque sua métrica
   melhorou em um conjunto de backtest sintético.

**Alcance comprovado:** módulos e testes offline. **Não comprovado:**
instalação real dos três pacotes, compatibilidade na infraestrutura de
produção, fontes de dados reais, aprendizado de LLM, go-live, previsões
reais com acurácia validada ou voz JARVIS.
