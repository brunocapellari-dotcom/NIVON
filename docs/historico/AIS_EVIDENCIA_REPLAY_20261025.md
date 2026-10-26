# Contrato AIS de auditoria

Toda posição precisa de MMSI, relógio da fonte, recepção, coordenadas válidas e identificação do evento. A presença em geocerca não comprova escala, DUV, carregamento, fila ou navio operado. Sem fonte original e histórico confiável, manter SHADOW.


## Implementação incorporada em 25/10/2026

- [PR #257](https://github.com/brunocapellari-dotcom/NIVON/pull/257): ingestão local de mensagens AIS RAW, hashes SHA-256, histórico SQLite e replay com controle temporal; [144 testes do painel aprovados](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40254211759).
- [PR #261](https://github.com/brunocapellari-dotcom/NIVON/pull/261): candidatos de permanência por geocerca declarada e isolamento dos indicadores de operação; [8 testes específicos aprovados](https://github.com/brunocapellari-dotcom/NIVON/actions/runs/40254707948).

**Limites:** geocerca declarada não é homologada; sequência AIS não confirma DUV, fila, atracação ou embarque. Os testes usam trajetórias sintéticas. Sem comprovação de ingestão AIS contínua no Google Cloud.

**Próximas provas:** cobertura AIS autorizada, geocercas auditadas, cruzamento MMSI/IMO com eventos portuários oficiais e backtest temporal independente.
