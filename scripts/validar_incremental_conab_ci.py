"""E2E GitHub Actions: 2 vintages -> 3 vintages -> no-op, 3 processes.

Downloads de referência de terceiro por commit fixo. O arquivo SQLite
persistente dura apenas dentro do diretório temporário do runner.
Jamais conecta Google Cloud, banco produtivo, portal CONAB ou agendador.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CAT=ROOT/"config"/"conab_referencias_multivintage_20261021.json"


def executar(catalogo:Path,banco:Path,backup:Path):
    cmd=[
        sys.executable,"-m","nivon.sincronizacao_incremental_conab_lab",
        "--catalogo",str(catalogo),
        "--banco",str(banco),"--backup-dir",str(backup),
        "--obter-do-github",
    ]
    env=dict(os.environ)
    env["PYTHONPATH"]=str(ROOT/"src")
    result=subprocess.run(cmd,env=env,cwd=str(ROOT),capture_output=True,
                          text=True,timeout=140,check=False)
    if result.returncode!=0:
        raise AssertionError("lote incremental falhou: "+result.stderr[-1500:])
    return json.loads(result.stdout)


def main():
    full=json.loads(CAT.read_text(encoding="utf-8"))
    assert len(full["edicoes"])==3
    with tempfile.TemporaryDirectory(prefix="nivon-incremental-lab-") as tmp:
        p=Path(tmp)
        if os.name=="posix":p.chmod(0o700)
        backups=p/"backups"
        backups.mkdir(mode=0o700)
        subset={**full,"edicoes":full["edicoes"][:2]}
        src=p/"catalogo-inicial.json"
        src.write_text(json.dumps(subset,ensure_ascii=False),encoding="utf-8")
        first=executar(src,p/"lab.sqlite",backups)
        assert first["edicoes_novas"]==2,first
        assert first["observacoes_novas"]==162,first
        assert first["requisicoes_previstas"]==2,first
        assert first["backup"]["backup_restaurado_e_conferido"] is True,first
        second=executar(CAT,p/"lab.sqlite",backups)
        assert second["edicoes_novas"]==1,second
        assert second["edicoes_inalteradas"]==2,second
        assert second["edicoes_historicas_preservadas"]==2,second
        assert second["observacoes_novas"]==66,second
        assert second["observacoes_no_lab"]==228,second
        assert second["requisicoes_previstas"]==1,second
        assert second["backup"]["backup_restaurado_e_conferido"] is True,second
        third=executar(CAT,p/"lab.sqlite",backups)
        assert third["edicoes_novas"]==0,third
        assert third["edicoes_inalteradas"]==3,third
        assert third["requisicoes_previstas"]==0,third
        assert third["backup_criado"] is False,third
        assert third["observacoes_no_lab"]==228,third
        with sqlite3.connect(str(p/"lab.sqlite")) as db:
            assert db.execute("SELECT COUNT(*) FROM lab_referencia_conab").fetchone()[0]==3
            assert db.execute("SELECT COUNT(*) FROM lab_observacao_conab").fetchone()[0]==228
            assert db.execute("SELECT COUNT(*) FROM lab_eventos_incrementais").fetchone()[0]==2
            assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
            count_by_week=dict(db.execute("""SELECT s.competencia,count(o.chave)
              FROM lab_referencia_conab s JOIN lab_observacao_conab o ON o.sha=s.sha
              GROUP BY s.competencia ORDER BY s.competencia"""))
            assert count_by_week=={
                "2025-09-27":66,"2026-02-21":96,"2026-09-18":66,
            },count_by_week
        b=sorted(backups.glob("*.sqlite"))
        assert len(b)==2,[x.name for x in b]
        for file in b:
            with sqlite3.connect(str(file)) as check:
                assert check.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
            assert file.stat().st_size>0
        report={
            "estado":"SINCRONIZACAO_INCREMENTAL_DE_REFERENCIA_TERCEIRO_TESTADA",
            "primeiro_ciclo":{"novas":first["edicoes_novas"],"observacoes":first["observacoes_novas"],
                             "GETs":first["requisicoes_previstas"]},
            "segundo_ciclo":{"novas":second["edicoes_novas"],"observacoes":second["observacoes_novas"],
                             "GETs":second["requisicoes_previstas"]},
            "terceiro_ciclo":{"novas":third["edicoes_novas"],"GETs":third["requisicoes_previstas"]},
            "total_banco_lab":third["observacoes_no_lab"],
            "total_backup_laboratorio":len(b),
            "backups_verificados":True,
            "preservacao_historico":True,
            "ciclos_processos_independentes":3,
            "fontes":"GITHUB_AGROBR_PUBLICO_FIXO_NAO_CONAB_DIRETO",
            "licenca_individual_oficial_verificada":False,
            "banco_de_producao":False,
            "publicacao_permitida":False,
            "migracao_permitida":False,
        }
        print(json.dumps(report,indent=2,ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
