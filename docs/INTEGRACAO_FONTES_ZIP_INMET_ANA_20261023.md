# NIVON — Entrega de fonte até acervo meteorológico/hidrológico
**Data de referência:** 23/10/2026. **Base científica:** integrações #68, #81, #89, #116, #129, #152, #191 e #214. **Estado:** testes de integração com dados sintéticos e transportes simulados, SEM produção.

## Priorização de execução e critérios

| Ordem | Capacidade integrada | Critério verificável | Estado |
|---|---|---|---|
| P0 | RONI histórico retrospectivo | Parser + RAW/SQLite + revisão + as-of local + CLI + backup íntegro | Testado CI (#152) |
| P0 | INMET CSV horário + ANA adotada JSON | Dados originais separados por estação/instante/QC, RAW imutável, SQLite, consulta, backup | Testado CI (#191) |
| P0 | ZIP INMET completo | ZIP original verificado e guardado por SHA, membro escolhido e auditado, dedup ZIP de várias estações | Testado nesta PR |
| P0 | ANA SSO adotada no pipeline | Reusar cliente SSO, normalização QC e suporte temporal; fake transport somente em teste | Testado nesta PR |
| P0 | Recaptura, revisão e recuperação | Mesmo CSV em ZIP diferente ou nova captura; origem preservada, nenhum dado duplicado | Testado nesta PR |
| P0 | Auditoria e backup de origem | ZIP integral+CSV+SQLite, CRC, hashes e teste de alteração/restore | Testado nesta PR |
| P0 | Registro e governança | Módulos permitidos, fontes reais e motores OFF | Testado CI |
| P1 | Fonte oficial INMET com ZIP real e licença comprovada | Evidência de origem, captura/versão/controles externos e QC da estação | Pendente |
| P1 | Telemetria ANA autenticada, com credencial segura | SSO real autorizado, metadados de fuso, janela e sensor, armazenamento controlado | Pendente |
| P1 | Integração canônica da cadeia científica | Consolidar no integrador #13 uma única vez, evitar PRs duplicadas | PR draft de consolidação, sem merge |
| P1 | Persistência e coleta no Google Cloud | Binding Cloud Storage/banco compatível, credenciais, direitos e custos aprovados | Não implantado |
| P2 | Agregados úteis e modelos reais | Janelas físicas/representatividade, observações reais, treino OOS | Ainda sem homologação |

## Fluxo integrado entregue

### INMET — entrada ZIP anual, com origem retida

`inmet_historico.inspecionar_arquivo` rejeita ZIP inseguro (traversal, links, arquivos cifrados/CRC, razão/tamanho), `obter_csv_em_memoria` extrai somente o CSV explicitamente selecionado e `inmet_horario_qc.extrair_horarios_inmet` confere WMO, ano, cabeçalho, horárias e limites físicos.

`fontes_hidro_entrada.preparar_inmet_zip_local` cria uma edição de acervo, com SHA-256 do ZIP pai e do CSV selecionado. **O preparo sozinho NÃO representa arquivo arquivado.** O pipeline `importar_ciclo_medicoes` copia o ZIP original por streaming para `raw/origens/<SHA>.zip`, preserva o CSV original em `raw/<SHA>.raw` e registra a relação `medidas_containers_origem` dentro da transação SQLite. A auditoria `auditar_acervo_medicoes` relê e valida ZIP, CSV, CRC, WMO, medição e banco. O backup inclui ZIPs integrais e CSVs, deduplicando o mesmo ZIP entre estações.

Arquivo ZIP baixado hoje não prova quais dados estavam disponíveis na data histórica da medição. A validação comprovada aqui é integridade **interna do acervo**, não autenticação HTTP institucional.

### ANA — cliente SSO existente até o mesmo acervo

`fontes_hidro_entrada.preparar_ana_consulta_adotada` cria `construir_consulta_adotada` com token passado em memória e usa `efetuar_request` do HidroWebService atual. **Somente testes com `simular=true` e transporte injetado** executam sem aprovação. Chamadas de rede sem transporte simulado consultam o catálogo canônico `ANA_HIDRO` e falham enquanto `enabled=false`, `collection_authorized=false` ou o status não é homologado. Tokens, senhas ou Authorization não entram no SQLite, no manifesto ou no relatório.

`normalizar_adotada` preserva cota, vazão e chuva intervalar e seus estados QC tal como enviados pela ANA, com o fuso da estação explicitamente informado. Valores de vazão/cota instantâneos **não podem** virar médias diárias, e chuva intervalar sem duração/limites medidos confirmados não pode virar dia civil.

### Manifesto ZIP+ANA pelo comando local

O manifesto `schema=1.0`, `projeto=NIVON`, `lotes` agora admite, além de `INMET_HORARIO_CSV` e `ANA_ADOTADA_JSON`, a forma:
```json
{
 "arquivo":"2025.zip",
 "formato":"INMET_ANUAL_ZIP",
 "estacao_id":"A904",
 "ano":2025,
 "zona":null,
 "coletado_em":"2026-10-23T12:00:00Z",
 "classe":"EXTERNO_NAO_HOMOLOGADO",
 "membro_csv":"CAMINHO_SEGURO_DO_MEMBRO.csv"
}
```
*Acima é um exemplo de contrato, não um arquivo realmente obtido.* O ZIP deve existir ao lado do manifesto; o membro escolhido precisa pertencer ao inventário verificado da fonte e ter metadado WMO compatível.

```bash
PYTHONPATH=src python -m nivon.pipeline_medicoes_cli validar --manifesto lotes.json
PYTHONPATH=src python -m nivon.pipeline_medicoes_cli executar --manifesto lotes.json --banco medicoes.sqlite --raw-dir raw --confirmar-gravacao
PYTHONPATH=src python -m nivon.pipeline_medicoes_cli auditar --banco medicoes.sqlite --raw-dir raw
PYTHONPATH=src python -m nivon.pipeline_medicoes_cli backup --banco medicoes.sqlite --raw-dir raw --destino-backup backup_01
PYTHONPATH=src python -m nivon.pipeline_medicoes_cli validar-backup --destino-backup backup_01
```

A cópia RAW+SQLite é consistente em operação **sem escritores concorrentes**. Uma interrupção brusca do processo entre a gravação de arquivo e commit SQLite pode deixar um arquivo órfão, que é detectado na auditoria; diretório RAW dedicado e serialização de escritores continuam obrigatórios. A integração no Cloud Storage com duas-fases será tratada separadamente.

## Testes: cobertura que importa

- ZIP anual seguro → inventário → WMO → 24 horas e temperatura/chuva do CSV → versão no banco.
- SHA do ZIP pai, ZIP original gravado e referenciado, recaptura do mesmo CSV em ZIP diferente, replay idempotente e múltiplas fontes no acervo.
- Telemetria ANA com token **somente em memória** e transporte fake, QC suspeito preservado, fluxo real desativado.
- ZIP traversal e WMO incompatível bloqueados antes de gravar; corrupção do ZIP arquivado detectada mesmo com CSV intacto.
- Backup carrega ZIP integral, CSV e SQLite; adulterar ZIP no backup invalida restauração.
- Chuva INMET não é chuva diária homologada; cota/vazão da ANA não são médias diárias; vintages externos e habilidade preditiva não são comprovados.

## Dependências externas e go-live

1. Validar direitos de coleta, retenção e eventual redistribuição dos arquivos, por fonte e operação; não ativar cron só por haver URL/token.
2. Homologar a primeira amostra **real, originária e imutavelmente arquivada** de INMET e ANA com todas as datas (competência, referência, publicação e coleta).
3. Provar metadados físicos dos intervalos meteorológicos e hidrológicos, convenção temporal, mudanças de estação, QC e versões.
4. Especificar o armazenamento permanente no **Google Cloud já aprovado como opção de infraestrutura**, com custo zero/mínimo verificável, sem ativar faturamento sem autorização.
5. Validar integração da cadeia em uma PR de consolidação **draft** contra #13; merges em `main` ficam separados.

**Nunca rotular testes em transporte falso como coleta real, nem equiparar consistência de RAW e SQLite a skill preditiva.**
