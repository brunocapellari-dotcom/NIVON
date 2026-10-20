"""Histórico anual oficial INMET 2000–2026: plano e inspeção ZIP offline.

Nunca baixa arquivo ou extrai um ZIP no sistema. Listagem anual observada
em portal.inmet.gov.br/dadoshistoricos/. Condições comerciais pendentes.
"""
from __future__ import annotations
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

class ErroHistoricoINMET(ValueError):
    pass

INDICE_OFICIAL="https://portal.inmet.gov.br/dadoshistoricos/"
ARQUIVO_BASE="https://portal.inmet.gov.br/uploads/dadoshistoricos/"
PRIMEIRO_ANO_PUBLICADO=2000
ULTIMO_ANO_CONFIRMANDO_INDICE=2026
MAX_ARQUIVO_COMPACTADO=1_000_000_000
MAX_MEMBROS=6000
MAX_DESCOMPACTADO=2_000_000_000
MAX_MEMBRO_CSV=18_000_000

def planejar_historico(*,ano_inicial:int,ano_final:int)->list[dict]:
    """URLs apenas do padrão que aparece no índice oficial, sem download."""
    if type(ano_inicial) is not int or type(ano_final) is not int or not (
        PRIMEIRO_ANO_PUBLICADO<=ano_inicial<=ano_final<=ULTIMO_ANO_CONFIRMANDO_INDICE
    ):
        raise ErroHistoricoINMET("ano fora do índice anual verificado")
    return [{"dataset_id":"INMET_ESTACOES","ano":ano,
             "arquivo_url":ARQUIVO_BASE+str(ano)+".zip",
             "pagina_oficial":INDICE_OFICIAL,
             "coleta_autorizada":False,"executar":False,
             "licenca_armazenamento":"AGUARDA_REVISAO",
             "tipo":"ZIP_ANUAL_ESTACOES_AUTOMATICAS"} for ano in range(ano_inicial,ano_final+1)]

def _validar_nome(raw: str) -> str:
    if not isinstance(raw,str) or not raw or "\x00" in raw or "\\" in raw:
        raise ErroHistoricoINMET("nome inseguro")
    path=PurePosixPath(raw)
    if path.is_absolute() or any(part in (".","..") for part in raw.split("/")) or re.match(r"^[A-Za-z]:",raw):
        raise ErroHistoricoINMET("caminho absoluto ou traversal dentro do ZIP")
    if len(raw)>260:
        raise ErroHistoricoINMET("nome muito longo")
    return raw

def _inventario(zipfile_obj):
    members=zipfile_obj.infolist()
    if not members or len(members)>MAX_MEMBROS:
        raise ErroHistoricoINMET("número de membros ZIP fora do limite")
    seen=set();total=0;csv=[]
    for member in members:
        name=_validar_nome(member.filename)
        if name in seen:
            raise ErroHistoricoINMET("nome duplicado no arquivo ZIP")
        seen.add(name)
        mode=(member.external_attr>>16)&0xFFFF
        if stat.S_ISLNK(mode):
            raise ErroHistoricoINMET("link simbólico ZIP proibido")
        if member.flag_bits & 1:
            raise ErroHistoricoINMET("ZIP criptografado não aceito")
        if member.is_dir():
            continue
        if member.file_size<0 or member.compress_size<0:
            raise ErroHistoricoINMET("tamanho inválido")
        total+=member.file_size
        if total>MAX_DESCOMPACTADO:
            raise ErroHistoricoINMET("descompactado total excede limite")
        if member.file_size>MAX_MEMBRO_CSV:
            raise ErroHistoricoINMET("membro grande demais")
        if member.file_size and member.file_size/max(1,member.compress_size)>500:
            raise ErroHistoricoINMET("razão de compressão suspeita")
        if name.lower().endswith(".csv"):
            csv.append({"nome":name,"bytes":member.file_size,"comprimidos":member.compress_size})
    if not csv:
        raise ErroHistoricoINMET("nenhum CSV encontrado; layout não homologado")
    return csv,total,len(members)

def inspecionar_arquivo(caminho: str | Path, *, ano:int)->dict:
    """Inventário local, sem extrair arquivos ou inferir schema meteorológico."""
    if type(ano) is not int or not PRIMEIRO_ANO_PUBLICADO<=ano<=ULTIMO_ANO_CONFIRMANDO_INDICE:
        raise ErroHistoricoINMET("ano de fonte inválido")
    path=Path(caminho)
    if path.is_symlink() or not path.is_file() or path.suffix.lower()!=".zip":
        raise ErroHistoricoINMET("ZIP local regular obrigatório, symlink proibido")
    if not 0<path.stat().st_size<=MAX_ARQUIVO_COMPACTADO:
        raise ErroHistoricoINMET("arquivo ZIP maior do que o limite")
    try:
        with zipfile.ZipFile(path,mode="r") as z:
            csv,total,membros=_inventario(z)
    except (zipfile.BadZipFile,EOFError,RuntimeError) as exc:
        raise ErroHistoricoINMET("ZIP corrompido ou inválido") from exc
    return {"dataset_id":"INMET_ESTACOES","ano":ano,"arquivos_csv":len(csv),
            "total_membros":membros,"total_descompactado_bytes":total,
            "csv":csv,"leitura_executada":False,"arquivo_extraido":False,
            "schema_homologado":False,"coleta_automatizada":False,
            "alerta":"Não assumir que uma hora de chuva é chuva diária; data UTC e limites físicos exigem validação."}

def obter_csv_em_memoria(caminho:str|Path,*,nome:str,max_bytes:int=8_000_000)->bytes:
    """Leitura explícita somente de CSV; CRC pelo ZipFile.read; nunca escreve."""
    name=_validar_nome(nome)
    if not name.lower().endswith(".csv"):
        raise ErroHistoricoINMET("somente membros CSV")
    if type(max_bytes) is not int or not 0<max_bytes<=MAX_MEMBRO_CSV:
        raise ErroHistoricoINMET("limite de leitura inválido")
    inventory=inspecionar_arquivo(caminho,ano=PRIMEIRO_ANO_PUBLICADO)
    match=[x for x in inventory["csv"] if x["nome"]==name]
    if len(match)!=1 or match[0]["bytes"]>max_bytes:
        raise ErroHistoricoINMET("CSV inexistente ou maior que limite")
    try:
        with zipfile.ZipFile(caminho) as z:
            return z.read(name)
    except (zipfile.BadZipFile,RuntimeError,EOFError) as exc:
        raise ErroHistoricoINMET("CRC ou dados comprimidos inválidos") from exc
