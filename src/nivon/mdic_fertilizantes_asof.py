"""Consulta local de MDIC Comex Stat importação de fertilizantes por NCM.

Visão de RESEARCH: agregados de uma seleção NCM guardada no ledger MDIC.
Não produz indicador publicável de briefing: pipeline MDIC ainda não homologou
publicação, fonte NCM/UF não representa entrega em fazenda nem cotação spot.
Não consulta internet, não escreve no SQLite e não cria schema.
"""
from __future__ import annotations

import json
import re
import sqlite3
from decimal import Decimal
from datetime import date

from .fertilizantes import NCM_GRUPOS
from .indicadores_historicos import _instante


class ErroVisaoFertilizantes(ValueError):
    pass


def resumo_mdic_fertilizante_asof(
    db: sqlite3.Connection, *, ncm: str, uf: str,
    ano: int, mes: int, gerado_em: str,
    leitura_autorizada: bool = False,
) -> dict:
    if leitura_autorizada is not True:
        return {"status":"BLOQUEADO_DIREITOS_LEITURA","publicavel":False}
    corte=_instante(gerado_em)
    if (not isinstance(ncm,str) or ncm not in NCM_GRUPOS
        or not isinstance(uf,str) or not re.fullmatch(r"[A-Z]{2}",uf)
        or type(ano) is not int or not 1997<=ano<=2100
        or type(mes) is not int or not 1<=mes<=12):
        raise ErroVisaoFertilizantes("seletores de MDIC/NCM fora do contrato")
    competencia=f"{ano:04d}-{mes:02d}"
    if date(ano,mes,1)>corte.date():
        raise ErroVisaoFertilizantes("competência futura")
    try:
        versions=db.execute("""
          SELECT a.resultado_json,s.sha256,s.evidencia_direitos,
                 MAX(c.coletado_utc) AS visto_em
          FROM nivon_mdic_agregados a
          JOIN nivon_snapshots s ON s.id=a.snapshot_id
          JOIN nivon_coletas c ON c.snapshot_id=s.id
          WHERE s.dataset_id='MDIC_COMEX_NCM'
            AND s.tipo='REAL_AUTORIZADO'
            AND a.ano=? AND a.direcao='IMPORTACAO'
            AND a.granularidade='NCM'
            AND c.coletado_utc<=?
          GROUP BY a.snapshot_id
          ORDER BY visto_em DESC,s.sha256 DESC LIMIT 3
        """,(ano,corte.isoformat())).fetchall()
    except sqlite3.Error:
        return {"status":"BANCO_INDISPONIVEL","publicavel":False}
    if not versions:
        return {"status":"SEM_SNAPSHOT_REAL_ASOF","publicavel":False}
    if (len(versions)>1 and versions[0][3]==versions[1][3]
        and versions[0][1]!=versions[1][1]):
        return {"status":"VINTAGES_CONFLITANTES","publicavel":False}
    row=versions[0]
    try:
        snapshot=json.loads(row[0])
        seen=_instante(row[3])
        evidence=row[2]
        sha=row[1]
        if not isinstance(snapshot,dict) or not isinstance(snapshot.get("recortes"),list):
            raise ErroVisaoFertilizantes("snapshot JSON inválido")
        if (not isinstance(snapshot.get("codigos_solicitados"),list)
            or not all(isinstance(c,str) for c in snapshot["codigos_solicitados"])):
            raise ErroVisaoFertilizantes("contrato de filtro NCM inválido")
        if ncm not in snapshot["codigos_solicitados"]:
            return {"status":"NCM_FORA_DA_COBERTURA_DO_SNAPSHOT","publicavel":False}
        if (not isinstance(sha,str) or re.fullmatch(r"[a-f0-9]{64}",sha) is None
            or not isinstance(evidence,str) or not evidence.strip()):
            raise ErroVisaoFertilizantes("proveniência não identificada")
        kg=usd=linhas=0
        for item in snapshot["recortes"]:
            if not isinstance(item,dict):
                raise ErroVisaoFertilizantes("linha de recorte malformada")
            if item.get("codigo_produto")!=ncm or item.get("uf")!=uf or item.get("competencia")!=competencia:
                continue
            if item.get("classificacao")!="NCM" or item.get("uf_nao_prova_municipio") is not True:
                raise ErroVisaoFertilizantes("campos geográficos incomparáveis")
            quantities=[item.get("peso_liquido_kg"),item.get("valor_fob_usd"),item.get("linhas_agrupadas")]
            if any(type(v) is not int or v<0 or v>10**18 for v in quantities):
                raise ErroVisaoFertilizantes("quantidades de origem inválidas")
            k,v,n=quantities
            kg+=k
            usd+=v
            linhas+=n
        if linhas==0:
            return {"status":"SEM_RECORTE_NO_SNAPSHOT","publicavel":False,
                    "advertencia":"não interpretar ausência como volume zero"}
        if kg==0:
            return {"status":"PESO_NAO_COMPARAVEL","publicavel":False}
        tons=Decimal(kg)/1000
        preco=Decimal(usd)/tons
        return {
            "status":"ANALISE_MDIC_NAO_HOMOLOGADA",
            "publicavel":False,
            "enviar_whatsapp":False,
            "registro":{
                "competencia":competencia,"uf_fiscal":uf,
                "ncm":ncm,"produto":NCM_GRUPOS[ncm],
                "volume_t":float(tons),
                "valor_fob_usd":usd,
                "valor_unitario_fob_usd_t":float(round(preco,2)),
                "linhas_agrupadas":linhas,
                "tipo_valor":"UNITARIO_FOB_CALCULADO_NAO_PRECO_CFR_NEM_COTACAO_SPOT",
            },
            "evidencia":{
                "dataset":"MDIC_COMEX_NCM","sha256_arquivo":sha,
                "visto_em":seen.isoformat(),
                "publicacao":None,
                "evidencia_direitos_armazenamento":evidence,
                "ponto_no_tempo":"APENAS_COLETA_NAO_PUBLICACAO",
                "filtro_ncm_interno":"COBERTURA_SOMENTE_CODIGOS_INGESTADOS",
                "uf_nao_comprova_municipio_ou_destino":True,
            },
            "impedimentos_publicacao":[
                "agregados MDIC não homologados contra totais oficiais",
                "data de publicação não verificada",
                "direitos de redistribuição por operação não confirmados",
                "UF fiscal não demonstra origem física ou chegada a armazém",
            ],
        }
    except (ValueError,TypeError,KeyError,OverflowError) as exc:
        if isinstance(exc,ErroVisaoFertilizantes):
            raise
        raise ErroVisaoFertilizantes("agregado MDIC inválido") from exc
