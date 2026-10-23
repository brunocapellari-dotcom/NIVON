"""Pipeline SAGyP: metadados -> CSV -> RAW privado -> SQLite de quarentena.

Sem agendamento, API publica propria, migracao cloud ou publicacao. Operacoes
reais exigem direitos verificados e permissao explicita. Transporte injetavel
permite testes locais com fixtures sem rede.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import stat

from .argentina_agricultura import (
    ErroArgentina, RECURSOS, consultar_metadados, importar_csv_autorizado,
)
from .argentina_download_csv import baixar_csv_candidato


def _pasta_privada(pasta: Path) -> None:
    if pasta.is_symlink():
        raise ErroArgentina('destino de RAW simbolico')
    pasta.mkdir(mode=0o700,parents=True,exist_ok=True)
    st = pasta.stat()
    if not stat.S_ISDIR(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o700:
        raise ErroArgentina('pasta RAW exige modo 0700')
    if hasattr(os,'getuid') and st.st_uid != os.getuid():
        raise ErroArgentina('pasta RAW deve pertencer ao operador')


def guardar_raw_privado(*, dados: bytes, pasta: str | Path, digest: str) -> str:
    """RAW SHA-addressed, permissionado; colisao/alteracao nao e sobrescrita."""
    if not isinstance(dados, bytes) or sha256(dados).hexdigest() != digest:
        raise ErroArgentina('SHA declarado nao confere')
    dest = Path(pasta)
    _pasta_privada(dest)
    arquivo = dest / (digest+'.csv')
    if arquivo.is_symlink():
        raise ErroArgentina('arquivo RAW simbolico')
    if arquivo.exists():
        st = arquivo.stat()
        if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) != 0o600:
            raise ErroArgentina('RAW antigo exige arquivo privado regular')
        if sha256(arquivo.read_bytes()).hexdigest() != digest:
            raise ErroArgentina('RAW existente adulterado')
        return str(arquivo)
    flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os,'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    fd=os.open(str(arquivo),flags,0o600)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(dados)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        arquivo.unlink(missing_ok=True)
        raise
    return str(arquivo)


def coletar_estimativas_local(*, recurso: str, banco: str | Path, pasta_raw: str | Path,
                               executar: bool = False, direitos_coleta_verificados: bool = False,
                               direitos_armazenamento_verificados: bool = False,
                               buscar_metadados=consultar_metadados,
                               buscar_csv=baixar_csv_candidato) -> dict:
    """Executa uma safra de ponta a ponta em quarentena sem ativacao automatica."""
    if (executar is not True or direitos_coleta_verificados is not True
            or direitos_armazenamento_verificados is not True):
        raise PermissionError('execucao SAGyP exige ambos direitos e opt-in')
    if recurso not in RECURSOS:
        raise ErroArgentina('recurso nao catalogado')
    meta = buscar_metadados(recurso, executar=True)
    if meta.get('id') != RECURSOS[recurso] or meta.get('recurso') != recurso:
        raise ErroArgentina('identidade de metadados diferente do recurso')
    url = meta.get('url_candidata_nao_autorizada')
    if not isinstance(url,str):
        raise ErroArgentina('URL candidata ausente')
    captura = buscar_csv(recurso=recurso, url=url, executar=True,
                         direitos_coleta_verificados=True)
    if captura.get('recurso') != recurso or captura.get('fonte_url') != url:
        raise ErroArgentina('identidade de captura divergente')
    raw = captura.get('raw')
    digest = captura.get('sha256')
    if not isinstance(raw,bytes) or not isinstance(digest,str) or sha256(raw).hexdigest() != digest:
        raise ErroArgentina('captura sem integridade verificavel')
    instante = datetime.fromisoformat(captura['coletado_em'])
    if instante.tzinfo is None:
        raise ErroArgentina('timestamp da captura sem timezone')
    caminho_raw=guardar_raw_privado(dados=raw,pasta=pasta_raw,digest=digest)
    edicao = 'ARG_'+recurso.upper()+'_'+digest
    gravacao = importar_csv_autorizado(
        raw,banco=banco,recurso=recurso,edicao_id=edicao,
        origem_url=url,coletado_em=instante,direitos_armazenamento_verificados=True)
    return {
        'fonte':'ARG_SAGYP', 'recurso': recurso, 'edicao_id': edicao,
        'sha256': digest, 'raw_privado': caminho_raw, 'status': gravacao['status'],
        'publicacao_verificada': False, 'apto_publicacao': False,
        'coleta_utc': instante.astimezone(timezone.utc).isoformat(timespec='seconds'),
    }
