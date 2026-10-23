# NIVON — Plano de entregas integradas e pipeline NOAA RONI
**Data:** 22/10/2026. **Escopo:** frente de Meteorologia e Hidrologia; não aciona a holding, outras frentes, clientes ou Cloud.

## Fila priorizada de execução — sem comandos por teste

| Prioridade | Entrega operacional de código | Critério de aceite / teste integrado | Estado neste lote |
|---|---|---|---|
| P0 | Arquivar RONI em RAW imutável + SQLite | Arquivo → parser → SHA → DB → restart → leitura | Implementado |
| P0 | Reconhecer alterações da NOAA sem substituir histórico | Primeira versão, nova competência, revisão, replay idempotente, retorno a edição anterior | Implementado |
| P0 | Fixar data real da primeira observação NIVON | Captura atual não reconstitui publicação antiga; impedir clock real injetado | Implementado |
| P0 | Operação local por manifesto e um comando | Preflight de lote inteiro, importação, dedup, métricas e saída JSON | Implementado |
| P0 | Verificar backup e integridade do acervo persistido | SQLite backup/restore, comparação valor-a-valor com RAW e SHA | Implementado |
| P1 | Captura pontual HTTPS sob permissão explícita | GET restrito ao recurso NOAA, limite 120 KB, sem redirect, 200/MIME, cache | Implementado com transporte falso; produção OFF |
| P1 | Registrar NOAA RONI no catálogo e contrato de fonte | Catálogo ↔ rota ↔ parser ↔ banco, sem agendamento | Implementado em PR #89 |
| P1 | Receber amostra RAW integral oficial com procedência | Um download real, SHA e headers, sem histórico inventado | Bloqueio externo: acesso HTTP/DNS |
| P1 | Homologar direitos por operação, atribuição e histórico | Evidência externa verificável por dataset | Pendente |
| P1 | Reconciliar #68→#81→#89→#116→esta PR | Merge coordenado sem reaplicar originais #9/#11 | Pendente da integração central |
| P2 | Programação econômica de coleta após persistência homologada | Atualizar apenas se houver mudança, restore testado, alertas sobre SOURCE_LAG | Planejado, não agendado |
| P2 | Calibração espacial e validação meteorológica real | INMET/NASA/NWP/ENSO/MJO com vintages, métricas OOS e QC | Pendente dos dados oficiais |

**Política de lotes:** executar e testar todas as etapas reversíveis e locais da entrega juntas, abrir apenas uma PR filha por unidade funcional e exigir CI completa no commit final; não abrir uma nova PR para cada teste. Não registrar alterações concluídas sem evidência.

## Entrega técnica nesta PR

- `src/nivon/roni_store.py`: `abrir_arquivo_roni`, `executar_lote_roni`, `consultar_arquivo_roni`, `panorama_local_roni`, `auditar_acervo_roni`. O arquivo é indexado por SHA-256 e escrito em modo local, sem sobrescrita; os valores mensais/temporadas ficam em SQLite com chaves por edição.
- `src/nivon/roni_cli.py`: lotes de até 50 arquivos ASCII e preflight completo, comando de persistência explícita, leitura resumida, captura HTTPS autorizada e auditoria. O manifesto não pode referenciar caminho fora do seu diretório ou symlink.
- `src/nivon/roni_captura_manual.py`: no máximo **um HTTPS GET** para o URL RONI oficial por execução após autorizar coleta/armazenamento; MIME e URL sem redirecionamento, cache e captura de hash/cabeçalhos. O teste de transporte é simulado; **nenhum HTTP real foi executado**.
- `tests/test_pipeline_roni_e2e.py` e `tests/test_roni_captura_e2e.py` cobrem a cadeia inteira, incluindo subprocesso CLI, backup/restauração e detecção de corrupção. Rodar em CI sem serviços pagos nem credenciais.

## Exemplo de manifesto local

Coloque o arquivo `lotes.json` no **mesmo diretório** dos arquivos ASCII autorizados. Para registros sintéticos, usar `classe=SINTETICO`; para um arquivo realmente recebido por canal autorizado, usar `classe=EXTERNO_NAO_HOMOLOGADO`.

```json
{
  "schema_version": "1.0",
  "project": "NIVON",
  "lotes": [
    {
      "arquivo": "roni_captura_01.ascii",
      "coletado_em": "2026-10-22T12:00:00Z",
      "classe": "EXTERNO_NAO_HOMOLOGADO"
    }
  ]
}
```

Os arquivos de exemplo precisam existir no diretório; o código **não gera nem baixa dados reais automaticamente**.

```bash
PYTHONPATH=src python -m nivon.roni_cli validar --manifesto lotes.json
PYTHONPATH=src python -m nivon.roni_cli executar --manifesto lotes.json --banco roni.sqlite --raw-dir arquivo_raw --confirmar-gravacao-local
PYTHONPATH=src python -m nivon.roni_cli auditar --banco roni.sqlite --raw-dir arquivo_raw
```

Captura real **somente depois de comprovar os direitos de coleta e armazenamento**:

```bash
PYTHONPATH=src python -m nivon.roni_cli capturar --banco roni.sqlite --raw-dir arquivo_raw --confirmar-gravacao-local --autorizar-http --direitos-fonte REFERENCIA_DA_AUTORIZACAO
```

Uma nova visita intencional para verificar revisão requer `--confirmar-revisao`. Não incluir segredos no comando nem no manifesto. Esta interface **não cria agendamento**.

## Segurança, limitações e evidências

- Fonte canônica: `https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt`, registro `NOAA_ENSO_RONI` do catálogo mestre.
- O arquivo RAW guardado por hash e o SQLite devem ser **copiados e restaurados juntos**, preferencialmente com backup criptografado e acessível apenas ao operador. Uma cópia parcial deve reprovar `auditar`.
- A data de primeira observação pelo NIVON é **o instante em que o processo registrou os bytes**. Um campo `coletado_em` informado no manifesto não antecipa esse instante para dados externos. Um RAW arquivado agora NÃO é uma série histórica de publicações NOAA conhecidas na época.
- O classificador RONI produz episódios retrospectivos com cinco temporadas de três meses sobrepostos. Não converte o RONI em probabilidade municipal, skill meteorológica, previsão de safra ou desvio de chuva; não mesclar diretamente com índice MJO/RMM.
- Registro real sem direitos específicos e publicação individual auditada continua `homologado=false`, `pode_treinar_asof=false` e `pode_agendar=false`. Arquivos provenientes de transporte falso recebem a mesma classificação.
- Se o recurso público mudar estrutura, falhar DNS/TLS/MIME, exceder tamanho ou truncar competências, o ciclo termina bloqueado; não inferir zeros e não substituir o arquivo antigo.
- Auditoria técnica detecta adulterações de RAW/SQLite, mas **não** fornece certificação de origem institucional, aprovação de licença ou versionamento externo.

## Próximo lote sem dependência de comandos unitários

1. Conferir o CI completo no HEAD final e corrigir todas as falhas na mesma PR.
2. Conferir o plano por módulos/registro e auditoria global, manter URL permitida e OFF.
3. Executar inspeção real pontual apenas quando a rede/fonte estiverem acessíveis e os direitos por operação puderem ser demonstrados; preservar o RAW no armazenamento privado, não no repositório.
4. Coordenar aceitação do integrador central e não realizar merges redundantes de PRs empilhadas.
5. Depois da fonte homologada, ligar atualização incremental com armazenamento durável ao agendador escolhido, sem contratar serviços pagos sem autorização.
