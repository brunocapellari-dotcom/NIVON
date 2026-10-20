# ANP diesel municipal — pipeline, governança e briefing

Data: 20/10/2026. Implementação proposta no PR #3, SEM homologação externa.

## O que funciona em modo offline

1. `anp_diesel.resumo_diesel_municipal` interpreta CSV ANP mensal
   (fonte já adquirida legitimamente) e agrega preço de revenda por
   UF, município, DIESEL ou DIESEL S10 e semana calendário derivada.
2. `anp_diesel_store.gravar_resumo_diesel` persiste somente agregados
   municipais, sem CNPJ, nome do posto, endereço, CEP ou identificador.
   Preserva SHA-256 do arquivo de origem e novas datas de coleta.
3. `anp_diesel_store.indicador_diesel_municipal` seleciona a versão
   observável no corte, para município e produto explicitamente pedidos.
   Ignora snapshots sintéticos e bloqueia valores antigos, conflitos
   entre vintages e ausência de direitos de publicação derivada.
4. `compor_pacote_historico`, CLI de ensaio (`--db-diesel`) e
   `NivonProjectAdapter.query('briefing.preview')` já possuem a ligação
   opcional de DIESEL ao briefing; nenhuma rede ou envio é ativado.

## Semântica obrigatória

- ANP: preço MÉDIO AMOSTRAL de revenda R$/L, não média ponderada por volume.
- Não é preço de importação, preço da Petrobras, atacado ou paridade internacional.
- DIESEL não é DIESEL S10: relatórios mostram cada produto separadamente.
- Semana domingo-sábado é DERIVADA das datas individuais do CSV,
  não necessariamente o mesmo período do relatório semanal oficial da ANP.
- A data no campo `referencia` do briefing é a captura do documento;
  a semana derivada aparece explicitamente no conteúdo.
- A data exata de publicação permanece desconhecida nesse adaptador:
  NÃO habilitar backtest com corte por publicação sem obter prova.
- Revisões conflitantes de uma semana local não são escolhidas
  silenciosamente, mesmo quando uma captura é mais recente.
- Se o município não estiver na amostra ANP, o indicador é AUSENTE,
  nunca zero. Frequência de publicação não garante pesquisa em todos os municípios.

## Requisitos pendentes para operação real

- Resolver o URL específico do arquivo mensal a partir da fonte oficial,
  confirmar condições legais de coleta, armazenamento e publicação derivada.
- Validar pelo menos três arquivos reais distintos com prova de bytes,
  SHA-256, datas, unidade, schema, contagem e cobertura municipal.
- Registrar evidência dos direitos e vincular o fluxo a um executor
  persistente somente após homologação; `direitos_confirmados=True` não
  configura sozinho uma licença ou autorização.
- A infraestrutura precisa executar coleta incremental, recuperar falhas,
  registrar logs sem PII e monitorar variação de schema/defasagem.
- Só habilitar envio WhatsApp com opt-in, provedor, preço e template aprovados.
- Para memória de paridade PPI diesel, manter motor INDEPENDENTE com
  câmbio, diesel internacional, frete, tributos, mistura obrigatória,
  especificação do produto e conversões físicas auditadas.

## Segurança e custo

Nenhuma coleta real, deploy, aquisição, cobrança ou envio é feita por esses
módulos. Os dados de teste são sintéticos. O histórico deve estar em volume
durável separado de workers efêmeros e ter backup/restauração testados.
