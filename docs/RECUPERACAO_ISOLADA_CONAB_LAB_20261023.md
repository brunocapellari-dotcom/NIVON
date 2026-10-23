# NIVON — Recuperação isolada e reconciliação de snapshots CONAB (LAB)

**Data:** 23/10/2026 · Frente: Coletores e Engenharia de Dados · PR #216, empilhada sobre PR #189.

## Objetivo operacional

Concluir um lote completo de **verificação de backup, restauração em ambiente novo, reconciliação com histórico e checagem bitemporal por data de coleta**, sem tocar no banco original, no banco canônico do NIVON ou na infraestrutura Google Cloud.

Os dados de teste são **exclusivamente históricos de terceiro (agrobr)** e as duas retificações são **artificiais**, derivadas de alterações do XML OOXML. Nenhuma série verdadeira da CONAB foi retificada, migrada ou distribuída.

## Entrega implementada

`src/nivon/recuperacao_isolada_conab_lab.py`:

1. Exige **caminho absoluto e privado** do backup SQLite LAB; aceita apenas o nome de arquivo compatível `conab-lab-seq-NNNN.sqlite` ou `conab-retif-seq-NNNN.sqlite`, sem symlink e com tamanho controlado.
2. Recebe um **SHA-256 esperado, fornecido fora do próprio arquivo de backup**. Recusa se divergir. Essa conferência vincula a restauração à evidência informada, mas **não constitui assinatura digital nem cadeia de custódia independente**.
3. Reabre a cópia em **modo somente leitura**, executa `PRAGMA integrity_check`, `foreign_key_check`, hashes semânticos, identificação das referências no catálogo e auditoria da cadeia das revisões, quando existente.
4. Restaura via API SQLite `Connection.backup` em arquivo **novo `0600`** dentro de pasta **vazia e privada `0700`**. Não sobrescreve nem apaga backup ou banco fonte.
5. Reabre e audita o restaurado; exige igualdade lógica entre origem e resultado, não apenas integridade do arquivo.
6. Opcionalmente abre o **banco LAB vivo** em leitura e identifica divergências frente ao snapshot antigo (quantidade de referências, revisões, observações, fingerprints semânticos e versões em cortes históricos).
7. Escreve `recuperacao-evidencia-lab.json` no mesmo diretório, com SHA da cópia restaurada, detalhes de verificação e resultados da reconciliação, além de todos os gates **NO-GO**.
8. Se a auditoria ou escrita falhar, exclui exclusivamente arquivos parciais criados no diretório de recuperação, preservando origem e evidências pré-existentes.

Exemplo de uso **somente em LAB**:

```sh
mkdir -m 700 /dados/privados/conab-recuperacao-001
PYTHONPATH=src python -m nivon.recuperacao_isolada_conab_lab \
  --backup /dados/privados/conab-backups/conab-retif-seq-0002.sqlite \
  --sha256-esperado SHA256_OBTIDO_DO_LOG_AUDITADO \
  --catalogo config/conab_referencias_multivintage_20261021.json \
  --destino /dados/privados/conab-recuperacao-001 \
  --banco-vivo /dados/privados/conab-lab.sqlite \
  --corte-coleta 2026-10-23T15:01:30Z \
  --corte-coleta 2026-10-23T15:02:30Z
```

O comando é demonstrativo. Não executar contra arquivos de produção. Para simulação de revisões, usar catálogo LAB apropriado ao respectivo ensaio; **não declarar o manifesto de outubro como arquivo de revisão real**.

## Testes integrados de recuperação

O script `scripts/validar_retificacoes_conab_ci.py` foi ampliado. Após os cinco processos de carga inicial e duas revisões artificiais, executa restaurações independentes dos **três pontos do histórico**:

| Snapshot | Observações da versão original | Observações de revisão | Revisões | Igual ao banco atual |
|---|---:|---:|---:|---|
| Base | 11 | 0 | 0 | Não |
| Após revisão 1 | 11 | 11 | 1 | Não |
| Após revisão 2 | 11 | 22 | 2 | Sim |

Também testa recuperação do último snapshot com o banco vivo não disponível. Os cortes as-of devem mostrar versão 0/1/2 de acordo com o momento de captura, sem *look-ahead bias*.

A regressão unitária cobre: arquivo SHA divergente/adulterado, backup semanticamente inconsistente mesmo após recalcular o SHA, diretório inseguro, symlink, restauração em pasta não vazia, catálogo contraditório, cortes sem fuso e preservação dos arquivos originais.

O trabalho evita comandos unitários do usuário: **um job de integração exercita o fluxo completo; a suíte geral é executada no mesmo PR**.

## Avaliação dos limites

- **Cópia SQLite em disco do runner** ≠ backup durável em Google Cloud, com retenção, versionamento, acesso restringido e teste de restauração entre projetos/ambientes.
- **SHA conhecido** ≠ prova de autoria da CONAB. O arquivo inicial é do agrobr e as retificações são sintéticas.
- **Reconciliação com banco vivo LAB** ≠ reconciliação com banco transacional canônico Google Cloud; nenhuma credencial ou conexão produtiva foi usada.
- Consultas as-of por coleta ≠ validação da data de publicação ou disponibilidade histórica no portal.
- Migração, publicação, distribuição externa e implantação de serviço continuam bloqueadas.

## Próximo lote recomendado

P0 — Homologar coleta direta do XLSX com evidência verificável, permissão de uso por operação, data de publicação e direitos de armazenamento. P1 — Integrar esquema de revisões aprovado a um ambiente de testes do armazenamento definitivo, com snapshots versionados e restauração isolada, sem credenciais reais no CI. P1 — Planejar transmissão segura de snapshots para armazenamento em nuvem somente depois da análise de acesso, retenção, custos e configuração aprovada. P2 — Consolidar PRs empilhadas após revisão de arquitetura e testes ponta a ponta.

**Gates:** `origem_conab_direta_autenticada=false`, `direitos_de_uso_homologados=false`, `banco_canonico_modificado=false`, `banco_de_producao_modificado=false`, `migracao_permitida=false`, `publicacao_permitida=false`.
