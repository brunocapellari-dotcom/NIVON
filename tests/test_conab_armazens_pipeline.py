"""Integração local: CONAB sintético -> proveniência SQLite -> restore."""
import tempfile
import unittest
from pathlib import Path
from nivon.conab_armazens import LAYOUT_CONAB_SICARM_HEADER_V1, agregar_capacidade_local
from nivon.registro_snapshots import abrir_registro, registrar_snapshot, visao_asof
from nivon.backup_sqlite import criar_backup, restaurar_backup

class TestPipelineArmazens(unittest.TestCase):
    def test_agregacao_registro_idempotencia_e_backup(self):
        with tempfile.TemporaryDirectory() as nome:
            pasta=Path(nome)
            f=pasta/"conab_fake.txt"
            cabecalho=("identificacao_armazem;dsc_especie_armazem;dsc_tipo_armazem;"
                       "dsc_tipo_entidade;dsc_tipo_pessoa;nom_municipio;cod_ibge;uf;"
                       "qtd_capacidade_estatica(t);qtd_capacidade_expedicao(t);"
                       "qtd_capacidade_recepcao(t);latitude;longitude;"
                       "nome_armazenador;endereco;email\n")
            linha="CODIGO-SINTETICO;A GRANEL;SILO;PRIVADO;PJ;Sorriso;5107925;MT;100,50;0,00;0,00;;;DADO_SIGILOSO;RUA_SIGILOSA;EMAIL_SIGILOSO\n"
            f.write_bytes((cabecalho+linha).encode("cp1252"))
            resumo=agregar_capacidade_local(f,LAYOUT_CONAB_SICARM_HEADER_V1,
                coletado_em="2026-10-19T12:00:00-04:00",
                publicacao="2026-10-18",referencia="2026-10-18")
            self.assertEqual(resumo["capacidade_total_t"],100.5)
            self.assertNotIn("DADO_SIGILOSO",str(resumo))
            catalogo={"datasets":[{"id":"CONAB_ARMAZENS_CAPACIDADE","source_id":"CONAB"}]}
            db=abrir_registro(":memory:")
            try:
                params=dict(dataset_id="CONAB_ARMAZENS_CAPACIDADE",
                    sha256=resumo["sha256_original"],tamanho=resumo["bytes"],
                    mime="text/plain",schema_versao="SICARM_header_v1",
                    coletado_em=resumo["coleta"],publicacao=resumo["publicacao"],
                    referencia=resumo["referencia"],tipo="SINTETICO")
                um=registrar_snapshot(db,catalogo,**params)
                dois=registrar_snapshot(db,catalogo,**params)
                self.assertTrue(um["nova_versao"])
                self.assertFalse(dois["nova_versao"])
                corte=visao_asof(db,dataset_id="CONAB_ARMAZENS_CAPACIDADE",
                    corte_coleta="2026-10-19T17:00:00Z",corte_publicacao="2026-10-19")
                self.assertEqual(corte["sha256"],resumo["sha256_original"])
                backup=pasta/"copia.sqlite"
                b=criar_backup(db,backup)
            finally:
                db.close()
            restaurado=pasta/"restaurado.sqlite"
            restaurar_backup(backup,restaurado,sha256_esperado=b["sha256"])
            outro=abrir_registro(str(restaurado))
            try:
                n=outro.execute("SELECT count(*) FROM nivon_snapshots").fetchone()[0]
                self.assertEqual(n,1)
            finally:
                outro.close()

    def test_versao_sem_publicacao_nao_usa_data_coleta(self):
        with tempfile.TemporaryDirectory() as nome:
            f=Path(nome)/"armazens.txt"
            f.write_bytes(("identificacao_armazem;dsc_especie_armazem;dsc_tipo_armazem;"
             "dsc_tipo_entidade;dsc_tipo_pessoa;nom_municipio;cod_ibge;uf;"
             "qtd_capacidade_estatica(t);qtd_capacidade_expedicao(t);"
             "qtd_capacidade_recepcao(t);latitude;longitude;"
             "nome_armazenador;endereco;email\n"
             "SINTETICO;A GRANEL;SILO;PRIVADO;PJ;Sorriso;5107925;MT;"
             "1,00;0,00;0,00;;;;;\n").encode("cp1252"))
            r=agregar_capacidade_local(f,LAYOUT_CONAB_SICARM_HEADER_V1,
                                      coletado_em="2026-10-19T12:00:00Z")
            self.assertIsNone(r["publicacao"])
            db=abrir_registro(":memory:")
            try:
                registrar_snapshot(db,{"datasets":[{"id":"CONAB_ARMAZENS_CAPACIDADE","source_id":"CONAB"}]},
                    dataset_id="CONAB_ARMAZENS_CAPACIDADE",sha256=r["sha256_original"],
                    tamanho=r["bytes"],mime="text/plain",schema_versao="SICARM_header_v1",
                    coletado_em=r["coleta"],publicacao=None)
                self.assertIsNone(visao_asof(db,dataset_id="CONAB_ARMAZENS_CAPACIDADE",
                    corte_coleta="2026-10-20T00:00:00Z",corte_publicacao="2026-10-20"))
            finally:
                db.close()
