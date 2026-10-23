"""Backfill controlado SIDRA em quarentena e consulta temporal sem look-ahead.

Captura lotes completos de ate 4 trimestres (6 GETs por trimestre) com
preflight integral e UMA transacao SQLite opcional. Reprocessamento por hash.
Todos os registros seguem sem metadados oficiais e sem homologacao.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

from .cadeias_adicionais import TABELAS_SIDRA, _instante
from .motores import DadoInvalido
from .pecuaria_sidra_quarentena import (
    _preparar, _salvar_capturas_atomicas, _conectar, _validar_periodo,
    recuperar_values_quarentena, _url_values,
)
from .pecuaria_sidra_sondagem import _requisicao_https
from .pecuaria_sidra_mapa_observado import contrato_sidra_observado
from .pecuaria_sidra_abate import normalizar_snapshot_sidra_abate
from .pecuaria_sidra_reconciliacao import diagnosticar_cobertura_abate
from contextlib import closing


def _validar_periodos(periodos):
    if not isinstance(periodos, (tuple,list)) or not 1 <= len(periodos) <= 4:
        raise DadoInvalido("backfill aceita entre 1 e 4 trimestres por lote")
    result = []
    for p in periodos:
        _validar_periodo(p)
        if p in result:
            raise DadoInvalido("competencia trimestral duplicada")
        result.append(p)
    return sorted(result)


def executar_backfill_quarentena(*, periodos, rede=False,
                                 direitos_confirmados=False, gravar=False,
                                 banco=None, timeout=8, transporte=None):
    """Consultar 6 a 24 extratos oficiais ou simulados, sem job agendado.

    A publicacao original do IBGE nao pode ser inferida destes extratos.
    O mapeamento de cada trimestre e conferido por schema real de values.
    """
    periodos = _validar_periodos(periodos)
    if type(rede) is not bool or type(gravar) is not bool or type(direitos_confirmados) is not bool:
        raise DadoInvalido("flags nao booleanas")
    if type(timeout) not in (int,float) or isinstance(timeout,bool) or not 1 <= timeout <= 10:
        raise DadoInvalido("timeout fora do limite")
    if gravar and (not direitos_confirmados or banco is None):
        raise PermissionError("backfill gravado exige direitos e SQLite explicitos")
    if not rede and transporte is None:
        return {"status":"PLANEJADO_SEM_REDE", "periodos":periodos,
                "n_requisicoes":6*len(periodos),
                "urls_previstas":[_url_values(TABELAS_SIDRA[e],p,geo)
                    for p in periodos for e in ("BOVINO","SUINO","FRANGO")
                    for geo in ("BR","UFS")],
                "persistido":False, "homologado":False}
    if not direitos_confirmados:
        raise PermissionError("consulta requer declaracao de direitos")
    fonte = transporte if transporte is not None else _requisicao_https
    capturas=[]
    for p in periodos:
        capturas.extend(_preparar(periodo=p,transporte=fonte,timeout=timeout))
    # Garante que nao persista nada se houver resposta invalida ou parcial.
    if len(capturas) != 6*len(periodos):
        raise DadoInvalido("backfill parcial, transacao proibida")
    ids=_salvar_capturas_atomicas(banco=banco,capturas=capturas) if gravar else []
    return {"status":"BACKFILL_EM_QUARENTENA_SEM_HOMOLOGACAO",
            "periodos":periodos,"n_requisicoes":6*len(periodos),
            "n_capturas":len(capturas),"ids_capturas":ids,
            "persistido":gravar,"rede_executada":bool(rede and transporte is None),
            "por_periodo":{p:{
                "capturas":sum(c["periodo"]==p for c in capturas),
                "registros":sum(len(c["snapshot"]["observacoes"])
                                  for c in capturas if c["periodo"]==p),
                "censuras":sum(len(c["snapshot"]["linhas_indisponiveis"])
                                  for c in capturas if c["periodo"]==p)}
                for p in periodos},
            "observacoes_reais_homologadas":False,
            "revisoes_historicas_autenticadas":False,
            "publicacao_permitida":False}


def consultar_backfill_quarentena(*, banco, especie, periodos, corte_asof):
    """As-of SÓ por momento da primeira coleta efetivamente arquivada.

    Nunca inventa snapshots anteriores à primeira coleta. Para um mesmo
    trimestre/territorio escolhe-se a última versão conhecida no corte,
    preservando os dois totais (BR vs UFs) de forma independente.
    """
    periodos=_validar_periodos(periodos)
    if especie not in TABELAS_SIDRA:
        raise DadoInvalido("especie desconhecida")
    corte=_instante(corte_asof,"corte_asof")
    tab=TABELAS_SIDRA[especie]
    marcas=",".join("?" for _ in periodos)
    consulta = """SELECT id, periodo, territorio, primeira_coleta_em
        FROM valores_pecuaria_quarentena WHERE especie=? AND tabela_sidra=?
        AND periodo IN (""" + marcas + """)
        ORDER BY id DESC LIMIT 501"""
    with closing(_conectar(banco,criar=False)) as cx:
        rows = cx.execute(consulta,(especie,tab,*periodos)).fetchall()
    # Sem truncamento silencioso de revisoes historicas; exige paginacao
    # explicita quando o volume crescer, mantendo o status nao homologado.
    if len(rows) > 500:
        raise DadoInvalido("consulta excede 500 capturas; paginacao exigida")
    escolhidas={}
    for ident,periodo,geo,coleta in rows:
        if periodo not in periodos or geo not in ("BR","UFS"):
            continue
        instante=_instante(coleta,"primeira_coleta_em")
        if instante > corte:
            continue
        chave=(periodo,geo)
        vigente=escolhidas.get(chave)
        if vigente is None or (instante,ident) > (vigente[0],vigente[1]):
            escolhidas[chave]=(instante,ident)
    mapa=contrato_sidra_observado(especie=especie,tabela_sidra=tab)
    snapshots=[]
    origem=[]
    for (periodo,geo),(quando,ident) in sorted(escolhidas.items()):
        cap=recuperar_values_quarentena(banco=banco,id_captura=ident)
        if cap["especie"] != especie or cap["periodo"] != periodo or cap["territorio"] != geo:
            raise DadoInvalido("captura recuperada diverge de identidade")
        # A publicacao real nao foi autenticada. A primeira coleta funciona
        # apenas como piso conservador de conhecimento para as-of.
        snap=normalizar_snapshot_sidra_abate(
            cap["bruto"], especie=especie,tabela_sidra=tab,
            dimensoes=mapa["dimensoes"],totais=mapa["totais"],
            variaveis=mapa["variaveis"], publicacao=cap["primeira_coleta_em"],
            coleta=cap["primeira_coleta_em"],status_fonte="APROVADA",
            operacoes_autorizadas={"LEITURA","ARMAZENAMENTO"})
        snapshots.append(snap)
        origem.append({"id":ident,"periodo":periodo,"territorio":geo,
                      "primeira_coleta_em":cap["primeira_coleta_em"],
                      "sha256_bruto":cap["sha256_bruto"]})
    diag=(diagnosticar_cobertura_abate(
        snapshots=snapshots, especie=especie, tabela_sidra=tab,
        corte_asof=corte_asof) if snapshots else None)
    return {"especie":especie,"tabela_sidra":tab,
            "periodos_solicitados":periodos, "corte_asof":corte_asof,
            "capturas_conhecidas_no_corte":origem,
            "diagnostico":diag,
            "status":"RECONSTRUCAO_POR_COLETA_NAO_HOMOLOGADA",
            "publicacao_historica_conhecida":False,
            "metadados_v3_verificados":False,
            "publicacao_permitida":False}


def main(argv=None):
    import argparse
    import sys
    parser=argparse.ArgumentParser(description="SIDRA: backfill em quarentena, sem agendamento")
    parser.add_argument("--periodo", action="append", required=True,
                        help="AAA A0T sem espacos; repetir ate quatro vezes")
    parser.add_argument("--rede",action="store_true")
    parser.add_argument("--confirmar-direitos",action="store_true")
    parser.add_argument("--gravar",action="store_true")
    parser.add_argument("--banco")
    args=parser.parse_args(argv)
    try:
        result=executar_backfill_quarentena(
            periodos=args.periodo,rede=args.rede,
            direitos_confirmados=args.confirmar_direitos,
            gravar=args.gravar,banco=args.banco)
        print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))
        return 0
    except (DadoInvalido, PermissionError, ValueError, OSError) as exc:
        print(json.dumps({"status":"BLOQUEADO","erro":type(exc).__name__,
                          "detalhe":str(exc)[:200]},ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
