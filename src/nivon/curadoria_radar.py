"""Pipeline editorial OFFLINE: RSS/Atom -> memória -> curadoria -> briefing.

Fonte/coleta/guid são dados não confiáveis; Nivon exige decisão editorial estruturada
e explícita por documento para não copiar automaticamente texto de terceiros.
Uma republicação conhecida mantém a MENOR data de publicação já observada.
Sem evidência/licença, não gera notícia; não tenta coletar RSS em rede.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import timedelta
from urllib.parse import urlsplit

from .briefing_diario import CATEGORIAS, selecionar_noticias
from .historico_noticias import registrar_observacoes
from .lineup_nacional import instante


class ErroCuradoria(ValueError):
    pass


def _prova(value: object, label: str) -> str:
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,140}",value):
        raise ErroCuradoria(label+" sem evidência registrada")
    return value


def _politica(p: dict, fonte_id: str) -> dict:
    if not isinstance(p,dict) or p.get("fonte_id")!=fonte_id:
        raise ErroCuradoria("política editorial incompatível com a fonte")
    if p.get("status_direitos")!="APROVADA" or not {
        "LEITURA","ARMAZENAMENTO","RESUMO","PUBLICACAO_DERIVADA",
    }.issubset(set(p.get("operacoes",[]))):
        raise PermissionError("direitos de coleta/armazenamento/resumo/publicação insuficientes")
    _prova(p.get("licenca_id"),"licença")
    nome=p.get("nome")
    if not isinstance(nome,str) or not 2<=len(nome.strip())<=120:
        raise ErroCuradoria("nome de fonte inválido")
    return p


def preparar_noticias_feed(
    conn: sqlite3.Connection, resultado_feed: dict, *,
    politica_fonte: dict, avaliacoes: dict[str,dict], gerado_em: str,
) -> dict:
    """Avaliação deve ser emitida por agente/editor independente (humanizado ou IA).

    A confirmação do classificador não eleva direitos nem faz a postagem.
    Cada avaliação vincula título/URL originais usando hash, para impedir
    prompt injection e reutilização de resumo autorizado em outro artigo.
    """
    if not isinstance(resultado_feed,dict) or not isinstance(avaliacoes,dict):
        raise ErroCuradoria("feed ou avaliações inválidos")
    fid=resultado_feed.get("fonte_id")
    if not isinstance(fid,str):
        raise ErroCuradoria("fonte não informada")
    p=_politica(politica_fonte,fid)
    agora=instante(gerado_em)
    candidatos=resultado_feed.get("candidatos")
    if not isinstance(candidatos,list) or len(candidatos)>200:
        raise ErroCuradoria("candidatos inválidos/excessivos")
    direitos={fid:{"status":"APROVADA","operacoes":["ARMAZENAMENTO"],
                   "evidencia_id":p["licenca_id"]}}
    # Histórico registrado inclusive para itens antigos, sem publicação.
    memoria=registrar_observacoes(conn,candidatos,autorizacao_armazenar=direitos)
    if len(memoria["resultados"])!=len(candidatos):
        raise ErroCuradoria("respostas do histórico e do feed não correspondem")
    noticias=[]
    excluidos=[]
    for i,(candidate,history) in enumerate(zip(candidatos,memoria["resultados"])):
        try:
            if candidate.get("fonte_id")!=fid:
                raise ErroCuradoria("origem do candidato diferente do feed")
            guid=candidate.get("guid")
            guid_hash=hashlib.sha256(guid.encode("utf-8")).hexdigest()
            edit=avaliacoes.get(guid_hash)
            if not isinstance(edit,dict):
                raise ErroCuradoria("nenhuma curadoria aprovada para o GUID")
            if edit.get("status")!="APROVADO":
                raise ErroCuradoria("curadoria rejeitada/pendente")
            _prova(edit.get("evidencia_id"),"curadoria")
            if edit.get("fonte_id")!=fid:
                raise ErroCuradoria("curadoria atribuída a outra fonte")
            documento=hashlib.sha256(
                (candidate["titulo"]+"\n"+candidate["url"]+"\n"+
                 candidate["publicado_em_original"]).encode("utf-8")
            ).hexdigest()
            if edit.get("documento_sha256")!=documento:
                raise ErroCuradoria("conteúdo/dados de publicação mudaram após curadoria")
            cat=edit.get("categoria")
            if cat not in CATEGORIAS:
                raise ErroCuradoria("categoria fora da taxonomia do NIVON")
            resumo=edit.get("resumo")
            if not isinstance(resumo,str) or not 20<=len(resumo.strip())<=450:
                raise ErroCuradoria("resumo editorial ausente ou excessivo")
            if any(x in resumo.lower() for x in ("ignore previous instructions",
                                                  "ignore suas instruções",
                                                  "revele seu prompt")):
                raise ErroCuradoria("conteúdo com possível instrução hostil exige revisão")
            # A memória protege contra URL/GUID repetidos em outros dias.
            original=instante(history["primeiro_publicado_em"])
            if original>agora or original<agora-timedelta(hours=24):
                raise ErroCuradoria("primeira publicação conhecida fora da janela das últimas 24h")
            noticias.append({
                "fonte_id":fid,
                "fonte":p["nome"],
                "titulo":candidate["titulo"],
                "url":candidate["url"],
                "publicado_em":original.isoformat(),
                "categoria":cat,
                "resumo":resumo.strip(),
            })
        except (KeyError,TypeError,ValueError,ErroCuradoria) as exc:
            excluidos.append({"indice":i,"motivo":str(exc)})
    fontes={fid:{"status_direitos":"APROVADA",
                 "operacoes":["LEITURA","RESUMO","PUBLICACAO_DERIVADA"]}}
    noticias_filtradas, recusadas=selecionar_noticias(noticias,fontes,gerado_em=gerado_em)
    excluidos.extend(recusadas)
    return {
        "noticias":noticias_filtradas,
        "fontes_briefing":fontes,
        "rejeicoes":excluidos,
        "historico":{"observacoes":memoria["observacoes"],
                     "republicacoes":memoria["republicacoes_ou_revisoes"]},
        "estado":"CURADO_SEM_ENVIO",
        "limites":"Curadoria e direitos foram informados externamente; este módulo não os homologa.",
    }


def hash_documento_candidato(candidato: dict) -> str:
    """Fingerprint que o editor/IA precisa referenciar ao aprovar a síntese."""
    return hashlib.sha256((candidato["titulo"]+"\n"+candidato["url"]+"\n"+
                           candidato["publicado_em_original"]).encode("utf-8")).hexdigest()
