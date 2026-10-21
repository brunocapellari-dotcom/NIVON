# NIVON — Briefing de ponta a ponta em modo de homologação

Data-base: 20/10/2026. PR #8 — https://github.com/brunocapellari-dotcom/NIVON/pull/8

## Fluxo concluído em código (somente offline)

1. O coletor web aceita RSS/Atom `XML` somente com `FonteWeb` autorizada.
2. `rss_radar.ler_feed_xml` identifica artigos com URL HTTPS, publicação original
   com hora/fuso e sem DTD; `updated` não renova publicação antiga.
3. `historico_noticias.registrar_observacoes` grava hash de GUID/URL e menor
   data de publicação observada na memória SQLite; conteúdo integral não é salvo.
4. `curadoria_radar.preparar_noticias_feed` exige política com direitos de
   coleta/armazenamento/resumo/publicação e aprovação editorial vinculada
   a SHA-256 do título+URL+publicação do documento. Não transforma o resumo
   bruto do feed em notícia liberada.
5. `briefing_diario.selecionar_noticias` aplica janela móvel de 24 horas e
   deduplicação conservadora entre fontes, preservando `fonte_id` para permitir
   validação nas fases subsequentes.
6. `pipeline_briefing.gerar_edicao_offline` agrega feeds curados, indicadores
   autorizados, fretes anunciados e quadro portuário homologado. Se a licença
   ou atualidade do line-up falhar, o porto não aparece como "zero navios".
7. `scripts/gerar_briefing_offline.py` produz o texto WhatsApp e auditoria
   JSON por gravação atômica. Não envia mensagens nem agenda jobs.
8. `outbox_whatsapp` prepara o suporte de idempotência, mas somente com
   opt-in, template, token, custo autorizado e provedor conectado poderá
   integrar uma remessa real.

## Comando de homologação (arquivos locais)

```sh
PYTHONPATH=src python scripts/gerar_briefing_offline.py \
  --manifesto entradas/edicao.json \
  --banco dados/radar.sqlite \
  --saida saida/briefing.txt \
  --auditoria saida/briefing.auditoria.json
```

O diretório do manifesto deve conter os arquivos XML referenciados
por `arquivo_xml` (caminhos relativos, sem traversal e sem symlink).
Os diretórios do banco e dos arquivos de saída devem existir previamente.
Os scripts e testes não instalam dependências externas.

Estrutura mínima de `edicao.json` (EXEMPLO NÃO AUTORIZA FONTE REAL):

```json
{
  "gerado_em": "2026-10-20T09:00:00-03:00",
  "feeds": [
    {
      "fonte_id": "EXEMPLO_SINTETICO",
      "arquivo_xml": "fonte_teste.xml",
      "url_feed": "https://exemplo.invalid/rss",
      "dominios_artigos": ["exemplo.invalid"],
      "coletado_em": "2026-10-20T08:30:00-03:00",
      "politica": {
        "fonte_id": "EXEMPLO_SINTETICO",
        "nome": "Fonte de teste",
        "status_direitos": "PENDENTE",
        "operacoes": [],
        "licenca_id": null
      },
      "avaliacoes": {}
    }
  ],
  "indicadores": [],
  "fontes_indicadores": {},
  "fretes": []
}
```

**A configuração ilustrativa acima falha por direitos PENDENTES, como deve acontecer.**
Para teste positivo, veja `tests/test_gerar_briefing_offline_cli.py`, que
usa fontes/credenciais meramente sintéticas. Nunca marcar fontes reais como
aprovadas sem evidência legal e governança.

## Fontes institucionais identificadas, não homologadas

A rota `RADAR_GOV` inclui candidatos, sem habilitação automática:

- CONAB notícias: https://www.gov.br/conab/pt-br/comunicacao-institucional/sala-de-imprensa/noticias
- ANTAQ notícias: https://www.gov.br/antaq/pt-br/noticias
- MAPA-SDA: https://www.gov.br/agricultura/pt-br/assuntos/defesa-agropecuaria/plataforma-sda/comunicados-sda/assine-o-feed-1
- O MAPA-SDA referencia um feed em `rss.app`, um serviço terceiro;
  origem, licença, condições de acesso e persistência não foram homologadas.

Índice HTML com data no artigo não é automaticamente um RSS com timestamp
de publicação original. A data de modificação da página principal tampouco
prova notícia recente. Notícias do briefing requerem no máximo 24h.

## Bloqueios de operação real

- Coleta incremental e histórico real das fontes só após autorização e
  validação de três snapshots, com evidência e monitoramento de qualidade.
- **Curadoria automática de IA:** ainda exige serviço/modelo conectado,
  políticas de conteúdo, avaliação factual e aprovação auditável dos resumos;
  este fluxo aceita apenas curadorias previamente aprovadas.
- Definição da infraestrutura nuvem, SQLite durável ou banco central e backup
  restaurado, proteção de segredos e observabilidade.
- Meta Business (destinatários com opt-in, template autorizado, credenciais,
  webhook e custo aprovado).
- Preços CME/ICE, fertilizantes CFR e várias programações portuárias permanecem
  com restrições de acesso, licença ou ausência de dados atuais.

Não confundir **suíte sintética aprovada** com homologaçao de dados reais
ou go-live.
