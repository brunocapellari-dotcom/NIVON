"""Integração IVO: bytes em quarentena -> pacote de auditoria NÃO homologado."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nivon.sidra_pam import planejar_pam_1612
from nivon.ivo_pam_coletor_pontual import coletar_candidato_pam
from nivon.ivo_pam_quarentena import arquivar_candidato_pam
from nivon.ivo_pam_pacote_auditoria import (
    ErroPacotePAM, preparar_pacote_pam_quarentena,
)

UTC=timezone.utc
CAT={"datasets":[{"id":"IBGE_PAM","source_id":"IBGE",
    "enabled":True,"collection_authorized":True,"training_authorized":False}]}
RIGHTS={"operacoes":frozenset(("COLETA","ARMAZENAMENTO")),
        "evidencia_ref":"DIREITOS_SINTETICOS_TESTE_IVO"}
COLETA=datetime(2026,10,21,15,tzinfo=UTC)


def consulta(municipio="5107958",ano=2021,produto="2713",variavel="214"):
    return planejar_pam_1612(municipio_ibge=municipio,ano=ano,
        codigo_produto_c81=produto,codigo_variavel=variavel)


def bytes_sidra(municipio="5107958",ano=2021,produto="2713",variavel="214",
                unidade="Toneladas",valor="150"):
    return json.dumps([
        {"D1C":"Município (Código)","D2C":"Variável (Código)",
         "D3C":"Ano (Código)",
         "D4C":"Produto das lavouras temporárias (Código)",
         "V":"Valor","MN":"Unidade de Medida"},
        {"D1C":municipio,"D2C":variavel,"D3C":str(ano),
         "D4C":produto,"V":valor,"MN":unidade}
    ],ensure_ascii=False).encode()


class TestIVOPacoteAuditoriaPAM(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)/"quarentena"
        self.plano=consulta()

    def arquivar(self,raw=None,*,plano=None,kind="SIDRA_JSON",
                direitos=RIGHTS,documento_url=None):
        plan=plano or self.plano
        if raw is None:
            raw=bytes_sidra()
        candidate=coletar_candidato_pam(catalogo=CAT,direitos=direitos,
            tipo=kind,coletado_em=COLETA,
            plano=plan if kind=="SIDRA_JSON" else None,
            url_documento=documento_url,
            transporte=lambda url,limit,timeout:(raw,
                "application/json" if kind=="SIDRA_JSON" else "application/pdf"))
        return arquivar_candidato_pam(raiz=self.root,candidato=candidate)["recibo_sha256"]

    def pacote(self,recibo,**kwargs):
        return preparar_pacote_pam_quarentena(raiz=self.root,
            recibo_sidra=recibo,plano=self.plano,**kwargs)

    def test_pacote_comprovacao_local_sem_validar_publicacao_ou_treino(self):
        digest=self.arquivar()
        rel=self.pacote(digest)
        self.assertEqual(rel["estado"],"PACOTE_PAM_QUARENTENA_AUDITORIA_PENDENTE")
        self.assertEqual(rel["municipio_ibge"],"5107958")
        self.assertEqual(rel["produto"],"SOJA_EM_GRAO")
        self.assertEqual(rel["ano_civil"],2021)
        self.assertEqual(rel["indicador"],"QUANTIDADE_PRODUZIDA")
        self.assertEqual(rel["unidade"],"Toneladas")
        self.assertEqual(rel["celula_sidra"]["valor_candidato_nao_certificado"],150.)
        self.assertFalse(rel["ledger_canonico_modificado"])
        self.assertFalse(rel["dados_reais_homologados"])
        self.assertFalse(rel["treinamento_real_habilitado"])
        self.assertIn("DATA_PUBLICACAO_OFICIAL_NAO_ATESTADA",rel["bloqueios"])
        self.assertIn("DOCUMENTO_OFICIAL_ANEXO_AUSENTE",rel["bloqueios"])

    def test_pdf_anexo_confere_hash_mas_nao_prova_que_corresponde_ao_valor(self):
        digest=self.arquivar()
        pdf=self.arquivar(raw=b"%PDF-1.4\n"+b"Documento apenas sintético"*3,
             kind="PDF_IBGE",documento_url="https://biblioteca.ibge.gov.br/pam/nota.pdf")
        r=self.pacote(digest,recibo_pdf=pdf,data_publicacao_declarada="2026-09-01")
        self.assertIsNotNone(r["documento_anexo"])
        self.assertEqual(r["documento_anexo"]["recibo_sha256"],pdf)
        self.assertFalse(r["documento_anexo"]["conteudo_revisado_para_o_alvo"])
        self.assertFalse(r["documento_anexo"]["autenticidade_ou_data_oficial_comprovadas"])
        self.assertEqual(r["publicacao_declarada_nao_verificada"],"2026-09-01")
        self.assertFalse(r["treinamento_real_habilitado"])
        self.assertNotIn("DOCUMENTO_OFICIAL_ANEXO_AUSENTE",r["bloqueios"])

    def test_pdf_com_direito_diferente_bloqueado(self):
        digest=self.arquivar()
        diff={"operacoes":RIGHTS["operacoes"],"evidencia_ref":"OUTROS_TERMOS_FICTICIOS"}
        pdf=self.arquivar(raw=b"%PDF-1.4\n"+b"Outro PDF"*4,
             kind="PDF_IBGE",documento_url="https://www.ibge.gov.br/pam/aviso.pdf",
             direitos=diff)
        with self.assertRaises(ErroPacotePAM):
            self.pacote(digest,recibo_pdf=pdf)

    def test_pacote_nao_aceita_municipio_ou_produto_errado(self):
        digest=self.arquivar()
        for p in (consulta(municipio="5107925"),consulta(produto="2692"),
                  consulta(ano=2022),consulta(variavel="109")):
            with self.subTest(p=p),self.assertRaises(ErroPacotePAM):
                preparar_pacote_pam_quarentena(raiz=self.root,
                    recibo_sidra=digest,plano=p)

    def test_payload_de_celula_fora_do_plano_rejeitado(self):
        p=consulta()
        bad=bytes_sidra(municipio="5107925")
        # Collector itself rejects mismatches; require no invalid object to exist.
        with self.assertRaises(Exception):
            self.arquivar(bad,plano=p)

    def test_unidade_errada_bloqueada(self):
        # Quarantine accepts collector-normalized result; semantic mismatch
        # still rejected at audit stage.
        digest=self.arquivar(bytes_sidra(unidade="Hectares"))
        with self.assertRaises(ErroPacotePAM):
            self.pacote(digest)

    def test_marcadores_nao_sao_toneladas_exatas(self):
        for value in ("0","-","X","..","..."):
            with self.subTest(value=value):
                digest=self.arquivar(bytes_sidra(valor=value))
                rel=self.pacote(digest)
                self.assertIsNone(rel["celula_sidra"]["valor_candidato_nao_certificado"])
                self.assertIn("VALOR_SIDRA_MARCADOR_NAO_EXATO",rel["bloqueios"])

    def test_comprovar_versao_anterior_so_pelo_hash_nao_basta(self):
        digest=self.arquivar()
        rel=self.pacote(digest,versao_anterior_sha256="a"*64)
        self.assertIn("VERSAO_HISTORICA_CITADA_MAS_NAO_CONFERIDA",rel["bloqueios"])
        self.assertFalse(rel["dados_reais_homologados"])

    def test_data_de_publicacao_futura_rejeitada(self):
        digest=self.arquivar()
        for day in ("2026-11-01","2026-13-30","2026-02-31"):
            with self.subTest(day=day),self.assertRaises(ErroPacotePAM):
                self.pacote(digest,data_publicacao_declarada=day)

    def test_recibo_com_hash_inexistente_nao_e_pacote(self):
        with self.assertRaises(ErroPacotePAM):
            self.pacote("a"*64)

    def test_payload_adulterado_apos_arquivamento_bloqueado(self):
        digest=self.arquivar()
        receb=json.loads((self.root/"recibos"/(digest+".json")).read_text())
        arq=self.root/receb["arquivo_bytes_relativo"]
        arq.write_bytes(b"[123]")
        with self.assertRaises(ErroPacotePAM):
            self.pacote(digest)

    def test_recibo_alterado_bloqueado(self):
        digest=self.arquivar()
        p=self.root/"recibos"/(digest+".json")
        p.write_text('{"liberado_para_treino":true}')
        with self.assertRaises(ErroPacotePAM):
            self.pacote(digest)

    def test_pacote_nao_escreve_no_ledger_canonico(self):
        digest=self.arquivar()
        self.pacote(digest)
        self.assertFalse((self.root/"database.sqlite").exists())
        self.assertEqual(len(list((self.root/"objetos_sha256").glob("*.bin"))),1)
        self.assertEqual(len(list((self.root/"recibos").glob("*.json"))),1)

    def test_nao_aceita_pdf_como_recibo_json(self):
        pdf=self.arquivar(raw=b"%PDF-1.4\n"+b"PDF sintético"*5,
            kind="PDF_IBGE",documento_url="https://www.ibge.gov.br/pam/nota.pdf")
        with self.assertRaises(ErroPacotePAM):
            self.pacote(pdf)


if __name__=="__main__":
    unittest.main()
