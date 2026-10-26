"""Aceitação de relatório IVO com backup real PAM: somente leitura/offline.

Consome ZIP existente auditado, produz entrega estruturada e HTML/Markdown.
Nenhuma coleta externa; não marca retroativamente publicação no ano da PAM.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

from .ivo_pam_backup import restaurar_backup_pam
from .ivo_pam_leitura import abrir_pam_somente_leitura
from .ivo_pam_qualidade import auditar_operacao_pam
from .ivo_pam_alertas import alertas_revisoes_pam
from .ivo_pam_entrega import montar_entrega_pam_ivo
from .ivo_pam_relatorio import salvar_relatorio_pam


def preparar_aceite_pam(*,arquivo, tarefas,saida):
    destino=Path(saida)
    if destino.exists() or not destino.parent.is_dir() or destino.is_symlink():
        raise ValueError("saída deve ser diretório novo")
    if not isinstance(tarefas,list) or not 1<=len(tarefas)<=30:
        raise ValueError("uma a trinta células para o relatório real")
    # O diretório só é publicado após verificar todos os bytes e tabelas.
    with tempfile.TemporaryDirectory(prefix="ivo-pam-aceite-",dir=destino.parent) as temporary:
        area=Path(temporary)
        recuperacao=restaurar_backup_pam(arquivo=arquivo,destino=area/"estado")
        with closing(abrir_pam_somente_leitura(area/"estado"/"pam.sqlite")) as db:
            auditoria=auditar_operacao_pam(db=db,raiz=area/"estado"/"cofre")
            if not auditoria["integridade_local_aprovada"]:
                raise ValueError("auditoria do backup não aprovada")
            radar=alertas_revisoes_pam(
                db,desde_exclusivo=datetime(1970,1,1,tzinfo=timezone.utc))
            entrega=montar_entrega_pam_ivo(db=db,tarefas=tarefas,radar=radar)
            if any(row["valor_candidato"] is None for row in entrega["linhas"]):
                raise ValueError("célula real requerida está ausente/oculta")
            if len(entrega["linhas"])!=len(tarefas):
                raise ValueError("backup incompleto para as células exigidas")
        rel=salvar_relatorio_pam(entrega,diretorio=area)
        (area/"entrega_ivo_pam.json").write_text(
            json.dumps(entrega,indent=2,ensure_ascii=False),encoding="utf-8")
        (area/"auditoria_pam.json").write_text(
            json.dumps(auditoria,indent=2,ensure_ascii=False),encoding="utf-8")
        resumido={
            "estado":"ACEITE_PAM_REAL_OFFLINE",
            "capturas_verificadas":recuperacao["capturas"],
            "vintages_verificadas":recuperacao["vintages"],
            "celulas":rel["celulas"],"revisoes_relevantes":rel["alteracoes_relevantes"],
            "ultima_coleta_utc":rel["ultima_coleta_utc"],
            "integridade_local_aprovada":True,
            "publicacao_historica_atestada":False,
            "site_publicado":False,
            "treinamento_gerado":False}
        (area/"aceite_pam.json").write_text(
            json.dumps(resumido,indent=2,ensure_ascii=False),encoding="utf-8")
        # Evitar copiar o backup/SQLite bruto junto do relatório (o HTML
        # é leitura interna; ZIP histórico fica no acervo da fonte).
        for file in (area/"relatorio_pam.html",area/"relatorio_pam.md",
                     area/"entrega_ivo_pam.json",area/"auditoria_pam.json",
                     area/"aceite_pam.json"):
            if not file.is_file() or file.stat().st_size==0:
                raise ValueError("artefato de entrega incompleto")
        import shutil
        shutil.rmtree(area/"estado")
        area.rename(destino)
    return resumido


def main(argv=None):
    p=argparse.ArgumentParser(description="NIVON IVO: backup PAM validado -> boletim real offline")
    p.add_argument("--backup",type=Path,required=True)
    p.add_argument("--tarefas",type=Path,required=True)
    p.add_argument("--saida",type=Path,required=True)
    args=p.parse_args(argv)
    try:
        tarefas=json.loads(args.tarefas.read_text(encoding="utf-8"))
        result=preparar_aceite_pam(arquivo=args.backup,tarefas=tarefas,saida=args.saida)
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (ValueError,OSError,sqlite3.Error,TypeError,KeyError) as exc:
        print(json.dumps({"estado":"BLOQUEADO","erro":str(exc)[:240]},ensure_ascii=False))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
