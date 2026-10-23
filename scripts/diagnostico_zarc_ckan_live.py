"""Prova online de um GET ao CKAN MAPA, sem baixar o CSV grande."""
import argparse
import json
from nivon.zarc_sinais_ckan import abrir_historico_zarc_meta,verificar_fonte_ckan

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--executar",action="store_true")
    args=p.parse_args(argv)
    if not args.executar:
        print(json.dumps({"estado":"REDE_OFF","consultas":0}))
        return 2
    try:
        with abrir_historico_zarc_meta() as db:
            r=verificar_fonte_ckan(executar=True,db=db)
            # Não imprime URLs, headers de rede, conteúdo CSV ou identidades.
            keep=("dataset_id","resource_id","coleta_utc",
                  "licenca_declarada","pacote_revision_id",
                  "recurso_revision_id","pacote_modified",
                  "recurso_modified","metadata_fingerprint",
                  "estado","sinal_revision_changed","pode_afirmar_novo_csv",
                  "csv_baixado","observacoes")
            print(json.dumps({k:r.get(k) for k in keep},
                             sort_keys=True,ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"estado":"METADADOS_NAO_VERIFICADOS",
                          "causa_tipo":type(exc).__name__}))
        return 1

if __name__=="__main__":
    raise SystemExit(main())
