"""Execução MANUAL do arquivo integral ZARC MT, com saída agregada sanitizada."""
import argparse
import json
from nivon.zarc_stream_mt import processar_zarc_mt, ErroZarcStream

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--executar", action="store_true")
    args=ap.parse_args(argv)
    if not args.executar:
        print(json.dumps({"fonte_id":"ZARC_JANELAS", "estado":"REDE_OFF"}))
        return 2
    try:
        r=processar_zarc_mt(executar=True)
    except ErroZarcStream as exc:
        # Mensagens internas são literais estáticos, sem registros ou URLs.
        print(json.dumps({"fonte_id":"ZARC_JANELAS",
                          "estado":"REJEICAO_DE_CONTRATO",
                          "motivo_controlado":str(exc)[:120]}))
        return 1
    except Exception as exc:
        # Não imprimir respostas do servidor nem caminhos internos.
        print(json.dumps({"fonte_id":"ZARC_JANELAS",
                          "estado":"NAO_VALIDADO",
                          "tipo_erro":type(exc).__name__}))
        return 1
    permitido=("dataset_id","fonte_id","competencia","linhas_total_arquivo",
               "linhas_mt","municipios_ibge_mt","linhas_por_cultura_nome_original",
               "portarias_distintas_mt","sha256_original","bytes_originais",
               "estado","persistido","publicavel")
    print(json.dumps({k:r[k] for k in permitido},ensure_ascii=False,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
