# NIVON — Plano de histórico meteorológico NASA POWER e CHIRPS v3

**Data-base:** 20 de outubro de 2026 · **Camada:** científica e ingestão sob controle · **PR:** #1.

## Evidência oficial e uso correto

**NASA POWER Daily:** https://power.larc.nasa.gov/docs/services/api/temporal/daily/
- Oferece respostas diárias para meteorologia/radiação desde 1981, inclusive `time-standard=UTC` ou `LST`; LST é padrão e nunca deve ser confundido com hora oficial de Mato Grosso.
- Até 20 parâmetros por ponto. A documentação alerta sobre requisições repetidas à mesma célula global aproximada de 0,5° que podem causar bloqueio.
- Produto é grade/reanálise, não medição INMET. Resposta precisa passar por validação de coordenada de origem; onda curta solar `ALLSKY_SFC_SW_DWN` não é a radiação líquida `Rn` do FAO-56.
- `-999` é missing, não chuva zero. Nunca fabricar carimbo de publicação quando só se conhece data de coleta.

**CHIRPS v3:** https://www.chc.ucsb.edu/data/chirps3
- Grade de 0,05°, 60°N–60°S, 1981-atualidade, cobertura quase global sobre terra.
- `sat` é série diária desagregada com IMERG Late V07; `rnl` usa ERA5 para distribuir os totais de chuva das **pêntadas**; não misturar esses dois produtos, nem versões preliminar/final.
- Versão preliminar normalmente disponível dois dias após encerramento da pêntada; final costuma sair na terceira semana do mês seguinte. Datas diárias são rótulos de desagregação e não janelas de observação uniforme de pluviômetros.
- Fonte oficial informa licença **CC BY 4.0**: registrar a atribuição devida, DOI, versão e data de aquisição; licença não prova qualidade da comparação local nem autoriza atribuir dados como observação de fazenda.

## Implementações e execução

1. `nasa_power_diario.py`: contrato e leitura JSON diária UTC, verificação da coordenada retornada, limites físicos e faltantes.
2. `nasa_power_backfill.py`: dividir 1981–presente em janelas anuais, incluindo bissextos; diagnosticar quais estão armazenadas antes de solicitar HTTP.
3. `nasa_power_captura_manual.py`: no máximo uma requisição por ação explícita, HTTPS e host exato, MIME JSON, limite 2 MB, cache por URL/hash, direitos registrados e sem redirecionamento. **Sem agendamento.**
4. `grade_meteorologica_store.py`: SQLite por requisição, SHA de conteúdo, ponto solicitado, centro de grade retornado, data UTC, versão e coleta; transação aninhada por savepoint e consultas temporais as-of.
5. `chirps_v3_conservacao.py`: checar as somas diárias contra total de pêntada, inclusive pêntada final de fevereiro/meses de 31 dias; não consulta a rede nem abre NetCDF/GeoTIFF.
6. As novas funções estão vinculadas ao registro das frentes METEOROLOGIA, HIDROLOGIA e à fachada CLIMA_HIDRO.

**Datas importantes:** dados meteorológicos têm competência, referência, publicação e coleta distintas. Quando a fonte não fornece publicação imutável, o histórico pode ser usado em análise retrospectiva, mas não deve entrar automaticamente em backtest sem look-ahead. A consulta `grade_asof` exclui publicações desconhecidas.

## Homologação necessária

- Verificar diretamente payload real NASA POWER e CHIRPS v3, sem simulá-los como capturados.
- Confirmar licença por operação e aplicar atribuição CC BY no output público.
- Validar municípios/células, grade, precipitação diária/horária e fusos, além de comparação com INMET.
- Implementar aquisição espacial autorizada de NetCDF/GeoTIFF CHIRPS, hash, reprojeção e recorte Brasil/Mato Grosso.
- Migrar captura/backup para storage durável em nuvem; o SQLite aqui continua local.
- Validar capacidade preditiva com dados históricos/vintages, treino walk-forward e holdout espacial; somente depois emitir sinais de risco para o Ivo.

**Status:** funções e testes offline existentes; nenhuma coleta agendada, nenhum deploy e nenhum modelo preditivo homologado. A presente execução não obteve dados reais NASA pelo ambiente de execução, que não resolve o DNS do serviço externo.
