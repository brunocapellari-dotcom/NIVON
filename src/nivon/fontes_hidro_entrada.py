"""Adaptadores de origem INMET ZIP anual e ANA telemetria para o acervo horário.

Nenhuma coleta real é iniciada por padrão. Os leitores/normalizadores oficiais
já existentes são a única autoridade de parsing. Fonte ZIP e token ANA não
devem ser confundidos com prova histórica de publicação da medida.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

from .inmet_historico import inspecionar_arquivo, obter_csv_em_memoria
from .pipeline_medicoes_horarias import (
    ErroPipelineAmbiental, preparar_arquivo_medicoes,
)
from .ana_hidrowebservice import (
    BASE as ANA_BASE, construir_consulta_adotada, efetuar_request,
)


def _sha_arquivo(caminho, *, max_bytes=1_000_000_000):
    p=Path(caminho)
    if p.is_symlink() or not p.is_file() or not 0<p.stat().st_size<=max_bytes:
        raise ErroPipelineAmbiental("arquivo de origem ausente, symlink ou excessivo")
    digest=sha256()
    with p.open("rb") as fp:
        while piece:=fp.read(1024*1024):
            digest.update(piece)
    if p.stat().st_size>max_bytes:
        raise ErroPipelineAmbiental("arquivo mudou durante a leitura")
    return digest.hexdigest()


def preparar_inmet_zip_local(
    *, caminho_zip, ano, membro_csv, estacao_id,
    coletado_em, classe="EXTERNO_NAO_HOMOLOGADO",
    observado_nivon_em=None,
):
    """ZIP oficial local -> membro CSV -> parser horário -> pacote para SQLite.

    O ZIP pai será copiado de forma imutável para o arquivo RAW pelo pipeline
    transacional, com seu SHA e vínculo de membro preservados no SQLite.
    A função de preparo sozinha nunca grava bytes no disco.
    """
    original = Path(caminho_zip)
    if original.suffix.lower()!=".zip":
        raise ErroPipelineAmbiental("somente ZIP local de dados históricos INMET")
    zip_sha=_sha_arquivo(original)
    inventory=inspecionar_arquivo(original,ano=ano)
    if membro_csv not in {x["nome"] for x in inventory["csv"]}:
        raise ErroPipelineAmbiental("membro CSV não consta do inventário seguro")
    raw=obter_csv_em_memoria(original,ano=ano,nome=membro_csv)
    # O inventário e o membro foram validados e lidos; arquivo ZIP externo
    # deve ser imutável durante a operação. Revalidar digest ao fim.
    if _sha_arquivo(original)!=zip_sha:
        raise ErroPipelineAmbiental("ZIP alterado durante inspeção/leitura")
    result=preparar_arquivo_medicoes(
        formato="INMET_HORARIO_CSV",raw=raw,estacao_id=estacao_id,
        ano=ano,zona=None,coletado_em=coletado_em,
        classe=classe,observado_nivon_em=observado_nivon_em)
    result["container_origem"]={
        "tipo":"ZIP_INMET_ANUAL","parent_sha256":zip_sha,
        "membro":membro_csv,"membro_sha256":result["sha256"],
        "arquivar_zip_pai_obrigatorio":True,
        "arquivo_zip_local":str(original.resolve()),
        "integridade_zip_externa_revalidada":True,
    }
    return result


def _exigir_ana_permitida():
    from .catalogo_fontes import carregar_catalogo
    c=carregar_catalogo()
    matches=[d for d in c["datasets"] if d["id"]=="ANA_HIDRO"]
    if len(matches)!=1:
        raise PermissionError("ANA: cadastro canônico ausente/duplicado")
    d=matches[0]
    if (d.get("enabled") is not True or
        d.get("collection_authorized") is not True or
        d.get("stage") != "REAL_SNAPSHOT_TESTED"):
        raise PermissionError(
            "ANA: catálogo não homologado impede conexão SSO real")
    return True


def preparar_ana_consulta_adotada(
    *, estacao_id, zona_estacao, token, data_busca, coletado_em,
    intervalo="HORA_1", transporte=None, simular=False,
    observado_nivon_em=None,
):
    """Executa request ANA somente em simulação injetada ou homologação.

    Credenciais/token nunca são retornados, persistidos ou incluídos no
    diagnóstico. Modo real depende da aprovação do catálogo canônico.
    Mesmo com HTTP real o status do dado segue NAO_HOMOLOGADO.
    """
    if simular is True:
        if transporte is None:
            raise PermissionError("simulação exige transporte injetado")
        classe="SINTETICO"
    else:
        if transporte is not None:
            raise PermissionError("transporte customizado só em simulação")
        _exigir_ana_permitida()
        classe="EXTERNO_NAO_HOMOLOGADO"
    req=construir_consulta_adotada(
        estacao=estacao_id,token=token,data_busca=data_busca,
        intervalo=intervalo)
    raw=efetuar_request(req,habilitar_rede=True,transporte=transporte)
    entry=preparar_arquivo_medicoes(
        formato="ANA_ADOTADA_JSON",raw=raw,estacao_id=estacao_id,
        ano=None,zona=zona_estacao,coletado_em=coletado_em,
        classe=classe,observado_nivon_em=observado_nivon_em)
    entry["consulta_api"]={
        "endpoint":ANA_BASE+"/HidroinfoanaSerieTelemetricaAdotada/v1",
        "codigo_estacao":estacao_id,
        "data_busca":data_busca,
        "intervalo":intervalo,
        "token_armazenado":False,
        "resposta_sha256":entry["sha256"],
        "testado_por_transporte_simulado":simular is True,
        "ingestao_real_homologada":False,
    }
    return entry
