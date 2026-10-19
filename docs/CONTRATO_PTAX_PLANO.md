# PTAX Banco Central — plano de consulta sem execução HTTP

Fonte: https://dadosabertos.bcb.gov.br/pt_BR/dataset/dolar-americano-usd-todos-os-boletins-diarios
Documentação OData: https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/documentacao

O módulo `ptax_plano.py` apenas constrói URLs oficiais para USD (`CotacaoDolarPeriodo`) e EUR (`CotacaoMoedaPeriodo`). Cada lote abrange no máximo 366 dias, dividido em janelas de até 20 dias, sem sobreposição. Usa os parâmetros de data `MM-DD-AAAA` do serviço OData e não inventa boletins nos dias sem observações.

O módulo `bcb_ptax.py` segue responsável por validar e normalizar a resposta recebida por um coletor futuro. Nenhum novo HTTP, agendamento, autorização, segredo ou deploy foi adicionado. Testes utilizam resposta sintética; endpoint real, direitos de uso, paginação, volumes e publicação comercial seguem em homologação.
