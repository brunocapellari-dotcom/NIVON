"""Inteligência de corredores: rodovia -> polo logístico potencial.

Lê apenas lotes MDF-e importados em SQLite (nunca inventa uma transferência).
A correspondência município/RGI não comprova acesso a terminal nem transbordo.
Um 'recorte' é obrigatório: recortes sobrepostos não podem ser somados.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import re
import sqlite3
import unicodedata

# IDs estáveis; não usar capacidade instalada como volume observado.
# Referências oficiais ou operador preservadas no cadastro.
POLOS = (
    {"id":"MT_RONDONOPOLIS_FERRO", "nome":"Rondonópolis", "uf":"MT", "municipio":"Rondonópolis",
     "modal_destino":"FERROVIARIO", "situacao":"OPERACIONAL",
     "fonte_infra":"https://rumolog.com/nossas-malhas/"},
    {"id":"MT_ITIQUIRA_FERRO", "nome":"Itiquira", "uf":"MT", "municipio":"Itiquira",
     "modal_destino":"FERROVIARIO", "situacao":"OPERACIONAL_REFERENCIA",
     "fonte_infra":"https://anttlegis.antt.gov.br/action/ActionDatalegis.php?acao=abrirTextoAto&cod_menu=7748&cod_modulo=423&link=S&numeroAto=00004145&orgao=DG%2FANTT%2FMT&seqAto=000&tipo=RES&valorAno=2013"},
    {"id":"MT_DOM_AQUINO_BR070", "nome":"Terminal BR-070 (Dom Aquino)", "uf":"MT", "municipio":"Dom Aquino",
     "modal_destino":"FERROVIARIO", "situacao":"COMISSIONAMENTO_INICIADO_2026",
     "fonte_infra":"https://www.ferroviamt.com.br/noticias/novo-terminal-na-br-070-capacidade-para-escoar-ate-10-milhoes-de-toneladas-por-ano/"},
    {"id":"MT_ALTO_ARAGUAIA_FERRO", "nome":"Alto Araguaia", "uf":"MT", "municipio":"Alto Araguaia",
     "modal_destino":"FERROVIARIO", "situacao":"OPERACIONAL_REFERENCIA",
     "fonte_infra":"https://rumolog.com/nossas-malhas/"},
    {"id":"PA_MIRITITUBA_HIDRO", "nome":"Miritituba (Itaituba)", "uf":"PA", "municipio":"Itaituba",
     "modal_destino":"HIDROVIARIO", "situacao":"OPERACIONAL",
     "fonte_infra":"https://www.gov.br/portos-e-aeroportos/pt-br/assuntos/noticias/2026/05/rio-tapajos-se-consolida-como-importante-eixo-logistico-com-sustentabilidade-e-recordes-de-movimentacao"},
    {"id":"RO_PORTO_VELHO_HIDRO", "nome":"Porto Velho", "uf":"RO", "municipio":"Porto Velho",
     "modal_destino":"HIDROVIARIO", "situacao":"OPERACIONAL_REFERENCIA",
     "fonte_infra":"https://www.gov.br/antaq/pt-br"},
    {"id":"PA_SANTAREM_PORTO", "nome":"Santarém", "uf":"PA", "municipio":"Santarém",
     "modal_destino":"PORTUARIO_MARITIMO_HIDROVIARIO", "situacao":"OPERACIONAL",
     "fonte_infra":"https://www.cargill.com.br/pt_BR/santar%C3%A9m"},
    {"id":"PA_BARCARENA_PORTO", "nome":"Barcarena / Vila do Conde", "uf":"PA", "municipio":"Barcarena",
     "modal_destino":"PORTUARIO_MARITIMO_HIDROVIARIO", "situacao":"OPERACIONAL",
     "fonte_infra":"https://www.gov.br/antaq/pt-br"},
    {"id":"AM_ITACOATIARA_PORTO", "nome":"Itacoatiara", "uf":"AM", "municipio":"Itacoatiara",
     "modal_destino":"PORTUARIO_MARITIMO_HIDROVIARIO", "situacao":"OPERACIONAL_REFERENCIA",
     "fonte_infra":"https://www.gov.br/antaq/pt-br"},
    {"id":"SP_SANTOS_PORTO", "nome":"Santos", "uf":"SP", "municipio":"Santos",
     "modal_destino":"PORTUARIO_RODOVIARIO_FERROVIARIO", "situacao":"OPERACIONAL",
     "fonte_infra":"https://www.portodesantos.com.br/"},
    {"id":"PR_PARANAGUA_PORTO", "nome":"Paranaguá", "uf":"PR", "municipio":"Paranaguá",
     "modal_destino":"PORTUARIO_RODOVIARIO_FERROVIARIO", "situacao":"OPERACIONAL",
     "fonte_infra":"https://www.portosdoparana.pr.gov.br/"},
    {"id":"MA_SAO_LUIS_ITAQUI", "nome":"Itaqui (São Luís)", "uf":"MA", "municipio":"São Luís",
     "modal_destino":"PORTUARIO_RODOVIARIO_FERROVIARIO", "situacao":"OPERACIONAL",
     "fonte_infra":"https://www.portodoitaqui.com/"},
    {"id":"RS_RIO_GRANDE_PORTO", "nome":"Rio Grande", "uf":"RS", "municipio":"Rio Grande",
     "modal_destino":"PORTUARIO_RODOVIARIO_FERROVIARIO", "situacao":"OPERACIONAL",
     "fonte_infra":"https://www.portosrs.com.br/"},
    {"id":"SC_SAO_FRANCISCO_SUL_PORTO", "nome":"São Francisco do Sul", "uf":"SC", "municipio":"São Francisco do Sul",
     "modal_destino":"PORTUARIO_RODOVIARIO_FERROVIARIO", "situacao":"OPERACIONAL",
     "fonte_infra":"https://portosaofrancisco.com.br/"},
)

# NCM somente se declarado no MDF-e; 4 dígitos permitem classificação familiar.
NCM_GRUPOS = {
    "1201":"SOJA_EM_GRAO", "1005":"MILHO_EM_GRAO",
    "2304":"FARELO_SOJA", "1507":"OLEO_SOJA",
    "3102":"FERTILIZANTES_NITROGENADOS", "3105":"FERTILIZANTES_MISTURAS",
    "2710":"DERIVADOS_PETROLEO", "1701":"ACUCAR",
}

class ErroCorredor(ValueError):
    pass

def _norm(valor):
    s=unicodedata.normalize("NFKD",str(valor or "")).encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+"," ",s).strip()

def _local(localidade, polo):
    """Exige nome geográfico isolado; nunca procura substring em endereço."""
    s=_norm(localidade)
    m=_norm(polo["municipio"])
    uf=_norm(polo["uf"])
    return s in {m, m+" "+uf, uf+" "+m}

def _produto(ncm):
    if ncm is None:
        return "NAO_IDENTIFICADO"
    codigo=str(ncm).strip()
    if not re.fullmatch(r"\d{2,8}",codigo):
        raise ErroCorredor("NCM inválido no lote")
    return NCM_GRUPOS.get(codigo[:4],"OUTRO_NCM_IDENTIFICADO")

def _confianca(nivel):
    if nivel == "RGI":
        return "REGIAO_RGI_NAO_TERMINAL"
    if nivel == "MUNICIPIO":
        return "MUNICIPIO_NAO_TERMINAL"
    raise ErroCorredor("Granularidade não suportada")

def identificar_polos(localidade, *, nivel):
    _confianca(nivel)
    return [
        {"id":p["id"],"nome":p["nome"],"uf":p["uf"],
         "modal_destino":p["modal_destino"],"situacao":p["situacao"],
         "evidencia_geografica":_confianca(nivel),
         "terminal_confirmado":False,"transferencia_modal_confirmada":False,
         "fonte_infra":p["fonte_infra"]}
        for p in POLOS if _local(localidade,p)
    ]

def consultar_corredores(banco, *, recorte, competencia, limite=100):
    """Agrupa origens/destinos regionais do mesmo recorte versionado.
    Não soma recortes distintos, nem volumes de um modal a outro.
    """
    if not isinstance(recorte,str) or not re.fullmatch(r"[a-zA-Z0-9_-]{3,100}",recorte):
        raise ErroCorredor("Recorte identificador obrigatório")
    if not isinstance(competencia,str) or not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])",competencia):
        raise ErroCorredor("Competência mensal inválida")
    if not isinstance(limite,int) or not 1<=limite<=1000:
        raise ErroCorredor("Limite deve ser 1..1000")
    with sqlite3.connect(banco) as con:
        lote=con.execute(
            """SELECT id,sha256,coletado_em,nivel FROM antt_mdfe_lotes
            WHERE recorte=? AND ativo=1""",(recorte,)).fetchone()
        if lote is None:
            return {"estado":"SEM_DADOS","recorte":recorte,"competencia":competencia,"corredores":[]}
        id_lote,sha,coletado,nivel=lote
        _confianca(nivel)
        rows=con.execute(
            """SELECT origem,destino,nivel,ncm,categoria,toneladas,mdfes
            FROM antt_mdfe_od WHERE lote_id=? AND competencia=?""",
            (id_lote,competencia)).fetchall()
    # Não comparar totais 'sem NCM' com detalhamento NCM sem validar universo.
    grupos={}
    for origem,destino,grao,ncm,categoria,toneladas,mdfes in rows:
        if grao!=nivel:
            raise ErroCorredor("Níveis conflitantes no lote")
        produto=_produto(ncm)
        try:
            toneladas_decimal=Decimal(toneladas)
        except (InvalidOperation,TypeError) as exc:
            raise ErroCorredor("Tonelagem inválida armazenada") from exc
        if not toneladas_decimal.is_finite() or toneladas_decimal<0:
            raise ErroCorredor("Tonelagem negativa/não-finita")
        for lado,valor in (("DESTINO",destino),("ORIGEM",origem)):
            for polo in identificar_polos(valor,nivel=nivel):
                # Mesmo município pode ter mais de um terminal: não criar
                # dupla contagem / não duplicar destino municipal entre terminais.
                key=(lado,polo["id"],origem,destino,produto,ncm,categoria)
                if key not in grupos:
                    grupos[key]={"sentido":lado, "polo":polo, "origem":origem, "destino":destino,
                                 "produto":produto, "ncm":ncm, "categoria":categoria,
                                 "toneladas_no_recorte":Decimal(0),
                                 "mdfes_no_recorte":0 if mdfes is not None else None}
                g=grupos[key]
                g["toneladas_no_recorte"]+=toneladas_decimal
                if mdfes is None:
                    g["mdfes_no_recorte"]=None
                elif g["mdfes_no_recorte"] is not None:
                    g["mdfes_no_recorte"]+=int(mdfes)
    ranking=sorted(grupos.values(),key=lambda x:(-x["toneladas_no_recorte"],x["polo"]["id"],x["origem"],x["destino"],x["produto"]))
    for g in ranking:
        g["toneladas_no_recorte"]=format(g["toneladas_no_recorte"],"f")
        g["unidade"]="toneladas"
        g["natureza"]="RODOVIARIO_MDFE_IMPORTADO_NAO_HOMOLOGADO"
        g["observacao"]="Destino geográfico não comprova transbordo, terminal ou porto utilizado."
    return {
        "estado":"RECORTE_IMPORTADO_NAO_HOMOLOGADO" if rows else "COMPETENCIA_AUSENTE",
        "recorte":recorte,"competencia":competencia,"granularidade":nivel,
        "sha256_origem":sha,"data_coleta":coletado,
        "linhas_encontradas":len(rows),"corredores_relevantes":len(ranking),
        "cobertura":{"produto_por_ncm":"AMOSTRAL_SE_DECLARADO",
                     "regional_ou_municipal":_confianca(nivel),
                     "sem_inferencia_de_transbordo":True,
                     "nao_somar_com_rail_ou_antaq":True},
        "corredores":ranking[:limite],
        "truncado":len(ranking)>limite,
    }

def salvar_relatorio(banco, *, recorte, competencia, caminho, limite=100):
    r=consultar_corredores(banco,recorte=recorte,competencia=competencia,limite=limite)
    alvo=Path(caminho)
    alvo.parent.mkdir(parents=True,exist_ok=True)
    # Uso em diretório privado. Não subir produtos/volumes reais a GitHub.
    alvo.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return {"estado":r["estado"],"grupos":len(r["corredores"]),
            "sha256_origem":r.get("sha256_origem")}
