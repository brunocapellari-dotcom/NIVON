# IVO — Rodada 11: benchmark anual PAM por município e vintage

**Data-base:** 21/10/2026. **Escopo:** investigação estatística offline, com
fixtures sintéticas e dados em SQLite criados pelos próprios testes NIVON.
**Sem** coleta efetiva da PAM/SIDRA nesta rodada, licenças reais auditadas,
instalação ML, treinamento real, atualização de produção, merge ou deploy.

## Por que um motor anual separado

- A Produção Agrícola Municipal (PAM) publica **dados anuais** por município.
- O LSPA publica **estimativas mensais do ano civil**: cada atualização não
  representa a produção daquele mês.
- A CONAB usa recortes por safra e levantamento, não necessariamente por ano
  civil, e as divulgações também são revisáveis.
- Desse modo, o motor mensal já existente (`ivo_benchmark_ml`) não é aplicável
  diretamente à PAM, e valores reportados não são medições físicas certificadas.

## Implementado

`src/nivon/ivo_pam_benchmark_anual.py`:

1. Recebe uma árvore de **versões anuais** do tipo `EventoPAM`, bytes JSON e
   PDFs registrados em `registro_snapshots`; reutiliza o
   `historico_edicoes_pam_asof`, sem criar outra fonte de dados.
2. Bloqueia datasets misturados por município IBGE, variável SIDRA,
   produto C81, unidade, ano e calendário. Audita a classificação de
   **todos os arquivos**, inclusive de versões futuras, e só admite
   `SINTETICO`, mediante autorização explícita do experimento.
3. Para cada ano-alvo, simula emissão às **00:00 UTC de 1º de janeiro**.
   Reconstrói ano a ano os valores que já estavam publicados, coletados e
   registrados no instante histórico, sem usar revisões futuras.
4. Permite janela de treinamento de 3 a 20 anos, estritamente **consecutivos**
   e sem interpolação; atraso admissível do último ano publicado é explícito
   (padrão até 2 anos). Períodos indisponíveis ficam como folds ignorados.
5. Calcula um **baseline ingênuo anual** (último ano já disponível) e um
   candidato determinístico de **tendência mediana** (mediana dos incrementos
   anuais, extrapolada pelo horizonte e limitada inferiormente a zero).
   A mediana não é alegada como treinamento de ML nem previsão calibrada.
6. Calcula MAE, WAPE, ganho relativo quando matematicamente definido, hashes
   dos valores usados em cada fold, anos de treino e timestamp da emissão.
7. Separa a política de comparação de rótulos
   `PRIMEIRA_PUBLICACAO` versus `ULTIMA_REVISAO_ATE_CORTE`, ambas
   calculadas somente com versões disponíveis até o corte de avaliação.
   Revisões posteriores mudam, quando apropriado, o erro avaliado, **não**
   a previsão reconstruída no passado.
8. Sinaliza sempre `dados_reais_autorizados=False`,
   `resultado_final_certificado=False`,
   `modelo_homologado=False`, `promocao_automatica=False`.

`tests/test_ivo_pam_benchmark_anual.py` verifica desempenho calculado sobre
uma série linear **inteiramente fictícia**, o atraso da primeira publicação,
errata divulgada depois da previsão, distinção entre primeira versão e revisão,
bloqueio de dados reais (inclusive escondidos em edições futuras), snapshot
ausente/adulterado, falta de anos, misturas territoriais e ausência de
autorização. Resultado da série sintética não serve como evidência de
qualidade preditiva sobre o agronegócio.

## Pontos não resolvidos

- Não há verificação externa de que os PDFs sejam documentos oficiais
  correspondentes àquela cultura, variável, município e período; a URL
  e o SHA-256 são somente indícios locais e provas de integridade.
- O SIDRA não traz diretamente no JSON pontual a data de publicação;
  datas no `registro_snapshots` são declaradas até confirmação.
- O histórico real das versões anteriores às erratas precisa existir:
  o valor original não pode ser deduzido de uma correção posterior.
- O benchmark não encontra automaticamente o ano em que uma série
  foi revisada, não faz backfill ou atualização remota, nem compara
  calendário PAM com safra CONAB sem mapa fenológico/metodológico.
- Não há amostra real homologada, direitos por operação comprovados,
  teste fora da amostra com dados reais, calibração de intervalos,
  distribuição de erro anual ou implantação operacional.

## Próxima prioridade

1. Identificar e preservar arquivos históricos autênticos da PAM (original,
   errata, documentação e licença), com coleta autorizada e cadeia de custódia.
2. Estabelecer **política de verdade anual**: primeira publicação,
   revisão em data de referência ou consolidação auditada; uma não deve
   substituir silenciosamente a outra.
3. Se autorizados, testar em **ambiente segregado de homologação** com
   publicação/coleta reais, por município, produto e ano, mantendo validação
   independente e baseline ingênuo.
4. Expandir para benchmark de preços/fretes **por observação compatível**,
   sem agregação indevida de frete por município e sem importar modelos
   de periodicidade errada.
