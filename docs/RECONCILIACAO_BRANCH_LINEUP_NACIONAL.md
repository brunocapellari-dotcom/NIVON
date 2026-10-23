# Reconciliação das duas branches do Nivon — 19/10/2026

## Situação observada

- Branch principal de desenvolvimento: feat/nucleo-motores-v0-1-20261016, PR #1 aberto, agora com 28 frentes e registro de motores.
- Branch paralela: feat/integracoes-lineup-nacional-20261019, divergente do PR #1.
- A branch paralela possui uma configuração de 126 datasets e 45 entradas LINEUP_* de portos/complexos nacionais (incluindo escopo adicional) a partir de base anterior com 90 datasets; PR #1 tem 94 datasets e configuração de dez portos. Esses totais **não são somáveis**, porque versões divergem e datasets se sobrepõem.
- Nenhuma das branches constitui, isoladamente, homologação de coleta recorrente ou deploy.

## Reaproveitamento identificado na branch paralela

| Componente | Valor para o Nivon | Verificação antes de integrar ao PR #1 |
|---|---|---|
| lineup_nacional.py | Identidade de escala, estado, evidência e produtos por 45 portos/complexos | Reconciliar escopo/aliases/contratos com portos.py e lineup_html.py; não confundir programação com embarque |
| anp_ppi.py | Planilha ANP de preço de paridade/importação com localidade e data | Validar XLSX, direitos de dados S&P derivados, datas e base tributária; nunca igualar diesel PPI à revenda |
| fertilizantes.py | Classificação de NCMs de ureia/MAP/DAP/KCl e consolidação MDIC | Checar NCM por vigência e forma do produto e evitar códigos fixos sem revisão |
| cotacoes_externas.py | Preço de mercado com unidade, competência e direitos | Verificar licença de CME/ICE/B3, disponibilidade e publicação/redistribuição |
| eventos_editoriais.py | Deduplicação conservadora entre portais | Calibrar falsas fusões em notícia/evento; não alterar data de publicação |
| entrega_whatsapp.py | Contrato de template e opt-in para saída | WhatsApp AI é independente; entrega autorizada, sem mensagem automática nesta etapa |

## Sequência de reconciliação

1. Mapear arquivos e schemas conflitantes, preservar a matriz das 28 frentes e suas funções.
2. Trazer módulos puros/testes que não dependam de licenças não aprovadas; nunca sobrescrever código mais recente sem auditoria.
3. Unificar manifestos de portos, fontes e datasets por IDs canônicos, com aliases e cobertura marítima verificável.
4. Reexecutar testes de ambas as branches e testes cruzados de briefing (notícia <=24 h, preço datado, linha de navios, fertilizantes, envio WhatsApp).
5. Homologar fontes por operação e histórico; manter agendamento, redistribuição e envio desativados.
6. Só após revisão independente considerar uma incorporação ao PR #1. **Nenhum merge para main ou deploy está autorizado nesta execução.**

## Limite

A relação de funções em config/motores_inteligencia.v1.json prova existência de código na branch do PR #1, não prova integração da branch de line-up, disponibilidade real de dados ou capacidade preditiva validada.
