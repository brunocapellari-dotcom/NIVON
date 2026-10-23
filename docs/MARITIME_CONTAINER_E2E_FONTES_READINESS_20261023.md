# NIVON — Operação marítima offline: contêiner executado e dossiê de fontes

**Data:** 23/10/2026 · **PR:** #187 · **Estado:** `CODE_TESTED_SYNTHETIC_ONLY / REAL_SOURCE_NOT_HOMOLOGATED / RELEASE_BLOCKED`

## Entregas integradas

A imagem Docker que antes existia só como definição em código foi **construída e executada em ambiente CI**. O job `validar-pdf-maritimo-em-conteiner` usa os mesmos comandos que um operador usaria localmente, com entrada read-only, saída em pasta distinta, `--network none`, root filesystem read-only, usuário não root, limites de CPU/RAM/processos e proibição de elevar privilégios. A fase de **construção** permite baixar dependências públicas da imagem; a **execução** não usa rede.

O teste gera **três arquivos PDF binários válidos, mas sintéticos**: dois line-ups fictícios de Paranaguá com alteração de ETA e um line-up fictício de Itaqui sem DUV. Testa, em um mesmo job:

1. `dry-run` da CLI real em Docker; nenhuma tabela de edição é persistida e nenhum SQLite é criado.
2. `--commit` com atestações sintéticas de direitos explicitamente marcadas como falsas para produção; 3 edições derivadas gravadas em SQLite.
3. Novo `--commit` com os mesmos bytes/instantes; zero inserções, 3 versões já existentes.
4. Inspeção **fora do contêiner** do JSON e SQLite: uma mudança de ETA **programado**, nenhuma escala física confirmada, nenhuma tonelagem realizada, nenhum vínculo DUV canônico, nenhuma permissão de divulgação.

O artefato é aprovado como **execução CI em contêiner**, não como operação em nuvem. A imagem não é publicada, implantada em Google Cloud nem testada contra documentos oficiais reais.

## Quadro de prontidão incorporado ao JSON

`src/nivon/maritime/pdf_source_dossier.py` foi ligado à saída padrão do comando `scripts/maritime_pdf_batch.py`, sem exigir um segundo comando e sem introduzir banco adicional.

Cada item `source_readiness[]` pertence a uma fonte e série documental específicas e contém:

- Edições fornecidas, edições com publicação e coleta efetivamente conhecidas no corte `as_of`, hashes distintos e instantes de coleta independentes.
- Mínimo **3 edições distintas** para revisão de estrutura e temporalidade; recapturar o mesmo PDF 3 vezes **não** satisfaz esse mínimo.
- Linhas com Nº Prog, ocorrências de DUV **expressamente declarado**, linhas excluídas como escala por identidade/ETA insuficiente.
- Bloqueios explícitos de autenticação do publicador, verificação de direitos, revisão visual de páginas e controle de publicação.
- Separação de referência de programação versus port call: `confirmed_port_call_count=null`, `realized_tonnes=null`, `release_allowed=false`, `verified_rights_from_software=false` sempre.

Um conjunto com três documentos distintos pode atender o **mínimo quantitativo de amostras**, mas o dossiê **permanece** `NOT_HOMOLOGATED_EXTERNAL_REVIEW_REQUIRED`; o programa não confere direitos nem emite parecer legal. Edições futuras ou sem publicação comprovada não contam como conhecidas no passado.

### Resultado factual do cenário sintético

| Fonte de teste | Documentos conhecidos no corte | Contagem mínima para revisão | DUV comprovado? | Estado |
| --- | ---: | ---: | --- | --- |
| Paranaguá / corredor oeste | 2 | 3 | Não | Bloqueado |
| Itaqui / programação PDF | 1 | 3 | Não | Bloqueado |

Estes **não são números operacionais reais**, nem documentos fornecidos pelas autoridades. O teste só demonstra que o NIVON é capaz de identificar as pendências corretamente.

## Critérios externos de homologação

Para Paranaguá e Itaqui, antes de coleta agendada, armazenamento operacional ou publicação:

1. **Direitos e contrato:** obter confirmação da fonte quanto a consulta, retenção, análise interna, geração de derivado e redistribuição — cada operação em seu próprio escopo. URL HTTPS e indicação de direitos pelo operador não são licença suficiente.
2. **Arquivos originais:** no mínimo 3 edições independentes **por fonte e série**. Guardar originais sob autorização; registrar URL exata, bytes/hash, captura, publicação provada, competência e referência.
3. **Revisão de layout:** conferir PDF contra extração por página (colunas, cabeçalhos, relógios, mudanças de layout, múltiplos produtos e páginas escaneadas). Não presumir que os PDFs disponíveis possuem coluna DUV.
4. **Identidade e operação:** tratar Nº Prog como referência de programação, não DUV. Se os documentos não fornecem um par oficial Nº Prog–DUV, manter as entidades separadas. Programação não prova atracação, saída ou carga efetivamente embarcada.
5. **Segurança:** homologar a imagem por **digest fixo** e dependências verificadas, auditar CVEs/seccomp/AppArmor e políticas do host, testar backup/restore e fluxo shadow. A execução da CI não prova segurança de produção.
6. **Aceite:** relatório independente com divergências, acesso autorizado, plano de reversão e aprovação humana para eventual implantação e divulgação.

Este pacote **não** altera os coletores de Santarém/Vila do Conde, Itacoatiara/Amaggi, Suape, Imbituba e Ponta da Madeira. Os últimos permanecem no escopo do NIVON mas necessitam testes próprios de fonte e de identidade, especialmente quando o line-up é inferido via AIS.

## Rastreabilidade

- `.github/workflows/testes.yml`: job Docker construído e executado, sem push, com execução estritamente offline.
- `tests/maritime_container_smoke.py`: gerador de PDFs genuinamente binários sintéticos, verificação de três relatórios e SQLite.
- `src/nivon/maritime/pdf_source_dossier.py`: bloco de prontidão por fonte/série na saída JSON.
- `src/nivon/maritime/offline_pdf_batch.py`: integra o bloco de prontidão ao relatório principal.
- `tests/test_maritime_offline_batch.py`: confere 3 edições distintas, hashes reciclados, DUV ausente e cortes temporais.
- A CI deve estar **verde no commit final** antes de considerar validada a documentação. Os logs da primeira execução bem-sucedida do contêiner estão no [GitHub Actions 39983437818](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/39983437818).

**Não ativado:** agendamento, aquisição de fontes, banco Google Cloud, serviços pagos, extração de AIS real, publicação, merge ou deploy.
