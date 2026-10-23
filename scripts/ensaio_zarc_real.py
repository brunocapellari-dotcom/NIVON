"""Prova manual de CSV MAPA verdadeiro, retido apenas durante o job efêmero."""
import json
from nivon.zarc_ensaio_real import ensaiar_zarc_real

def main():
    try:
        result=ensaiar_zarc_real(executar=True)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0
    except Exception as e:
        # Nunca publicar texto de erro de terceiros (URLs assinadas/segredos).
        print(json.dumps({"estado":"QUARENTENA_NAO_HOMOLOGADA",
                          "erro_tipo":type(e).__name__}))
        return 1

if __name__=="__main__":
    raise SystemExit(main())
