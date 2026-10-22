"""Lista de safras publicadas CONAB: somente origens e períodos verificados."""
from datetime import datetime
from zoneinfo import ZoneInfo

from nivon.conab_publicacoes import selecionar_publicacoes
from nivon.conab_safras import checar_meta, validar_linhas

PRODUTOS = ("soja", "milho")

async def edicoes_atuais(conab, limite=2, hoje=None):
    hoje = hoje or datetime.now(ZoneInfo("America/Cuiaba")).date()
    rows = await conab.levantamentos()
    return selecionar_publicacoes(rows, hoje=hoje, limite=limite, primeira_safra=2024)

async def registros_publicacao(conab, publicacao):
    """Apenas edição de safra explícita (não dataset revisado por fallback)."""
    registros=[]
    for produto in PRODUTOS:
        tabela, meta = await conab.safras(
            produto, safra=publicacao["safra"], uf="MT",
            levantamento=publicacao["levantamento"], return_meta=True)
        validacao = checar_meta(meta)
        detalhes = validacao.get("source_details") or {}
        p = detalhes.get("publicacao")
        if not isinstance(p, dict):
            raise ValueError("Origem da publicação não disponível")
        for chave, item in (("safra","safra"), ("levantamento","levantamento"),
                            ("data_publicacao","data_publicacao"),("url","url")):
            if p.get(chave) != publicacao[item]:
                raise ValueError("Metadados divergentes da edição: "+chave)
        linhas=validar_linhas(tabela.to_dict(orient="records"), produto,
                            publicacao["safra"],"MT",publicacao["levantamento"])
        if linhas["quantidade_validas"]!=1 or linhas["quantidade_rejeitadas"]:
            raise ValueError("Dados em quarentena: "+produto)
        registros.append({
            "source":"CONAB","origin_kind":"agrobr.conab.safras",
            "parser_version":"agrobr-2.0.0-schema-"+str(validacao["schema_version"]),
            "publication_url":p["url"],
            "publication_date":p["data_publicacao"],
            "publication_safra":p["safra"],
            "publication_survey":p["levantamento"],
            "metric":linhas["validas"][0],
        })
    return registros
