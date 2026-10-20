"""Backup e restauração dos novos registros NIVON, com dados apenas sintéticos."""
from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path

from nivon.backup_sqlite import criar_backup,restaurar_backup,ErroBackup
from nivon.conab_agrobr import normalizar_progresso
from nivon.progresso_store import abrir_progresso,gravar_progresso
from nivon.portos_store import abrir_historico_portos,gravar_documento_porto
from nivon.portos import Programacao
from nivon.outbox_briefing import abrir_outbox,agendar_briefing

AGORA="2026-10-19T12:00:00+00:00"
URL="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture"
PORTO_URL="https://www.portodesantos.com.br/fixture-testes"


class TestRestauracaoRegistrosNivon(unittest.TestCase):
    def exercitar(self,conn,nome,tabela,expect):
        with tempfile.TemporaryDirectory() as dir:
            p=Path(dir)
            bk=p/(nome+"-backup.sqlite")
            dest=p/(nome+"-restore.sqlite")
            one=criar_backup(conn,bk)
            self.assertEqual(one["integridade"],"OK")
            self.assertEqual(bk.stat().st_mode & 0o777,0o600)
            second=restaurar_backup(bk,dest,sha256_esperado=one["sha256"])
            self.assertEqual(second["integridade"],"OK")
            with sqlite3.connect(dest) as read:
                self.assertEqual(
                    read.execute("SELECT COUNT(*) FROM "+tabela).fetchone()[0],expect)
                self.assertEqual(read.execute("PRAGMA integrity_check").fetchone()[0],"ok")
            with self.assertRaises(ErroBackup):
                restaurar_backup(bk,dest,sha256_esperado=one["sha256"])

    def test_progresso_conab_mantem_revisoes(self):
        db=abrir_progresso()
        rec=normalizar_progresso([{
            "cultura":"Soja","safra":"2026/27",
            "operacao":"Semeadura","uf":"MT",
            "semana_atual":"2026-10-16","pct_semana_atual":.35,
        }],fonte_url=URL,coletado_em=datetime.fromisoformat(AGORA),
        publicado_em="2026-10-19T11:00:00+00:00")
        gravar_progresso(db,rec,evidence_id="TESTE",direitos_confirmados=True)
        self.exercitar(db,"conab","progresso_observacoes",1)
        db.close()

    def test_porto_mantem_documento_e_escala(self):
        db=abrir_historico_portos()
        p=Programacao(
            porto="SANTOS",navio="NAVIO TESTE",duv="DUV-1",
            imo="1234567",produto="SOJA",toneladas_programadas=1000,
            fonte=PORTO_URL,coletado_em=AGORA,
            status="PROGRAMADO",eta_programado="21/10/2026",
            terminal="Berço 1")
        gravar_documento_porto(db,{
            "status":"EXTRAIDO_AGUARDA_HOMOLOGACAO",
            "porto":"SANTOS","fonte":PORTO_URL,
            "documento_sha256":hashlib.sha256(b"fixture").hexdigest(),
            "capturado_em":AGORA,"registros":[p],
        },evidence_id="TESTE",direitos_confirmados=True)
        self.exercitar(db,"portos","porto_linhas",1)
        db.close()

    def test_outbox_mantem_unicidade(self):
        db=abrir_outbox()
        msg="Nivon sintético"
        agendar_briefing(db,dia_local="2026-10-19",
                         destinatario_hmac="a"*64,
                         briefing={"status":"PREPARADO_SEM_ENVIO",
                            "texto":msg,
                            "sha256":hashlib.sha256(msg.encode()).hexdigest()},
                         agora=AGORA,auditoria_aprovada=True)
        self.exercitar(db,"outbox","briefing_outbox",1)
        db.close()


if __name__=="__main__":
    unittest.main()
