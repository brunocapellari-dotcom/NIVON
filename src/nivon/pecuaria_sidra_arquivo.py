"""Arquivo local append-only de EVIDENCIAS BRUTAS SIDRA, nunca fonte homologada.

Recebe exclusivamente bytes ja obtidos fora deste modulo. Nao acessa rede,
nao infere IDs oficiais nem autentica que bytes vieram de um servidor.
Banco SQLite local explicito; nao empacotar bancos em repositório publico.
"""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from .cadeias_adicionais import TABELAS_SIDRA, _instante
from .motores import DadoInvalido, validar_fonte

_SCHEMA = """
CREATE TABLE IF NOT EXISTS capturas_sidra (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 especie TEXT NOT NULL, tabela_sidra TEXT NOT NULL,
 url_valores TEXT NOT NULL, url_metadados TEXT NOT NULL,
 publicacao_declarada TEXT NOT NULL, coleta_declarada TEXT NOT NULL,
 sha256_valores TEXT NOT NULL, sha256_metadados TEXT NOT NULL,
 bruto_valores BLOB NOT NULL, bruto_metadados BLOB NOT NULL,
 status TEXT NOT NULL CHECK(status='ARQUIVADO_NAO_HOMOLOGADO'),
 UNIQUE(especie, tabela_sidra, url_valores, url_metadados,
        coleta_declarada)
);
CREATE TRIGGER IF NOT EXISTS sidra_sem_update
 BEFORE UPDATE ON capturas_sidra BEGIN
 SELECT RAISE(ABORT, 'append_only');
 END;
CREATE TRIGGER IF NOT EXISTS sidra_sem_delete
 BEFORE DELETE ON capturas_sidra BEGIN
 SELECT RAISE(ABORT, 'append_only');
 END;
"""


def _validar_url(url, *, tabela, metadados):
    if not isinstance(url, str) or len(url) > 1000:
        raise DadoInvalido("URL de origem SIDRA ausente ou excessiva")
    parts = urlsplit(url)
    host = "servicodados.ibge.gov.br" if metadados else "apisidra.ibge.gov.br"
    if (parts.scheme != "https" or parts.netloc != host
        or parts.query or parts.fragment or "\\" in parts.path
        or "%" in parts.path):
        raise DadoInvalido("URL de evidencia nao canonicamente oficial")
    if metadados:
        if parts.path != f"/api/v3/agregados/{tabela}/metadados":
            raise DadoInvalido("metadados de tabela distinta")
    elif not re.fullmatch(rf"/values/t/{tabela}/(?:[a-zA-Z0-9,/_-]+)", parts.path):
        raise DadoInvalido("consulta values fora da tabela SIDRA")
    return url


def _conteudo(bruto, *, tipo, max_bytes, tabela):
    if not isinstance(bruto, bytes) or not 2 <= len(bruto) <= max_bytes:
        raise DadoInvalido("conteudo vazio, nao binario ou maior que limite")
    try:
        obj = json.loads(bruto.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise DadoInvalido("JSON nao valido") from exc
    # Checagem apenas estrutural: nenhuma afirmacao de schema oficial.
    if tipo == "valores" and (not isinstance(obj, list) or len(obj) < 2
                               or not isinstance(obj[0], dict)
                               or not isinstance(obj[1], dict)):
        raise DadoInvalido("estrutura de valores nao e lista SIDRA h/y")
    if tipo == "metadados" and (not isinstance(obj, dict)
                                or str(obj.get("id", "")) != tabela):
        raise DadoInvalido("metadata de agregado sem ID coincidente com tabela")
    return sha256(bruto).hexdigest()


def _abrir(path):
    if not isinstance(path, (str, Path)):
        raise DadoInvalido("caminho local SQLite obrigatorio")
    p = Path(path).expanduser()
    if p.is_symlink() or not p.parent.is_dir() or p.parent.is_symlink():
        raise DadoInvalido("SQLite: caminho inseguro ou diretorio ausente")
    if p.exists() and not p.is_file():
        raise DadoInvalido("SQLite deve ser arquivo regular")
    cx = sqlite3.connect(str(p), timeout=5)
    esperado = ("especie", "tabela_sidra", "url_valores",
                "url_metadados", "coleta_declarada")

    def indice_canonico():
        indices = cx.execute("PRAGMA index_list(capturas_sidra)").fetchall()
        for indice in indices:
            if not indice[2]:
                continue
            nome = indice[1].replace('"', '""')
            colunas = tuple(row[2] for row in
                cx.execute('PRAGMA index_info("' + nome + '")').fetchall())
            if colunas == esperado:
                return True
        return False

    try:
        # IMPORTANTE: validar schema legado ANTES de executescript, pois
        # CREATE TRIGGER alteraria o banco mesmo quando a migracao e negada.
        existe = cx.execute("""SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='capturas_sidra'""").fetchone()
        if existe and not indice_canonico():
            raise DadoInvalido(
                "esquema SIDRA legado sem unicidade de captura; migracao auditada necessaria")
        cx.executescript(_SCHEMA)
        if not indice_canonico():
            raise DadoInvalido("esquema SIDRA nao possui indice canonico")
        return cx
    except Exception:
        cx.close()
        raise


def arquivar_pacote_sidra_offline(
    *, banco, especie, tabela_sidra, bruto_valores, bruto_metadados,
    url_valores, url_metadados, publicacao_declarada, coleta_declarada,
    status_fonte, operacoes_autorizadas,
    max_valores_bytes=4_000_000, max_metadados_bytes=1_000_000,
):
    """Guardar bytes e metadados em SQLite com hashes; status SEM homologacao.

    'publicacao_declarada' nao prova vintage historico. Hash nao prova origem
    remota: identificacao de URL e declaracao de direitos sao condicionais.
    """
    if TABELAS_SIDRA.get(especie) != tabela_sidra:
        raise DadoInvalido("especie/tabela incompativeis")
    if (type(max_valores_bytes) is not int or not 1 <= max_valores_bytes <= 4_000_000
        or type(max_metadados_bytes) is not int or not 1 <= max_metadados_bytes <= 1_000_000):
        raise DadoInvalido("limites invalidos")
    validar_fonte(status=status_fonte, operacao="LEITURA",
                  operacoes_autorizadas=operacoes_autorizadas)
    if "ARMAZENAMENTO" not in operacoes_autorizadas:
        raise PermissionError("ARMAZENAMENTO de dados nao autorizado")
    _validar_url(url_valores, tabela=tabela_sidra, metadados=False)
    _validar_url(url_metadados, tabela=tabela_sidra, metadados=True)
    pub = _instante(publicacao_declarada, "publicacao")
    col = _instante(coleta_declarada, "coleta")
    if pub > col:
        raise DadoInvalido("publicacao declarada depois da coleta")
    hash_v = _conteudo(bruto_valores, tipo="valores", max_bytes=max_valores_bytes, tabela=tabela_sidra)
    hash_m = _conteudo(bruto_metadados, tipo="metadados", max_bytes=max_metadados_bytes, tabela=tabela_sidra)
    parametros = (
        especie, tabela_sidra, url_valores, url_metadados,
        pub.isoformat(), col.isoformat(), hash_v, hash_m,
        bruto_valores, bruto_metadados, "ARQUIVADO_NAO_HOMOLOGADO"
    )
    with closing(_abrir(banco)) as cx, cx:
        # Uma captura possui identidade (origem+instante da coleta). Nunca
        # mascarar alteracao de publicacao, hash ou payload como idempotencia.
        identidade = (especie, tabela_sidra, url_valores, url_metadados,
                      col.isoformat())
        consulta = """SELECT id, publicacao_declarada, sha256_valores,
                             sha256_metadados FROM capturas_sidra
                      WHERE especie=? AND tabela_sidra=? AND url_valores=?
                        AND url_metadados=? AND coleta_declarada=?"""
        anterior = cx.execute(consulta, identidade).fetchone()
        if anterior is not None and (
                anterior[1] != pub.isoformat() or anterior[2] != hash_v
                or anterior[3] != hash_m):
            raise DadoInvalido("captura conflitante com mesmo instante de coleta")
        cx.execute("""INSERT OR IGNORE INTO capturas_sidra
           (especie, tabela_sidra, url_valores, url_metadados,
            publicacao_declarada, coleta_declarada, sha256_valores,
            sha256_metadados, bruto_valores, bruto_metadados, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", parametros)
        registro = cx.execute(consulta, identidade).fetchone()
        if registro is not None and (
                registro[1] != pub.isoformat() or registro[2] != hash_v
                or registro[3] != hash_m):
            raise DadoInvalido("captura concorrente com metadados conflitantes")
    if not registro:
        raise DadoInvalido("captura nao registrada")
    return {"id": registro[0], "especie": especie, "tabela_sidra": tabela_sidra,
            "sha256_valores": hash_v, "sha256_metadados": hash_m,
            "coleta_declarada": col.isoformat(),
            "status": "ARQUIVADO_NAO_HOMOLOGADO", "dados_reais_verificados": False,
            "timestamps_autenticados": False, "previsao_homologada": False}


def recuperar_pacote_sidra_offline(*, banco, id_captura: int):
    """Recuperacao byte-a-byte, conferindo metadados e origem DECLARADA."""
    if type(id_captura) is not int or id_captura < 1:
        raise DadoInvalido("id de captura invalido")
    with closing(_abrir(banco)) as cx:
        row = cx.execute("""SELECT especie, tabela_sidra,
            url_valores, url_metadados,
            publicacao_declarada, coleta_declarada,
            sha256_valores, sha256_metadados,
            bruto_valores, bruto_metadados, status
            FROM capturas_sidra WHERE id=?""", (id_captura,)).fetchone()
    if row is None:
        raise DadoInvalido("captura nao encontrada")
    (especie, tabela, url_v, url_m, publicacao, coleta,
     hash_v, hash_m, bruto_v, bruto_m, estado) = row
    if TABELAS_SIDRA.get(especie) != tabela or estado != "ARQUIVADO_NAO_HOMOLOGADO":
        raise DadoInvalido("identidade/status do arquivo corrompidos")
    _validar_url(url_v, tabela=tabela, metadados=False)
    _validar_url(url_m, tabela=tabela, metadados=True)
    pub, col = _instante(publicacao, "publicacao"), _instante(coleta, "coleta")
    if pub > col:
        raise DadoInvalido("cronologia de arquivo corrompida")
    if (_conteudo(bruto_v, tipo="valores", max_bytes=4_000_000, tabela=tabela) != hash_v
        or _conteudo(bruto_m, tipo="metadados",
                    max_bytes=1_000_000, tabela=tabela) != hash_m):
        raise DadoInvalido("integridade de evidencia corrompida")
    return {
        "id_captura": id_captura,
        "especie": especie, "tabela_sidra": tabela,
        "url_valores": url_v, "url_metadados": url_m,
        "publicacao_declarada": publicacao, "coleta_declarada": coleta,
        "bruto_valores": bruto_v, "bruto_metadados": bruto_m,
        "sha256_valores": hash_v, "sha256_metadados": hash_m,
        "status": estado, "dados_reais_verificados": False,
        "timestamps_autenticados": False,
    }
