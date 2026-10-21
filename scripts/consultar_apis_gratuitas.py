"""Diagnóstico MANUAL de uma chamada de API gratuita, sem salvar dados.

Comandos:
 PYTHONPATH=src python scripts/consultar_apis_gratuitas.py --fonte selic --executar
 PYTHONPATH=src python scripts/consultar_apis_gratuitas.py --fonte clima --latitude -13 --longitude -56 --executar
 PYTHONPATH=src python scripts/consultar_apis_gratuitas.py --fonte banco_mundial --indicador SP.POP.TOTL --inicio-ano 2020 --fim-ano 2025 --executar
Nada roda por padrão; o catálogo NÃO é ativado por este script.
"""
import argparse
import json

from nivon.apis_gratuitas_execucao import (
    consultar_open_meteo, consultar_selic, consultar_banco_mundial,
    consultar_ibge_municipios, consultar_nasa_power,
)


def executar(argv=None):
    parser = argparse.ArgumentParser(description="NIVON: smoke pontual e somente leitura de APIs públicas")
    parser.add_argument("--fonte", choices=("selic", "clima", "historico_clima", "banco_mundial", "ibge", "nasa_power"), required=True)
    parser.add_argument("--executar", action="store_true", help="Autoriza somente UMA consulta HTTPS pontual; sem persistência ou agendamento")
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--inicio", help="AAAA-MM-DD para histórico/POWER")
    parser.add_argument("--fim", help="AAAA-MM-DD para histórico/POWER")
    parser.add_argument("--dias", type=int, default=7)
    parser.add_argument("--indicador", default="SP.POP.TOTL")
    parser.add_argument("--inicio-ano", type=int, default=2020)
    parser.add_argument("--fim-ano", type=int, default=2025)
    args = parser.parse_args(argv)
    if not args.executar:
        print(json.dumps({"status": "BLOQUEADO_POR_PADRAO",
                          "fonte": args.fonte,
                          "instrucao": "Use --executar para consulta pontual explícita."}, ensure_ascii=False))
        return 2
    coords = {}
    if args.fonte in ("clima", "historico_clima", "nasa_power"):
        if args.latitude is None or args.longitude is None:
            parser.error("--latitude e --longitude obrigatórios para fonte geográfica")
        coords = {"latitude": args.latitude, "longitude": args.longitude}
    try:
        if args.fonte == "selic":
            r = consultar_selic(executar=True)
        elif args.fonte == "clima":
            r = consultar_open_meteo(tipo="previsao", dias_previsao=args.dias,
                                    executar=True, **coords)
        elif args.fonte == "historico_clima":
            r = consultar_open_meteo(tipo="reanalise", inicio=args.inicio, fim=args.fim,
                                    executar=True, **coords)
        elif args.fonte == "nasa_power":
            r = consultar_nasa_power(inicio=args.inicio, fim=args.fim, executar=True, **coords)
        elif args.fonte == "ibge":
            r = consultar_ibge_municipios(executar=True)
        else:
            r = consultar_banco_mundial(indicador=args.indicador, inicio=args.inicio_ano,
                                       fim=args.fim_ano, executar=True)
    except Exception as exc:
        # Apenas tipo do erro para não vazar URLs, valores, credenciais ou detalhes de rede.
        print(json.dumps({"status": "FALHA", "fonte": args.fonte,
                          "erro_tipo": type(exc).__name__}, ensure_ascii=False))
        return 1
    dados = r["dados"]
    total = dados.get("quantidade", dados.get("numero_observacoes",
            dados.get("numero_dias", dados.get("quantidade", dados.get("quantidade", None)))))
    if total is None:
        total = len(dados.get("observacoes", dados.get("municipios", [])))
    # Nunca registrar valores, população, série histórica nem outro dado bruto no CI.
    print(json.dumps({"status": "CONSULTA_PONTUAL_VALIDADA_SEM_PERSISTENCIA",
                      "fonte": args.fonte, "dataset_id": dados.get("dataset_id"),
                      "linhas": total,
                      "host": r["aquisição"]["url"].split("/")[2],
                      "sha256": r["aquisição"]["sha256"],
                      "coleta": r["aquisição"]["coleta"],
                      "publicacao_operacional_autorizada": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(executar())
