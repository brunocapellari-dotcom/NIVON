"""Integração sintética de revisões IBGE/PAM e snapshots de documentação."""
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256

from nivon.ivo_pam_publicacoes import EventoPAM, ErroPublicacaoPAM, historico_edicoes_pam_asof
from nivon.registro_snapshots import abrir_registro, registrar_snapshot
from nivon.sidra_pam import planejar_pam_1612

UTC=timezone.utc
CAT={"datasets":[{"id":"IBGE_PAM","source_id":"IBGE",
                 "enabled":False,"collection_authorized":False,
                 "training_authorized":False}]}
URL="https://www.ibge.gov.br/estatisticas/economicas/agricultura-e-pecuaria/pam.html"


def quando(data):
    return datetime.fromisoformat(data+"T12:00:00+00:00")


def plano():
    return planejar_pam_1612(municipio_ibge="5107925",ano=2025,
                             codigo_produto_c81="2713",codigo_variavel="214")


def json_sidra(valor):
    return json.dumps([
        {"D1C":"Município (Código)","D2C":"Variável (Código)",
         "D3C":"Ano (Código)",
         "D4C":"Produto das lavouras temporárias (Código)",
         "V":"Valor","MN":"Unidade de Medida"},
        {"D1C":"5107925","D2C":"214","D3C":"2025",
         "D4C":"2713","V":str(valor),"MN":"Toneladas"},
    ],ensure_ascii=False).encode()


class TestIVOEdicoesPAM(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro()
        self.addCleanup(self.db.close)

    def evento(self,id,tipo,valor,publicado,coleta,*,formatado=False):
        raw=json.dumps(json.loads(json_sidra(valor)),indent=2,ensure_ascii=False).encode() if formatado else json_sidra(valor)
        pdf=("%PDF-1.4\nDocumento de exemplo sintetico "+id+" 000000000000").encode()
        h=sha256(pdf).hexdigest()
        for blob,mime,schema in (
            (raw,"application/json","sidra_pam_1612_v1"),
            (pdf,"application/pdf","ivo_pam_release_doc_v1"),
        ):
            registrar_snapshot(self.db,CAT,dataset_id="IBGE_PAM",
                sha256=sha256(blob).hexdigest(),tamanho=len(blob),
                mime=mime,schema_versao=schema,
                coletado_em=quando(coleta).isoformat(),
                competencia="2025",referencia="2025-12-31",
                publicacao=publicado,tipo="SINTETICO")
        return EventoPAM(
            id=id,tipo=tipo,plano=plano(),json_original=raw,
            json_coletado_em=quando(coleta),
            documento_pdf=pdf,documento_url=URL,documento_sha256=h,
            publicado_em=datetime.fromisoformat(publicado).date(),
            documento_coletado_em=quando(coleta),
            revisor_id="AUDITOR_TESTE",revisado_em=quando(coleta),
        )

    def consultar(self,edicoes,cut="2026-10-20"):
        return historico_edicoes_pam_asof(
            edicoes,db=self.db,corte=quando(cut),
            variavel="214",produto="2713")

    def test_divulgacao_e_errata_respeitam_vintages(self):
        a=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        b=self.evento("errata_2025","ERRATA","1600","2026-10-01","2026-10-02")
        antigo=self.consultar([b,a],cut="2026-09-15")
        novo=self.consultar([a,b])
        self.assertEqual(antigo["valor_asof"],1500.)
        self.assertEqual(novo["valor_asof"],1600.)
        self.assertEqual(novo["edicoes_conhecidas"],2)
        self.assertEqual(novo["historico"][1]["delta_desde_anterior"],100.)
        self.assertFalse(novo["label_final_certificado"])
        self.assertFalse(novo["data_oficial_publicacao_comprovada"])

    def test_sem_divulgacao_ainda_nao_retornou_valor(self):
        e=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        r=self.consultar([e],cut="2026-08-31")
        self.assertEqual(r["estado"],"SEM_EDICAO_CONHECIDA")
        self.assertIsNone(r["valor_asof"])

    def test_errata_isolada_esta_proibida(self):
        e=self.evento("errata_2025","ERRATA","1600","2026-10-01","2026-10-02")
        with self.assertRaises(ErroPublicacaoPAM):
            self.consultar([e])

    def test_pdfs_sem_snapshot_ou_hash_nao_burlam(self):
        e=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        self.db.execute("DELETE FROM nivon_coletas WHERE snapshot_id IN (SELECT id FROM nivon_snapshots WHERE sha256=?)",(e.documento_sha256,))
        with self.assertRaises(ErroPublicacaoPAM):
            self.consultar([e])
        with self.assertRaises(ErroPublicacaoPAM):
            self.consultar([replace(e,documento_sha256="f"*64)])

    def test_documento_nao_ibge_bloqueado(self):
        e=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        for url in ("https://ibge.gov.br.evil.test/pam.pdf",
                    "http://www.ibge.gov.br/pam.pdf",
                    "https://www.ibge.gov.br@evil.test/pam.pdf",
                    "https://www.ibge.gov.br:444/pam.pdf",
                    "https://www.ibge.gov.br:abc/pam.pdf"):
            with self.subTest(url=url),self.assertRaises(ErroPublicacaoPAM):
                self.consultar([replace(e,documento_url=url)])

    def test_revisor_posterior_ao_corte_nao_autoriza_errata(self):
        a=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        b=self.evento("errata_2025","ERRATA","1600","2026-10-01","2026-10-02")
        b=replace(b,revisado_em=quando("2026-11-01"))
        r=self.consultar([a,b])
        self.assertEqual(r["valor_asof"],1500.)

    def test_misturar_municipios_anual_proibido(self):
        a=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        b=self.evento("errata_2025","ERRATA","1600","2026-10-01","2026-10-02")
        outro=planejar_pam_1612(municipio_ibge="5105259",ano=2025,
                                 codigo_produto_c81="2713",codigo_variavel="214")
        with self.assertRaises(ErroPublicacaoPAM):
            self.consultar([a,replace(b,plano=outro)])

    def test_plano_adulterado_e_rejeitado_antes_da_consulta(self):
        e=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        p=dict(e.plano)
        p["url"]="https://www.ibge.gov.br/falso"
        with self.assertRaises(ErroPublicacaoPAM):
            self.consultar([replace(e,plano=p)])

    def test_indica_origem_do_snapshot_no_historico(self):
        e=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        r=self.consultar([e])
        self.assertEqual(r["historico"][0]["classe_snapshot"],"SINTETICO")

    def test_dois_ids_iguais_proibidos(self):
        a=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        with self.assertRaises(ErroPublicacaoPAM):
            self.consultar([a,a])

    def test_tipo_desconhecido_e_falha(self):
        a=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        with self.assertRaises(ErroPublicacaoPAM):
            self.consultar([replace(a,tipo="PREVISAO")])

    def test_duas_divulgacoes_iniciais_bloqueadas(self):
        a=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        b=self.evento("edicao_outra","DIVULGACAO","1600","2026-10-01","2026-10-02")
        with self.assertRaises(ErroPublicacaoPAM):
            self.consultar([a,b])

    def test_data_pdf_diferente_do_json_bloqueia(self):
        e=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        with self.assertRaises(ErroPublicacaoPAM):
            self.consultar([replace(e,publicado_em=datetime(2026,9,2).date())])

    def test_marcas_nao_numeric_valem_bloqueio_de_serie(self):
        e=self.evento("edicao_2025","DIVULGACAO","X","2026-09-01","2026-09-02")
        with self.assertRaises(ErroPublicacaoPAM):
            self.consultar([e])

    def test_republicacao_uma_versao_sem_mudar_valor_nao_e_performance(self):
        a=self.evento("edicao_2025","DIVULGACAO","1500","2026-09-01","2026-09-02")
        b=self.evento("errata_2025","ERRATA","1500","2026-10-01","2026-10-02",formatado=True)
        r=self.consultar([a,b])
        self.assertEqual(r["historico"][1]["delta_desde_anterior"],0.)
        self.assertFalse(r["treinamento_real_autorizado"])


if __name__=="__main__":
    unittest.main()
