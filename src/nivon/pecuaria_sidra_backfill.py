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
from .pecuaria_sidra_vintages import historico_sidra_asof
from .pecuaria_sidra_quarentena import _checar_semantica_extrato
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
    """Reconstroi estado e TODAS as revisoes arquivadas ate a data de corte.

    A primeira coleta identifica quando o NIVON soube de uma edicao, NAO
    a data de publicacao historica pelo IBGE. Um backfill posterior nunca
    pode aparecer em cortes anteriores à coleta. Preserva proveniencia.
    """
    periodos = _validar_periodos(periodos)
    if especie not in TABELAS_SIDRA:
        raise DadoInvalido("especie desconhecida")
    corte = _instante(corte_asof, "corte_asof")
    tabela = TABELAS_SIDRA[especie]
    placeholders = ",".join("?" for _ in periodos)
    sql = """SELECT id, periodo, territorio, primeira_coleta_em
        FROM valores_pecuaria_quarentena
        WHERE especie=? AND tabela_sidra=? AND periodo IN (""" + placeholders + """)
        ORDER BY id ASC LIMIT 501"""
    with closing(_conectar(banco, criar=False)) as cx:
        linhas = cx.execute(sql, (especie, tabela, *periodos)).fetchall()
    # Falha fechada se a base demandar paginacao para impedir omissao
    # silenciosa de revisoes antigas ou novas.
    if len(linhas) > 500:
        raise DadoInvalido("consulta excede 500 capturas; paginacao exigida")

    conhecidos = []
    for ident, periodo, territorio, primeira_coleta in linhas:
        if territorio not in ("BR", "UFS"):
            raise DadoInvalido("territorio invalido no historico SQLite")
        instante = _instante(primeira_coleta, "primeira_coleta_em")
        if instante <= corte:
            conhecidos.append((instante, ident, periodo, territorio))
    # Garante uma ordem causal reproduzivel na reconstrução.
    conhecidos.sort(key=lambda r: (r[0], r[1]))
    if len(conhecidos) > 300:
        raise DadoInvalido("limite de 300 capturas do motor vintage; paginacao exigida")

    mapa = contrato_sidra_observado(especie=especie, tabela_sidra=tabela)
    snapshots = []
    capturas = []
    vigentes = {}
    for instante, ident, periodo, territorio in conhecidos:
        recuperado = recuperar_values_quarentena(banco=banco, id_captura=ident)
        if (recuperado["especie"] != especie
            or recuperado["tabela_sidra"] != tabela
            or recuperado["periodo"] != periodo
            or recuperado["territorio"] != territorio
            or _instante(recuperado["primeira_coleta_em"],
                         "primeira_coleta_em") != instante):
            raise DadoInvalido("captura historica com identidade divergente")
        _checar_semantica_extrato(
            bruto=recuperado["bruto"], especie=especie, periodo=periodo)
        snapshot = normalizar_snapshot_sidra_abate(
            recuperado["bruto"], especie=especie, tabela_sidra=tabela,
            dimensoes=mapa["dimensoes"], totais=mapa["totais"],
            variaveis=mapa["variaveis"],
            publicacao=recuperado["primeira_coleta_em"],
            coleta=recuperado["primeira_coleta_em"],
            status_fonte="APROVADA",
            operacoes_autorizadas={"LEITURA", "ARMAZENAMENTO"})
        snapshots.append(snapshot)
        provenance = {
            "id": ident, "periodo": periodo, "territorio": territorio,
            "primeira_coleta_em": recuperado["primeira_coleta_em"],
            "sha256_bruto": recuperado["sha256_bruto"],
        }
        capturas.append(provenance)
        # A captura mais nova por coleta e território compõe o estado vigente;
        # TODAS as capturas são necessárias para contar revisões anteriores.
        chave = (periodo, territorio)
        atual = vigentes.get(chave)
        if atual is None or (instante, ident) > (atual[0], atual[1]):
            vigentes[chave] = (instante, ident, provenance)

    diagnostico = (diagnosticar_cobertura_abate(
        snapshots=snapshots, especie=especie, tabela_sidra=tabela,
        corte_asof=corte_asof) if snapshots else None)
    ultimas = [x[2] for _, x in sorted(vigentes.items())]
    # Retorno de revisões de valor/status mantém origem SHA, mas sua data
    # "publicacao_nova" no motor representa PRIMEIRA COLETA neste contexto.
    revisoes = [] if diagnostico is None else historico_sidra_asof(
        snapshots=snapshots, especie=especie, tabela_sidra=tabela,
        corte_asof=corte_asof)["revisoes"]
    for revisao in revisoes:
        revisao["data_temporal_representa"] = "PRIMEIRA_COLETA_NIVON"
        revisao["publicacao_ibge_confirmada"] = False
    return {
        "especie": especie, "tabela_sidra": tabela,
        "periodos_solicitados": periodos, "corte_asof": corte_asof,
        "capturas_conhecidas_no_corte": ultimas,
        "capturas_historicas_no_corte": capturas,
        "capturas_superadas_no_corte": len(capturas) - len(ultimas),
        "total_revisoes_observadas": len(revisoes),
        "revisoes_observadas": revisoes,
        "diagnostico": diagnostico,
        "status": "RECONSTRUCAO_POR_COLETA_NAO_HOMOLOGADA",
        "publicacao_historica_conhecida": False,
        "metadados_v3_verificados": False,
        "publicacao_permitida": False,
    }


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
    parser.add_argument("--consultar",action="store_true",
                        help="consulta historica read-only, sem rede e sem escrita")
    parser.add_argument("--especie",choices=("BOVINO","SUINO","FRANGO"))
    parser.add_argument("--corte",help="ISO 8601 com fuso, exigido em --consultar")
    args=parser.parse_args(argv)
    try:
        if args.consultar:
            if (not args.banco or not args.especie or not args.corte
                or args.rede or args.gravar):
                raise DadoInvalido(
                    "--consultar exige --banco --especie --corte e proibe --rede/--gravar")
            result=consultar_backfill_quarentena(
                banco=args.banco,especie=args.especie,
                periodos=args.periodo,corte_asof=args.corte)
        else:
            if args.especie or args.corte:
                raise DadoInvalido("--especie/--corte apenas em --consultar")
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
