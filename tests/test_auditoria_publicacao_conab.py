"""Publicações oficiais CONAB identificadas vs RAW efetivamente ausente.

Arquivo golden de agrobr é de TERCEIRO e nunca reclassificado como
download oficial; o teste de bytes prova só estrutura e competência.
"""
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from nivon.auditoria_publicacao_conab import (
    ErroProvenienciaConab, auditar_conab_local, auditar_manifesto_edicoes,
    validar_publicacao_conab, main,
)

ROOT=Path(__file__).resolve().parents[1]
CAT=ROOT/"config"/"conab_publicacoes_identificadas_20261021.json"
FIXTURE=ROOT/"tests"/"fixtures"/"conab_progresso_agrobr_20260207.xlsx.b64"
P="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/"
FAKE={
    "id_edicao":"CONAB_PROG_2026_02_08",
    "url_pagina":P+"acompanhamento-das-lavouras-02-02-a-08-02-26/acompanhamento-das-lavouras-02-02-a-08-02-26",
    "url_anexo":P+"acompanhamento-das-lavouras-02-02-a-08-02-26/plantio-e-colheita-01-02-a-07-02.xlsx",
    "publicacao_data":"2026-02-09",
    "pagina_inicio":"2026-02-02","pagina_fim":"2026-02-08",
    "planilha_inicio":"2026-02-01","planilha_fim":"2026-02-07",
    "conteudo_sha256_verificado":None,
}


class TestAuditoriaPublicacaoConab(unittest.TestCase):
    def fixture(self):
        return base64.b64decode(FIXTURE.read_text().strip(),validate=True)

    def test_catalogo_duas_paginas_com_raw_pendente(self):
        doc=json.loads(CAT.read_text(encoding="utf-8"))
        report=auditar_manifesto_edicoes(doc)
        self.assertEqual(report["edicoes_identificadas"],2)
        self.assertEqual(report["edicoes_com_raw_autenticado"],0)
        self.assertFalse(report["migracao_permitida"])
        self.assertTrue(all(e["status"]=="PAGINA_E_ANEXO_IDENTIFICADOS_RAW_NAO_AUTENTICADO"
                            for e in report["estados"]))
        self.assertEqual({e["semana_planilha"] for e in report["estados"]},
                         {"2026-10-09","2026-10-16"})

    def test_nao_havia_raw_na_configuracao(self):
        doc=json.loads(CAT.read_text(encoding="utf-8"))
        self.assertTrue(all(e["conteudo_sha256_verificado"] is None for e in doc["edicoes"]))
        result=auditar_conab_local(doc["edicoes"][1],bytes_anexo=None)
        self.assertFalse(result["raw_verificado_localmente"])
        self.assertFalse(result["acesso_ao_anexo_comprovado"])

    def test_fixture_terceiro_so_prova_estrutura(self):
        result=auditar_conab_local(FAKE,bytes_anexo=self.fixture(),
                                  coletado_utc="2026-02-24T09:59:00Z")
        self.assertEqual(result["status"],"BYTES_LOCAIS_VALIDOS_SEM_PROVA_CADEIA_DE_DOWNLOAD")
        self.assertEqual(result["semana_planilha"],"2026-02-07")
        self.assertEqual(result["quantidade_observacoes"],11)
        self.assertEqual(result["raw_sha256_calculado"],hashlib.sha256(self.fixture()).hexdigest())
        self.assertFalse(result["acesso_ao_anexo_comprovado"])
        self.assertFalse(result["migracao_permitida"])
        self.assertFalse(result["direitos_individuais_comprovados"])

    def test_conteudo_html_disfarcado_falha(self):
        with self.assertRaises(ErroProvenienciaConab):
            auditar_conab_local(FAKE,bytes_anexo=b"<html>bloqueado</html>",
                               coletado_utc="2026-02-24T09:59:00Z")

    def test_hash_declarado_divergente_falha(self):
        d={**FAKE,"conteudo_sha256_verificado":"0"*64}
        with self.assertRaisesRegex(ErroProvenienciaConab,"hash"):
            auditar_conab_local(d,bytes_anexo=self.fixture(),
                               coletado_utc="2026-02-24T09:59:00Z")

    def test_coleta_anterior_publicacao_falha(self):
        with self.assertRaisesRegex(ErroProvenienciaConab,"anterior"):
            auditar_conab_local(FAKE,bytes_anexo=self.fixture(),
                               coletado_utc="2026-02-07T01:00:00Z")

    def test_coleta_sem_fuso_falha(self):
        with self.assertRaises(ErroProvenienciaConab):
            auditar_conab_local(FAKE,bytes_anexo=self.fixture(),
                               coletado_utc="2026-02-24T09:59:00")

    def test_sem_bytes_nao_aceita_coleta(self):
        with self.assertRaises(ErroProvenienciaConab):
            auditar_conab_local(FAKE,bytes_anexo=None,
                               coletado_utc="2026-02-24T09:59:00Z")

    def test_semana_da_planilha_divergente_bloqueia(self):
        d={**FAKE,"planilha_inicio":"2026-02-02","planilha_fim":"2026-02-08"}
        with self.assertRaisesRegex(ErroProvenienciaConab,"semana das observações"):
            auditar_conab_local(d,bytes_anexo=self.fixture(),
                               coletado_utc="2026-02-24T09:59:00Z")

    def test_anexo_externo_ou_outra_edicao_bloqueia(self):
        d={**FAKE,"url_anexo":"https://malicioso.example/plantio-e-colheita.xlsx"}
        with self.assertRaises(ErroProvenienciaConab):
            validar_publicacao_conab(d)
        d={**FAKE,"url_anexo":P+"acompanhamento-das-lavouras-12-10-a-18-10-26/plantio-e-colheita-01-02-a-07-02.xlsx"}
        with self.assertRaisesRegex(ErroProvenienciaConab,"outra edição"):
            validar_publicacao_conab(d)

    def test_janelas_de_semanas_incoerentes_bloqueiam(self):
        for val in ("2026-02-12","2026-02-01"):
            d={**FAKE,"pagina_fim":val}
            with self.subTest(val=val),self.assertRaises(ErroProvenienciaConab):
                validar_publicacao_conab(d)

    def test_manifesto_duplicado_bloqueia(self):
        with self.assertRaises(ErroProvenienciaConab):
            auditar_manifesto_edicoes({
                "schema":"NIVON_CONAB_PAGINA_ANEXO_V1",
                "edicoes":[FAKE,dict(FAKE)],
            })

    def test_cli_resumo_nao_publica_registros(self):
        import io
        from contextlib import redirect_stdout
        out=io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--manifesto",str(CAT),"--resumo"]),0)
        result=json.loads(out.getvalue())
        self.assertEqual(result["edicoes_identificadas"],2)
        self.assertNotIn("estados",result)


if __name__=="__main__":
    unittest.main()
