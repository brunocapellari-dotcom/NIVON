"""Contrato de validação multivintage CONAB sem rede e sem novos RAW no git."""
import base64
import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from pathlib import Path

from nivon.auditoria_vintages_conab import (
    ErroAuditoriaVintages,auditar_vintages_conab,
    validar_catalogo_vintages,main,
)

ROOT=Path(__file__).resolve().parents[1]
CAT=ROOT/"config"/"conab_referencias_multivintage_20261021.json"
GOLD=ROOT/"tests"/"fixtures"/"conab_progresso_agrobr_20260207.xlsx.b64"
SAMPLE_ID="AGROBR_20260207"
SAMPLE="agrobr_20260207.xlsx"


class TestAuditoriaVintagesConab(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.data=base64.b64decode(GOLD.read_text().strip(),validate=True)
        self.cat=json.loads(CAT.read_text(encoding="utf-8"))
        self.sample={
            "id":SAMPLE_ID,
            "arquivo":SAMPLE,
            "origem_repositorio":"tests/golden_data/conab_progresso/progresso_sample/response.xlsx",
            "git_blob_sha1":"05d50fb46c23186ec8cee23f1969746acec082e4",
            "sha256":hashlib.sha256(self.data).hexdigest(),
            "bytes":len(self.data),
            "competencia":"2026-02-07",
            "captura_declarada":"2026-02-24T09:59:00Z",
            "url_original_declarada":"https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture",
            "observacoes_esperadas":11,
            "culturas_esperadas":["Soja","Milho 2ª"],
        }
    def sample_catalog(self):
        doc=copy.deepcopy(self.cat)
        doc["edicoes"]=[copy.deepcopy(self.sample)]
        return doc
    def put(self, data=None):
        (self.root/SAMPLE).write_bytes(self.data if data is None else data)

    def test_catalogo_pins_reais_tres_edicoes_terceiro(self):
        doc=validar_catalogo_vintages(self.cat)
        self.assertEqual(len(doc["edicoes"]),3)
        self.assertEqual({r["competencia"] for r in doc["edicoes"]},
                         {"2025-09-27","2026-02-21","2026-09-18"})
        self.assertTrue(all(len(r["sha256"])==64 for r in doc["edicoes"]))
        self.assertEqual(doc["edicoes"][0]["observacoes_esperadas"],66)

    def test_catalogo_sem_files_conta_pendencias_sem_inventar_dados(self):
        report=auditar_vintages_conab(self.cat,self.root)
        self.assertEqual(report["edicoes_pendentes"],3)
        self.assertEqual(report["edicoes_presentes_reprocessadas"],0)
        self.assertFalse(report["parser_multivintage_testado_localmente"])
        self.assertFalse(report["captura_proveniencia_oficial_comprovada"])
        self.assertFalse(report["licencas_confirmadas_individualmente"])
        self.assertFalse(report["migracao_permitida"])
        self.assertFalse(report["publicacao_permitida"])

    def test_amostra_existente_reprocessa_sem_afirmar_vintages_variadas(self):
        self.put()
        r=auditar_vintages_conab(self.sample_catalog(),self.root)
        self.assertEqual(r["edicoes_presentes_reprocessadas"],1)
        self.assertEqual(r["edicoes_pendentes"],0)
        self.assertEqual(r["itens"][0]["observacoes_extraidas"],11)
        self.assertEqual(r["itens"][0]["estado"],
                         "RAW_TERCEIRO_REPRODUZIDO_SEM_HOMOLOGACAO_OFICIAL")
        self.assertTrue(r["itens"][0]["hash_validado_neste_ambiente"])
        self.assertFalse(r["parser_multivintage_testado_localmente"])
        self.assertFalse(r["migracao_permitida"])

    def test_alterar_arquivo_e_sha_velho_falha(self):
        self.put(self.data+b"x")
        with self.assertRaisesRegex(ErroAuditoriaVintages,"tamanho diferente"):
            auditar_vintages_conab(self.sample_catalog(),self.root)

    def test_mesmo_tamanho_conteudo_alterado_falha_sha(self):
        b=bytearray(self.data)
        b[20]^=1
        self.put(bytes(b))
        with self.assertRaisesRegex(ErroAuditoriaVintages,"SHA256"):
            auditar_vintages_conab(self.sample_catalog(),self.root)

    def test_oraculo_contagem_errada_bloqueia(self):
        doc=self.sample_catalog()
        doc["edicoes"][0]["observacoes_esperadas"]=12
        self.put()
        with self.assertRaisesRegex(ErroAuditoriaVintages,"contagem"):
            auditar_vintages_conab(doc,self.root)

    def test_oraculo_culturas_errado_bloqueia(self):
        doc=self.sample_catalog()
        doc["edicoes"][0]["culturas_esperadas"]=["Soja"]
        self.put()
        with self.assertRaisesRegex(ErroAuditoriaVintages,"culturas"):
            auditar_vintages_conab(doc,self.root)

    def test_oraculo_semana_errado_bloqueia(self):
        doc=self.sample_catalog()
        doc["edicoes"][0]["competencia"]="2026-02-08"
        self.put()
        with self.assertRaisesRegex(ErroAuditoriaVintages,"semana observada"):
            auditar_vintages_conab(doc,self.root)

    def test_documento_sem_schema_recusado(self):
        doc=self.sample_catalog()
        doc["schema"]="UNKNOWN"
        with self.assertRaises(ErroAuditoriaVintages):
            auditar_vintages_conab(doc,self.root)

    def test_arquivo_nao_referenciado_recusado(self):
        (self.root/"extra.txt").write_text("indesejado")
        with self.assertRaisesRegex(ErroAuditoriaVintages,"não catalogado"):
            auditar_vintages_conab(self.sample_catalog(),self.root)

    def test_duplicidade_de_competencia_recusada(self):
        doc=self.sample_catalog()
        duplicate=copy.deepcopy(doc["edicoes"][0])
        duplicate["id"]="AGROBR_20260208"
        duplicate["arquivo"]="agrobr_20260208.xlsx"
        duplicate["sha256"]="0"*64
        doc["edicoes"].append(duplicate)
        with self.assertRaisesRegex(ErroAuditoriaVintages,"duplicada"):
            auditar_vintages_conab(doc,self.root)

    def test_caminho_traversal_e_symlink_recusados(self):
        doc=self.sample_catalog()
        doc["edicoes"][0]["arquivo"]="../escape.xlsx"
        with self.assertRaises(ErroAuditoriaVintages):
            auditar_vintages_conab(doc,self.root)
        link=Path(self.tmp.name).parent/"unused-nivon-symlink"
        # Criar dentro da pasta do teste sem invadir diretórios externos
        link=self.root/SAMPLE
        elsewhere=Path(self.tmp.name)/"real.xlsx"
        elsewhere.write_bytes(self.data)
        try:link.symlink_to(elsewhere)
        except (OSError,NotImplementedError):self.skipTest("symlink indisponível")
        with self.assertRaises(ErroAuditoriaVintages):
            auditar_vintages_conab(self.sample_catalog(),self.root)

    def test_captura_sem_timezone_rejeitada(self):
        doc=self.sample_catalog()
        doc["edicoes"][0]["captura_declarada"]="2026-02-24T09:59:00"
        with self.assertRaises(ErroAuditoriaVintages):
            auditar_vintages_conab(doc,self.root)

    def test_oraculo_publicacao_nao_verificada(self):
        self.put()
        r=auditar_vintages_conab(self.sample_catalog(),self.root)
        self.assertFalse(r["captura_proveniencia_oficial_comprovada"])
        self.assertFalse(r["licencas_confirmadas_individualmente"])
        self.assertFalse(r["publicacao_permitida"])

    def test_cli_sumario_sem_files(self):
        out=io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["--catalogo",str(CAT),
                                   "--diretorio",str(self.root),"--resumo"]),0)
        doc=json.loads(out.getvalue())
        self.assertEqual(doc["edicoes_pendentes"],3)
        self.assertNotIn("itens",doc)

    def test_cli_falha_se_raw_nao_coincide(self):
        self.put(b"RAW adulterado")
        doc=self.sample_catalog()
        path=self.root.parent/"catalogo-privado.json"
        path.write_text(json.dumps(doc))
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as exc:
            main(["--catalogo",str(path),"--diretorio",str(self.root)])
        self.assertEqual(exc.exception.code,2)


if __name__=="__main__":
    unittest.main()
