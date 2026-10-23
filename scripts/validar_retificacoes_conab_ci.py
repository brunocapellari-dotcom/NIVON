"""Fluxo E2E em subprocessos: 1 base pública de terceiro + 2 revisões artificiais.

Nunca acessar portal CONAB, banco de produção ou publicar informação agrícola.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from nivon.fixture_retificacao_conab import alterar_xlsx_apenas_teste
from nivon.revisoes_conab_lab import consultar_versao_asof_lab
from nivon.recuperacao_isolada_conab_lab import recuperar_backup_isolado

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/"tests"/"fixtures"/"conab_progresso_agrobr_20260207.xlsx.b64"
URL="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture"


def _run(module,args):
    env=dict(os.environ)
    env["PYTHONPATH"]=str(ROOT/"src")
    p=subprocess.run([sys.executable,"-m",module,*args],cwd=str(ROOT),
                     env=env,text=True,capture_output=True,timeout=90)
    if p.returncode:
        raise AssertionError(f"{module} falhou (exit={p.returncode}): {p.stderr[-2500:]}")
    return json.loads(p.stdout)


def main():
    with tempfile.TemporaryDirectory(prefix="nivon-retificacoes-lab-") as tmp:
        root=Path(tmp)
        if os.name=="posix":root.chmod(0o700)
        rawdir=root/"raw"
        rawdir.mkdir(mode=0o700)
        backups=root/"backups"
        backups.mkdir(mode=0o700)
        db=root/"lab.sqlite"
        fixture=base64.b64decode(FIXTURE.read_text().strip(),validate=True)
        base={
            "id":"AGROBR_20260207","arquivo":"agrobr_20260207.xlsx",
            "origem_repositorio":"tests/golden_data/conab_progresso/progresso_sample/response.xlsx",
            "git_blob_sha1":"05d50fb46c23186ec8cee23f1969746acec082e4",
            "sha256":hashlib.sha256(fixture).hexdigest(),
            "bytes":len(fixture),"competencia":"2026-02-07",
            "captura_declarada":"2026-02-24T09:59:00Z",
            "url_original_declarada":URL,
            "observacoes_esperadas":11,"culturas_esperadas":["Soja","Milho 2ª"],
        }
        catalog={
            "schema":"NIVON_CONAB_REFERENCIAS_TERCEIRO_V1",
            "fornecedor_referencia":"bruno-portfolio/agrobr",
            "natureza":"REFERENCIAS_PUBLICADAS_POR_TERCEIRO_NAO_CAPTURA_DIRETA_CONAB",
            "edicoes":[base],
        }
        basepath=root/"catalog.json"
        basepath.write_text(json.dumps(catalog,ensure_ascii=False))
        (rawdir/base["arquivo"]).write_bytes(fixture)
        dbargs=["--catalogo",str(basepath),"--banco",str(db),
                "--backup-dir",str(backups)]
        original=_run("nivon.sincronizacao_incremental_conab_lab",
                      dbargs+["--arquivos-locais",str(rawdir)])
        assert original["observacoes_no_lab"]==11
        revision1,cell1=alterar_xlsx_apenas_teste(fixture)
        revision2,cell2=alterar_xlsx_apenas_teste(revision1)
        assert cell1==cell2
        versions=[]
        last=base["sha256"]
        for n,raw in ((1,revision1),(2,revision2)):
            name=f"retificacao-20260207-{n:03d}.xlsx"
            (rawdir/name).write_bytes(raw)
            ref={
                "id":f"RETIF_LAB_20260207_{n:03d}","id_base":base["id"],
                "sha_base":base["sha256"],"sha_anterior":last,
                "sha256":hashlib.sha256(raw).hexdigest(),
                "arquivo":name,"tamanho":len(raw),"competencia":"2026-02-07",
                "coletado_em":f"2026-10-23T15:{n:02d}:00Z",
                "motivo":"SIMULACAO_LAB_NAO_PUBLICADA_PELA_CONAB",
                "evidencia":"XLSX_FIXTURE_ALTERADA_SINTETICAMENTE",
            }
            versions.append(ref)
            last=ref["sha256"]
        rev_args=["--catalogo",str(basepath),"--banco",str(db),
                  "--backup-dir",str(backups),"--raw-dir",str(rawdir)]
        manifest1=root/"r1.json"
        manifest1.write_text(json.dumps({
            "schema":"NIVON_CONAB_RETIFICACOES_SINTETICAS_LAB_V1",
            "revisoes":versions[:1]},ensure_ascii=False))
        manifest2=root/"r2.json"
        manifest2.write_text(json.dumps({
            "schema":"NIVON_CONAB_RETIFICACOES_SINTETICAS_LAB_V1",
            "revisoes":versions[1:]},ensure_ascii=False))
        first=_run("nivon.revisoes_conab_lab",rev_args+["--manifesto",str(manifest1)])
        assert first["retificacoes_novas"]==1 and first["deltas"][0]["alterados"]==1,first
        second=_run("nivon.revisoes_conab_lab",rev_args+["--manifesto",str(manifest2)])
        assert second["retificacoes_novas"]==1 and second["deltas"][0]["alterados"]==1,second
        again=_run("nivon.revisoes_conab_lab",rev_args+["--manifesto",str(manifest2)])
        assert again["retificacoes_novas"]==0,again
        base_noop=_run("nivon.sincronizacao_incremental_conab_lab",
                       dbargs+["--arquivos-locais",str(rawdir)])
        assert base_noop["edicoes_novas"]==0 and base_noop["observacoes_no_lab"]==11
        assert base_noop["integridade_historico_e_backup_conferida"] is True
        with sqlite3.connect(str(db)) as conn:
            base_ct=conn.execute("SELECT COUNT(*) FROM lab_observacao_conab").fetchone()[0]
            revised_ct=conn.execute("SELECT COUNT(*) FROM lab_retificacao_observacoes").fetchone()[0]
            all_revisions=conn.execute("SELECT COUNT(*) FROM lab_retificacoes_conab").fetchone()[0]
            assert (base_ct,revised_ct,all_revisions)==(11,22,2)
            edges=list(conn.execute("SELECT sha_anterior FROM lab_retificacoes_conab ORDER BY revisao"))
            assert edges==[(base["sha256"],),(versions[0]["sha256"],)]
            assert conn.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
            assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        with sqlite3.connect(str(db)) as query_db:
            check0=consultar_versao_asof_lab(query_db,catalog,id_base=base["id"],
                corte_coleta="2026-10-23T14:59:59Z")
            check1=consultar_versao_asof_lab(query_db,catalog,id_base=base["id"],
                corte_coleta="2026-10-23T15:01:30Z")
            check2=consultar_versao_asof_lab(query_db,catalog,id_base=base["id"],
                corte_coleta="2026-10-23T15:02:30Z")
            assert [check0["revisao"],check1["revisao"],check2["revisao"]]==[0,1,2]
            assert [check0["sha_versao"],check1["sha_versao"],check2["sha_versao"]]==[
                base["sha256"],versions[0]["sha256"],versions[1]["sha256"]]
            assert len({check0["sha_semantico"],check1["sha_semantico"],
                        check2["sha_semantico"]})==3
        b=sorted(backups.glob("*.sqlite"))
        assert len(b)==3, [x.name for x in b]
        for file in b:
            with sqlite3.connect(str(file)) as restored:
                assert restored.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
                assert not restored.execute("PRAGMA foreign_key_check").fetchall()
        snapshots=[
            (backups/original["backup"]["arquivo_backup"],
             original["backup"]["sha256_backup"],0),
            (backups/first["backup"]["arquivo"],
             first["backup"]["sha256"],1),
            (backups/second["backup"]["arquivo"],
             second["backup"]["sha256"],2),
        ]
        restore_reports=[]
        for index,(snapshot,expected_sha,expected_revisions) in enumerate(snapshots):
            dest=root/f"recuperacao-{index}"
            dest.mkdir(mode=0o700)
            recovered=recuperar_backup_isolado(
                snapshot,expected_sha,catalog,dest,
                banco_vivo=db,cortes_coleta=[
                    "2026-10-23T14:59:59Z",
                    "2026-10-23T15:01:30Z",
                    "2026-10-23T15:02:30Z",
                ])
            assert recovered["restauracao_integridade_fk_semantica_conferida"] is True
            assert recovered["resumo_restaurado"]["retificacoes"]==expected_revisions
            assert recovered["resumo_restaurado"]["observacoes_originais"]==11
            assert recovered["resumo_restaurado"]["observacoes_retificacoes"]==11*expected_revisions
            assert recovered["comparacao"]["equivalencia_com_banco_vivo"] is (expected_revisions==2)
            assert recovered["comparacao"]["divergencias"]["retificacoes"]==2-expected_revisions
            expected_asof=[0]+[min(expected_revisions,1),min(expected_revisions,2)]
            assert [item.get("revisao",0) for item in recovered["cortes_asof"]]==expected_asof
            assert (dest/"conab-recuperado-lab.sqlite").is_file()
            assert (dest/"recuperacao-evidencia-lab.json").is_file()
            restore_reports.append({
                "snapshot":snapshot.name,
                "retificacoes_no_ponto":expected_revisions,
                "restauracao_valida":True,
                "igual_ao_vivo":expected_revisions==2,
            })
        lost=root/"recuperacao-sem-banco-vivo"
        lost.mkdir(mode=0o700)
        last=recuperar_backup_isolado(
            snapshots[-1][0],snapshots[-1][1],catalog,lost,
            banco_vivo=None,cortes_coleta=["2026-10-23T15:02:30Z"])
        assert last["comparacao"]["comparacao_realizada"] is False
        assert last["resumo_restaurado"]["retificacoes"]==2
        report={
            "estado":"LAB_RETIFICACOES_SINTETICAS_E2E_VERIFICADAS",
            "processos_independentes":5,
            "referencias_originais":1,
            "observacoes_originais_preservadas":base_ct,
            "versoes_sinteticas_adicionadas":all_revisions,
            "observacoes_em_retificacoes":revised_ct,
            "alteracoes_observadas":[e["deltas"][0]["alterados"] for e in (first,second)],
            "backup_sqlite_lab_conferidos":len(b),
            "retificacao_idempotente":True,
            "sincronizacao_base_consistente_apos_retificacao":True,
            "consulta_asof_3_cortes_sem_lookahead":True,
            "snapshots_recuperados_isoladamente":restore_reports,
            "recuperacao_sem_banco_vivo_verificada":True,
            "reconciliacao_laboratorio_com_versoes_historicas":True,
            "documentos_conab_oficiais_retificados":0,
            "dados_de_terceiro_com_valores_artificialmente_alterados":True,
            "banco_produtivo_alterado":False,
            "migracao_permitida":False,"publicacao_permitida":False,
        }
        print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
