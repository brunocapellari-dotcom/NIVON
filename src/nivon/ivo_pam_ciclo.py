"""Executa um ciclo PAM completo: restaurar -> coletar -> auditar -> backup.

Projetado para job efêmero, com arquivo anterior explícito; não busca
arquivos remotos, não reinicia silenciosamente um histórico perdido e
não escreve na branch Git. Um pacote anterior é obrigatório após a
primeira inicialização para preservar vintages reais.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .ivo_pam_backup import ErroBackupPAM, criar_backup_pam, restaurar_backup_pam
from .ivo_pam_operacao import abrir_operacao_pam, executar_lote_pam
from .ivo_pam_qualidade import auditar_operacao_pam


def executar_ciclo_pam(*,saida, tarefas, modo="PUBLICO_IBGE",
                       arquivo_anterior=None, permitir_legado=False,
                       iniciar_novo=False, entrada=None, transporte=None)->dict:
    destino=Path(saida)
    if destino.exists() or destino.is_symlink() or not destino.parent.is_dir():
        raise ValueError("saída precisa ser diretório novo sob pai existente")
    if arquivo_anterior is None and iniciar_novo is not True:
        raise ErroBackupPAM("não iniciar histórico novo sem decisão explícita")
    if arquivo_anterior is not None and iniciar_novo:
        raise ErroBackupPAM("não pode importar e reiniciar no mesmo ciclo")
    destino.mkdir(mode=0o700)
    workspace=destino/"estado"
    if arquivo_anterior is not None:
        antes=restaurar_backup_pam(arquivo=arquivo_anterior,destino=workspace,
                                 permitir_legado=permitir_legado)
    else:
        workspace.mkdir(mode=0o700)
        antes={"estado":"PRIMEIRO_CICLO_EXPLICITAMENTE_INICIADO",
               "capturas":0,"vintages":0,"legado_sem_manifesto":False}
    db=abrir_operacao_pam(workspace/"pam.sqlite")
    try:
        rel=executar_lote_pam(db=db,raiz=workspace/"cofre",tarefas=tarefas,
             modo=modo,entrada=entrada,transporte=transporte)
        aud=auditar_operacao_pam(db=db,raiz=workspace/"cofre")
        if not aud["integridade_local_aprovada"]:
            raise ErroBackupPAM("falha de integridade do histórico; backup cancelado")
        if rel["falhas"] or rel["aprovados"] != len(tarefas):
            raise ErroBackupPAM(
                f"{rel['falhas']} falhas de coleta; não substituir backup validado")
        stats=criar_backup_pam(db=db,raiz=workspace/"cofre",
                              saida=destino/"estado_pam.zip")
    finally:
        db.close()
    payload={
        "estado":"CICLO_PAM_INCREMENTAL_APROVADO",
        "estado_anterior":antes,
        "coleta":{"total":rel["total"],"sucessos":rel["aprovados"],"falhas":rel["falhas"],
                 "mudancas":[{"ordem":r["ordem"],
                              "alteracao":r["resultado"]["alteracao"],
                              "sha256":r["resultado"]["sha256"],
                              "municipio_ibge":r["resultado"]["municipio_ibge"],
                              "ano_civil":r["resultado"]["ano_civil"]}
                             for r in rel["resultados"] if r["status"]=="OK"]},
        "integridade":aud,
        "backup":stats,
        "persistencia_cloud_comprovada":False,
        "vintages_publicacao_historica_verificadas":False,
        "treinamento_real_habilitado":False,
    }
    (destino/"resultado_ciclo.json").write_text(
        json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    (destino/"auditoria.json").write_text(
        json.dumps(aud,indent=2,ensure_ascii=False),encoding="utf-8")
    return payload


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON PAM: estado anterior -> coleta -> backup")
    p.add_argument("--saida",type=Path,required=True)
    p.add_argument("--tarefas",type=Path,required=True)
    p.add_argument("--modo",choices=("PUBLICO_IBGE","LOCAL"),default="PUBLICO_IBGE")
    p.add_argument("--entrada",type=Path)
    p.add_argument("--anterior",type=Path,help="estado_pam.zip anterior")
    p.add_argument("--legado",action="store_true",help="admitir ZIP piloto sem manifesto")
    p.add_argument("--iniciar-novo",action="store_true",
                   help="apenas para bootstrap explícito, sem backup anterior")
    args=p.parse_args(argv)
    try:
        tarefas=json.loads(args.tarefas.read_text(encoding="utf-8"))
        result=executar_ciclo_pam(saida=args.saida,tarefas=tarefas,
            modo=args.modo,entrada=args.entrada,arquivo_anterior=args.anterior,
            permitir_legado=args.legado,iniciar_novo=args.iniciar_novo)
        print(json.dumps({"estado":result["estado"],
                          "coleta":result["coleta"],
                          "backup_sha256":result["backup"]["sha256_arquivo"],
                          "capturas":result["integridade"]["capturas_registradas"],
                          "vintages":result["integridade"]["vintages_verificadas"]},
                         ensure_ascii=False))
        return 0
    except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
        print(json.dumps({"estado":"BLOQUEADO","motivo":str(exc)[:250]},
                         ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
