"""Quarentena local, content-addressed, para arquivos candidatos PAM.

Preserva os bytes originais e recibos idempotentes; não modifica
registro_snapshots, não faz rede e não afirma licença/autenticidade da fonte.
Os recibos guardam carimbo de coleta DECLARADO, enquanto a execução do
cofre é verificada localmente. Não substituir por banco canônico.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime,timezone
from pathlib import Path

from .ivo_pam_coletor_pontual import _url


class ErroQuarentenaPAM(ValueError):
    pass


TIPOS={"SIDRA_JSON":2_000_000,"PDF_IBGE":8_000_000,
       "ARQUIVO_LEGADO":8_000_000}
ESTADO="CAPTURA_PONTUAL_PAM_QUARENTENA_NAO_HOMOLOGADA"


def _path(root):
    if not isinstance(root,(str,Path)):
        raise ErroQuarentenaPAM("diretório local obrigatório")
    caminho=Path(root).expanduser()
    if caminho.exists() and (not caminho.is_dir() or caminho.is_symlink()):
        raise ErroQuarentenaPAM("destino é link simbólico ou não é diretório")
    caminho.mkdir(parents=True,exist_ok=True,mode=0o700)
    if caminho.is_symlink() or not caminho.is_dir():
        raise ErroQuarentenaPAM("diretório de quarentena inválido")
    return caminho


def _pasta(root,nome):
    local=root/nome
    if local.is_symlink():
        raise ErroQuarentenaPAM("subdiretório é link simbólico")
    local.mkdir(exist_ok=True,mode=0o700)
    if not local.is_dir() or local.is_symlink():
        raise ErroQuarentenaPAM("subdiretório inválido")
    return local


def _gravar_uma_vez(path,raw):
    if path.is_symlink():
        raise ErroQuarentenaPAM("arquivo de quarentena é symlink")
    flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0)
    try:
        fd=os.open(path,flags,0o600)
    except FileExistsError:
        if not path.is_file() or path.is_symlink() or path.read_bytes()!=raw:
            raise ErroQuarentenaPAM("colisão ou arquivo já gravado foi adulterado")
        return False
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:path.unlink(missing_ok=True)
        except OSError:pass
        raise
    return True


def arquivar_candidato_pam(*, raiz:str|Path, candidato:dict,
                           limite_total_bytes:int=64*1024*1024)->dict:
    """Materializa SOMENTE candidatos; não converte em REAL_AUTORIZADO.

    O candidato deve vir do coletor guardado ou ter contrato idêntico;
    a integridade do payload é conferida, mas direitos/identidade declarados
    pelo chamador seguem NÃO autenticados. Nenhum campo de "homologado"
    pode entrar com valor True.
    """
    if (not isinstance(candidato,dict) or candidato.get("estado")!=ESTADO
        or candidato.get("fonte")!="IBGE"
        or candidato.get("dataset_id")!="IBGE_PAM"
        or candidato.get("autenticidade_documental_verificada") is not False
        or candidato.get("publicacao_oficial_verificada") is not False
        or candidato.get("treinamento_autorizado") is not False
        or candidato.get("gravado_em_snapshot_ledger") is not False):
        raise ErroQuarentenaPAM("somente candidato não homologado pode ser arquivado")
    if type(limite_total_bytes) is not int or not 1024<=limite_total_bytes<=1024*1024*1024:
        raise ErroQuarentenaPAM("limite do cofre inválido")
    raw=candidato.get("conteudo_original")
    kind=candidato.get("tipo")
    digest=candidato.get("sha256")
    if (kind not in TIPOS or not isinstance(raw,bytes) or
            not 0<len(raw)<=TIPOS[kind] or
            digest!=hashlib.sha256(raw).hexdigest()
            or candidato.get("bytes")!=len(raw)):
        raise ErroQuarentenaPAM("bytes/tamanho/SHA de candidato inválidos")
    try:
        url=_url(candidato.get("url_exata"),tipo=kind)
    except ValueError as exc:
        raise ErroQuarentenaPAM("endereço da fonte inválido") from exc
    data=candidato.get("coletado_em")
    if not isinstance(data,str):
        raise ErroQuarentenaPAM("captura sem timestamp")
    try:captura=datetime.fromisoformat(data.replace("Z","+00:00"))
    except ValueError as exc:raise ErroQuarentenaPAM("captura inválida") from exc
    if captura.tzinfo is None or captura.utcoffset() is None:
        raise ErroQuarentenaPAM("captura sem timezone")
    direitos=candidato.get("evidencia_direitos_declarada")
    if not isinstance(direitos,str) or not 6<=len(direitos)<=160:
        raise ErroQuarentenaPAM("identificador de direitos declarado obrigatório")
    local=_path(raiz)
    objs=_pasta(local,"objetos_sha256")
    recibos=_pasta(local,"recibos")
    original=objs/(digest+".bin")
    # O limite é local, independente de tamanho máximo disponível na nuvem.
    soma=0
    for item in objs.iterdir():
        if item.is_symlink() or not item.is_file():
            raise ErroQuarentenaPAM("cofre contém link/objeto não regular")
        soma+=item.stat().st_size
        if soma>limite_total_bytes:
            raise ErroQuarentenaPAM("cofre excede quota local")
    if not original.exists() and soma+len(raw)>limite_total_bytes:
        raise ErroQuarentenaPAM("quota local insuficiente para bytes recebidos")
    # Manifesto imutável por URL/SHA/instante/tipo. Uma segunda captura
    # do mesmo conteúdo e outra data cria recibo novo, não substitui origem.
    manifesto={
        "schema":"nivon_ivo_pam_quarentena_v1",
        "dataset_id":"IBGE_PAM","fonte":"IBGE","tipo":kind,
        "url_declarada":url,"sha256":digest,"bytes":len(raw),
        "captura_declarada_em":captura.astimezone(timezone.utc).isoformat(),
        "referencia_direitos_declarada":direitos,
        "arquivo_bytes_relativo":"objetos_sha256/"+digest+".bin",
        "fonte_autenticada_externamente":False,
        "data_publicacao_atestada":False,
        "direitos_validados_externamente":False,
        "liberado_para_treino":False,
        "inscrito_no_ledger_canonico":False,
    }
    doc=(json.dumps(manifesto,sort_keys=True,ensure_ascii=False,
                    separators=(",",":"))+"\n").encode("utf-8")
    receipt_hash=hashlib.sha256(doc).hexdigest()
    novo_objeto=_gravar_uma_vez(original,raw)
    novo_recibo=_gravar_uma_vez(recibos/(receipt_hash+".json"),doc)
    return {
        "estado":"ARQUIVADO_EM_QUARENTENA_LOCAL_NAO_HOMOLOGADO",
        "sha256":digest,"recibo_sha256":receipt_hash,
        "bytes":len(raw),"novo_objeto":novo_objeto,"novo_recibo":novo_recibo,
        "objeto_relativo":manifesto["arquivo_bytes_relativo"],
        "recibo_relativo":"recibos/"+receipt_hash+".json",
        "captura_declarada_em":manifesto["captura_declarada_em"],
        "cofre_verificado_por_hash":True,
        "captura_remota_comprovada":False,
        "publicacao_oficial_comprovada":False,
        "treinamento_real_autorizado":False,
        "ledger_canonico_atualizado":False,
    }


def conferir_recibo_pam(*, raiz:str|Path, recibo_sha256:str)->dict:
    if (not isinstance(recibo_sha256,str) or len(recibo_sha256)!=64
            or any(c not in "0123456789abcdef" for c in recibo_sha256)):
        raise ErroQuarentenaPAM("hash de recibo inválido")
    local=_path(raiz)
    path=local/"recibos"/(recibo_sha256+".json")
    if path.is_symlink() or not path.is_file():
        raise ErroQuarentenaPAM("recibo não encontrado ou symlink")
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=recibo_sha256:
        raise ErroQuarentenaPAM("recibo alterado após arquivamento")
    try:doc=json.loads(raw)
    except (ValueError,UnicodeError) as exc:
        raise ErroQuarentenaPAM("manifesto não é JSON válido") from exc
    if (not isinstance(doc,dict) or doc.get("schema")!="nivon_ivo_pam_quarentena_v1"
            or doc.get("liberado_para_treino") is not False
            or doc.get("inscrito_no_ledger_canonico") is not False):
        raise ErroQuarentenaPAM("manifesto com estado indevido")
    digest=doc.get("sha256")
    if (not isinstance(digest,str) or len(digest)!=64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise ErroQuarentenaPAM("hash de arquivo inválido")
    if doc.get("arquivo_bytes_relativo")!="objetos_sha256/"+digest+".bin":
        raise ErroQuarentenaPAM("caminho do objeto adulterado")
    obj=local/"objetos_sha256"/(digest+".bin")
    if obj.is_symlink() or not obj.is_file():
        raise ErroQuarentenaPAM("objeto indisponível")
    body=obj.read_bytes()
    if len(body)!=doc.get("bytes") or hashlib.sha256(body).hexdigest()!=digest:
        raise ErroQuarentenaPAM("bytes originais não correspondem ao manifesto")
    return {"estado":"QUARENTENA_HASH_CONFERIDO_NAO_HOMOLOGADO",
            "sha256":digest,"recibo_sha256":recibo_sha256,
            "bytes":len(body),"direitos_homologados":False,
            "origem_publicacao_autenticada":False,
            "modelo_treinavel":False}
