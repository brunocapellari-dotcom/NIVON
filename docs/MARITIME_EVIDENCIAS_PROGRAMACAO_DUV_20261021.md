# NIVON — Dossiê de evidência Nº Prog → DUV (21/10/2026)

**Estado:** controle técnico offline, sem dados oficiais homologados; **0 vínculos reais comprovados**, sem promoção para port calls, sem scrape, sem merge/deploy.

## Informação pública e limites

- [Portos do Paraná — exemplo oficial de line-up (16/10/2026)](https://www.portosdoparana.pr.gov.br/Arquivo/LINE-CORREDOR-OESTE-16102026): a página lista uma edição de line-up; o carimbo geral de publicação de CMS não deve ser aceito como data comprovada de publicação do PDF.
- [Governo Federal — programação para atracação](https://www.gov.br/pt-br/servicos/programar-navios-para-atracar-e-desatracar-no-porto-de-itaguai): indica o **DUV no Porto Sem Papel como formalização de escala de navio**. Não afirma que o **Nº Prog** do corredor de Paranaguá corresponda automaticamente ao DUV.
- [Portos do Rio — carta de serviços](https://www.portosrio.gov.br/sites/default/files/2025-files/carta_de_servicos_companhia_docas_do_rio_de_janeiro_2025.pdf): descreve a criação do DUV e sua relação com a estadia de embarcação. É orientação sobre DUV, não um serviço público de crosswalk Nº Prog–DUV.
- [Receita Federal — serviços de controle de carga](https://www.gov.br/receitafederal/pt-br/assuntos/aduana/carga/carga/): operações aduaneiras de atracação/saída possuem fontes/controles específicos. Dados de programação NÃO comprovam realização.

**Conclusão de escopo:** nenhuma destas páginas constitui fonte oficial atual e auditada contendo pares específicos `(porto, fonte, corredor, Nº Prog, data de referência) → DUV`. Não foi obtida permissão de consulta/guarda do Porto Sem Papel ou de extração de pares de sistemas restritos.

## Contrato técnico implementado

Arquivo `src/nivon/maritime/programme_duv_evidence.py`:

- `ProgrammeDuvEvidence`: porto `PARANAGUA`, fonte, série, data de referência, Nº Prog qualificado, DUV expressamente documentada, SHA do line-up, URL HTTPS de evidência no domínio institucional permitido, SHA da evidência de associação, prova de aquisição, prova de publicação, prova de ligação e identificação de revisor; timestamps de publicação, aquisição e revisão com timezone.
- Evidência `OFFICIAL_SOURCE_EXPLICIT_PAIR`: o **mesmo PDF** precisa ter URL e hash iguais aos da edição e conter a **dupla Nº Prog–DUV no dado extraído**, não apenas um Nº Prog isolado.
- Evidência `OFFICIAL_AUTHORITY_CROSSWALK`: candidata à revisão apenas quando existe documentação independente que atribua explicitamente os dois identificadores. A presença de `concentrador.portosempapel.gov.br` na lista de hosts **não** implica acesso aberto, autorização ou prova de que exista o dado requerido nesse serviço.
- Datas: a relação não pode existir, estar publicada, ter sido adquirida ou revisada após o corte `as_of`. A edição PDF também deve ter publicação comprovada e coleta anterior ao corte.
- Escopo: a associação deve se referir à **mesma fonte, porto, série, data de referência e SHA da edição**. Não se pode aplicar um vínculo ao mesmo Nº Prog em outro dia/série/fonte.
- Divergência de DUVs para o mesmo Nº Prog, documento de outra fonte, programa ausente, URL não oficial ou prova temporal inconsistente deixam o relatório em `BLOCKED_UNVERIFIED_DOCUMENTARY_LINK`.
- Mesmo um dossiê inteiramente preenchido produz, no máximo, `CANDIDATE_READY_FOR_EXTERNAL_VERIFICATION`. Os campos `canonical_duv_link_allowed` e `release_allowed` permanecem **false**. Os booleans de revisão de direitos e de relação são declarações de entrada, **não** certificações de permissão ou homologação.
- Sem associação por IMO, nome, linha, produto ou horário; o parser não inventa IDs de escala. `PdfProgrammeLedger`, `LineupVintageLedger` e AIS seguem fisicamente separados.

## Testes e condições de aceitação

`tests/test_maritime_programme_duv_evidence.py`: cenários totalmente sintéticos para os dois tipos de documento, divergências de fonte, conflito de DUVs, exatidão do PDF, janela temporal, URLs indevidas, direitos não revisados, programa ausente e no-op canônico.

Para demonstrar um **vínculo real**, é necessário obter, sem burlar acesso, uma fonte que **publique explicitamente ambos os identificadores**; preservar bytes originais e prova de publicação, conferir direitos de coleta/uso/armazenamento, testar correspondência de pelo menos três edições reais e submeter a revisão independente. Esse material não foi adquirido nesta implementação. Atribuição em PDF de 2026 a uma escala efetivamente observada exige ainda dado operacional oficial próprio.

O contrato foi concebido para bloquear automaticamente ligações insuficientemente demonstradas; sua passagem não é sinal para unir bases ou publicar.

**Próxima fase:** quando houver documentação original e direitos comprovados, realizar revisão externa e testar a estabilidade temporal/semântica das ligações. Sem isso, manter `REAL_DATA_GATED / RIGHTS_UNVERIFIED / RELEASE_BLOCKED`.
