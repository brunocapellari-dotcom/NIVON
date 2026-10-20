# NIVON — PTAX oficial e diesel semanal ANP: integração e bloqueios

Data da pesquisa e testes: 20/10/2026. Objetivo: custo zero, sem nova infraestrutura,
sem coleta automática nem publicação de números não homologados.

## PTAX Banco Central — integração criada e testada

Fonte primária: https://dadosabertos.bcb.gov.br/dataset/dolar-americano-usd-todos-os-boletins-diarios
Documentação técnica OData: https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/documentacao

A página do BCB atribui licença **Open Data Commons ODbL**, com dados
desde 28/11/1984 e periodicidade diária. A licença não elimina necessidade
de verificar atribuição, compartilhamento equivalente de bases derivadas e
limitações editoriais/comerciais específicas do produto.

Pipeline criado:
- `ptax_plano.planejar_consultas_ptax`: planeja endpoint exato USD/EUR por janela.
- `ptax_briefing.adquirir_ptax_autorizado`: fonte HTTPS exata, sem redirect,
  direitos de coleta/armazenamento comprovados e gates de dataset ligados
  somente após governança.
- `ptax_briefing.normalizar_snapshot_ptax`: SHA-256, MIME, JSON sem chaves
  duplicadas, fonte/plano/vigência e observações dentro da janela.
- `ptax_briefing.construir_indicador_ptax`: **somente tipoBoletim = Fechamento**;
  não equipara Fechamento Interbancário, Abertura ou Intermediário a PTAX
  oficial de fechamento; valor informado é COMPRA/VENDA, não USD spot.
  A defasagem é avaliada pelo dia local de Brasília (não UTC).
- `pipeline_briefing.gerar_edicao_offline` aceita `ptax_snapshots`
  e incorpora o indicador ao bloco CAMBIO, mantendo trilha SHA/licença.
- Testes `tests/test_ptax_briefing.py` e `tests/test_pipeline_ptax_briefing.py`
  verificam via respostas sintéticas, sem chamada à API real.

**Não foi feita captura real**, ativação de flags, importação histórica completa,
nem revisão jurídica da ODbL. A fonte BCB_PTAX permanece bloqueada no catálogo.

## Diesel ANP — fonte semanal oficial PRIORITÁRIA encontrada

Fonte primária da metodologia:
https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-revenda-e-de-distribuicao-combustiveis/serie-historica-do-levantamento-de-precos

Arquivo oficial 2026 (página de metadados):
https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-revenda-e-de-distribuicao-combustiveis/shlp/semanal/semanal-municipios-2026.xlsx/view

Índice de versões anuais:
https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/precos-revenda-e-de-distribuicao-combustiveis/shlp/semanal/

A ANP declara que a média **municipal** de revenda é média aritmética simples.
Médias estaduais/nacionais seguem metodologias distintas (ponderações, cobertura).
A tabela semanal municipal oficial deve ser fonte principal para Sorriso, Sinop,
Rondonópolis e outros municípios efetivamente cobertos pela pesquisa.

**Correção conceitual obrigatória**: `anp_diesel.resumo_diesel_municipal`
agrupa amostras de CSV mensal em semanas domingo–sábado, algo próprio do Nivon.
Não tratar estas séries calculadas como semanas oficiais da ANP.

O arquivo XLSX de 2026 não pôde ser baixado/inspecionado por este ambiente.
Não presumir colunas, aba, unidade, download endpoint, vigência da licença nem
tratar preço de DIESEL B revenda como DIESEL A de refinaria ou PPI.

Para fechamento operacional:
1. Obter XLSX oficial por acesso permitido; preservar hash e a página de versão.
2. Documentar colunas reais, tipos, datas de início/fim oficiais, unidade R$/L,
   formato produto Diesel vs Diesel S10, municípios efetivamente amostrados.
3. **Já existe** `anp_semanal_municipios.interpretar_anp_semanal_xlsx` que usa
   `openpyxl` opcional, contrato de layout externo, semana oficial de sete dias,
   município, Diesel/Diesel S10, média e número de postos. Os testes
   `tests/test_anp_semanal_municipios.py` usam planilhas sintéticas e só executam
   com `openpyxl` disponível; não comprovam as colunas do XLSX público.
4. Homologar o layout com três amostras reais de datas diferentes antes de
   habilitar coleta/agendamento e publicação derivada.
5. Alertar município sem pesquisa e arquivo defasado, sem inventar preço.
6. Conciliar com histórico semanal agregado da própria ANP quando disponível.

## Status objetivo

| Componente | Estado |
| --- | --- |
| PTAX parser, endpoint, indicador e pipeline briefing | Implementado/testado offline |
| PTAX ODbL | Licença identificada; requisitos operacionais ainda sob revisão |
| PTAX download real + agendamento | Desabilitado |
| ANP CSV mensal postos | Parser existente, semanas inferidas documentadas |
| ANP XLSX semanal municípios 2026 | Parser genérico implementado e testes sintéticos; XLSX real e esquema ainda não homologados |
| ANP custo/mercado produtor e paridade internacional | Fora destas médias de revenda |
| Publicação e WhatsApp | Não ativados |

Nenhum número sintético dos testes pode aparecer em edição real do briefing.
