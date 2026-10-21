"""IVO/PAM: cronologia de divulgação e erratas baseada em snapshots locais.

Comprova integridade dos bytes e consistência de datas declaradas no
registro do NIVON, NÃO autenticidade do PDF, licenças ou data externa oficial.
Nenhuma rede, escrita, treino ou promoção.
"""
from __future__ import annotations
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from urllib.parse import urlsplit
from .ivo_pam_bridge import preparar_pam_anual_asof

class ErroPublicacaoPAM(ValueError): pass

def _utc(v):
    if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None:
        raise ErroPublicacaoPAM("instante com timezone obrigatório")
    return v.astimezone(timezone.utc)

@dataclass(frozen=True)
class EventoPAM:
    id: str
    tipo: str
    plano: dict
    json_original: bytes
    json_coletado_em: datetime
    documento_pdf: bytes
    documento_url: str
    documento_sha256: str
    publicado_em: date
    documento_coletado_em: datetime
    revisor_id: str
    revisado_em: datetime

    def validar(self):
        if not isinstance(self.id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,80}",self.id):
            raise ErroPublicacaoPAM("ID inválido")
        if self.tipo not in ("DIVULGACAO","ERRATA"):
            raise ErroPublicacaoPAM("tipo de edição inválido")
        if not isinstance(self.plano,dict):
            raise ErroPublicacaoPAM("plano inválido")
        if not isinstance(self.json_original,bytes) or not 0<len(self.json_original)<=2_000_000:
            raise ErroPublicacaoPAM("JSON obrigatório e limitado")
        if (not isinstance(self.documento_pdf,bytes)
            or not 20<=len(self.documento_pdf)<=8_000_000
            or not self.documento_pdf.startswith(b"%PDF-")):
            raise ErroPublicacaoPAM("PDF com bytes originais obrigatório")
        if (not isinstance(self.documento_sha256,str)
            or self.documento_sha256!=sha256(self.documento_pdf).hexdigest()):
            raise ErroPublicacaoPAM("hash do PDF divergente")
        try: url=urlsplit(self.documento_url)
        except (TypeError,ValueError) as exc: raise ErroPublicacaoPAM("URL inválida") from exc
        if (url.scheme!="https" or url.hostname not in (
              "www.ibge.gov.br","biblioteca.ibge.gov.br","agenciadenoticias.ibge.gov.br")
              or url.username is not None or url.password is not None or url.port is not None
              or not url.path or url.path=="/"):
            raise ErroPublicacaoPAM("URL não é documento em domínio IBGE permitido")
        if not isinstance(self.publicado_em,date) or isinstance(self.publicado_em,datetime):
            raise ErroPublicacaoPAM("dia de publicação inválido")
        j,d,r=map(_utc,(self.json_coletado_em,self.documento_coletado_em,self.revisado_em))
        if self.publicado_em>min(j.date(),d.date()) or r<max(j,d):
            raise ErroPublicacaoPAM("publicação, coleta ou revisão inconsistentes")
        if not isinstance(self.revisor_id,str) or not self.revisor_id.strip():
            raise ErroPublicacaoPAM("identidade declarada do revisor obrigatória")

def _conferir_pdf(db:sqlite3.Connection,e:EventoPAM):
    if not isinstance(db,sqlite3.Connection):
        raise ErroPublicacaoPAM("ledger de snapshots obrigatório")
    try:
        rows=db.execute("""SELECT s.fonte_id,s.bytes,s.mime,s.schema_versao,
               s.competencia,s.referencia,s.publicacao,s.tipo,s.evidencia_direitos,
               c.coletado_utc FROM nivon_snapshots s
               JOIN nivon_coletas c ON c.snapshot_id=s.id
               WHERE s.dataset_id='IBGE_PAM' AND s.sha256=?""",
            (e.documento_sha256,)).fetchall()
    except sqlite3.Error as exc:
        raise ErroPublicacaoPAM("snapshot documental indisponível") from exc
    for r in rows:
        (fonte,tamanho,mime,schema,comp,ref,pub,tipo,direitos,coleta)=tuple(r)
        expected=("IBGE",len(e.documento_pdf),"application/pdf","ivo_pam_release_doc_v1",
                  str(e.plano["ano"]),f"{e.plano['ano']}-12-31",e.publicado_em.isoformat())
        try: capturado=datetime.fromisoformat(coleta.replace("Z","+00:00"))
        except (TypeError,AttributeError,ValueError): continue
        if ((fonte,tamanho,mime,schema,comp,ref,pub)==expected
              and _utc(capturado)==_utc(e.documento_coletado_em)
              and tipo in ("SINTETICO","REAL_AUTORIZADO")
              and ((tipo=="SINTETICO" and direitos is None)
                   or (tipo=="REAL_AUTORIZADO" and bool(direitos)))):
            return tipo
    raise ErroPublicacaoPAM("PDF não corresponde ao livro de snapshots")

def historico_edicoes_pam_asof(edicoes:list[EventoPAM],*,db:sqlite3.Connection,
    corte:datetime,variavel:str,produto:str,unidade:str="Toneladas")->dict:
    cutoff=_utc(corte)
    if not isinstance(edicoes,list) or not 1<=len(edicoes)<=40:
        raise ErroPublicacaoPAM("quantidade de versões inválida")
    ids=set()
    alvo=None
    disponiveis=[]
    for e in edicoes:
        if not isinstance(e,EventoPAM):
            raise ErroPublicacaoPAM("evento não tipado")
        e.validar()
        if e.id in ids:
            raise ErroPublicacaoPAM("IDs de edição duplicados")
        ids.add(e.id)
        p=e.plano
        scope=(p.get("municipio_ibge"),p.get("ano"),p.get("variavel"),p.get("categoria_c81"))
        if alvo is None: alvo=scope
        elif scope!=alvo: raise ErroPublicacaoPAM("séries de municípios/culturas/anos misturadas")
        if max(_utc(e.json_coletado_em),_utc(e.documento_coletado_em),
               _utc(e.revisado_em))>cutoff or e.publicado_em>cutoff.date():
            continue
        tipo=_conferir_pdf(db,e)
        result=preparar_pam_anual_asof(payload=e.json_original,plano=e.plano,
            coletado_em=_utc(e.json_coletado_em).isoformat(),corte=cutoff,registro_db=db,
            variavel_autorizada=variavel,produto_autorizado=produto,
            unidade_autorizada=unidade)
        # A resposta da ponte inclui classe do documento JSON quando numérico.
        if result["estado"]=="BLOQUEADO_MARCADOR_SIDRA":
            raise ErroPublicacaoPAM("versão censurada ou arredondada não é resultado exato")
        if result["tipo_snapshot"]!=tipo:
            raise ErroPublicacaoPAM("PDF e JSON não podem misturar classes sintética/real")
        if result["data_publicacao_declarada"]!=e.publicado_em.isoformat():
            raise ErroPublicacaoPAM("data do PDF diverge do snapshot JSON")
        disponiveis.append((e,result))
    disponiveis.sort(key=lambda x:(x[0].publicado_em,_utc(x[0].json_coletado_em),x[0].id))
    if disponiveis and (disponiveis[0][0].tipo!="DIVULGACAO"
        or sum(e.tipo=="DIVULGACAO" for e,_ in disponiveis)!=1):
        raise ErroPublicacaoPAM("errata sem divulgação original única")
    prev=None
    vistos=set()
    historia=[]
    for e,v in disponiveis:
        ordem=(e.publicado_em,_utc(e.json_coletado_em))
        if ordem in vistos: raise ErroPublicacaoPAM("duas versões ambíguas no mesmo instante")
        vistos.add(ordem)
        valor=v["observacao"].valor
        historia.append({"evento_id":e.id,"tipo":e.tipo,"valor":valor,
            "delta_desde_anterior":valor-prev if prev is not None else None,
            "data_declarada":e.publicado_em.isoformat(),
            "json_sha256":sha256(e.json_original).hexdigest(),
            "documento_sha256":e.documento_sha256,
            "documento_url":e.documento_url,
            "revisor_declarado":e.revisor_id,
            "json_coletado_em":e.json_coletado_em.isoformat(),
            "documento_coletado_em":e.documento_coletado_em.isoformat(),
            "revisado_em":e.revisado_em.isoformat()})
        prev=valor
    return {"estado":"PAM_VERSIONADA_NAO_HOMOLOGADA" if historia else "SEM_EDICAO_CONHECIDA",
        "alvo":alvo,"corte":cutoff.isoformat(),"historico":historia,
        "edicoes_conhecidas":len(historia),"valor_asof":prev,
        "origem_documental_autenticada_externamente":False,
        "data_oficial_publicacao_comprovada":False,"treinamento_real_autorizado":False,
        "label_final_certificado":False,
        "aviso":"Metadados, hashes e URL oficial não comprovam autenticidade do PDF nem licenças; sem treino real."}
