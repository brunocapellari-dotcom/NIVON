"""Testes E2E da ponte IVO <-> normalizador PAM <-> ledger NIVON.

Fixtures do SIDRA são SINTÉTICAS: mesmo fluxo JSON, sem rede e sem declarar
produção agrícola medida, direitos de dados reais ou data oficial publicada.
"""
import json
import unittest
from datetime import datetime, timezone
from hashlib import sha256

from nivon.historico import Observacao
from nivon.ivo_pam_bridge import ErroPontePAM, preparar_pam_anual_asof
from nivon.registro_snapshots import abrir_registro, registrar_snapshot
from nivon.sidra_pam import planejar_pam_1612

UTC=timezone.utc
COLETA="2026-10-19T12:00:00Z"
CORTE=datetime(2026,10,20,15,tzinfo=UTC)
CAT={"datasets":[{"id":"IBGE_PAM","source_id":"IBGE",
                  "enabled":False,"collection_authorized":False,
                  "training_authorized":False}]}


def plano():
    return planejar_pam_1612(municipio_ibge="5107925",ano=2025,
                             codigo_produto_c81="2713",codigo_variavel="214")


def payload(v="1500",unidade="Toneladas"):
    return json.dumps([
        {"D1C":"Município (Código)","D2C":"Variável (Código)",
         "D3C":"Ano (Código)",
         "D4C":"Produto das lavouras temporárias (Código)",
         "V":"Valor","MN":"Unidade de Medida"},
        {"D1C":"5107925","D2C":"214","D3C":"2025",
         "D4C":"2713","V":v,"MN":unidade},
    ],ensure_ascii=False).encode("utf-8")


class TestIVOPAMBridge(unittest.TestCase):
    def setUp(self):
        self.db=abrir_registro()
        self.addCleanup(self.db.close)

    def registrar(self, bruto=None, *, pub="2026-09-01",
                  coleta=COLETA, referencia="2025-12-31",mime="application/json",
                  competencia="2025", schema="sidra_pam_1612_v1"):
        bruto=bruto if bruto is not None else payload()
        return registrar_snapshot(
            self.db,CAT,dataset_id="IBGE_PAM",sha256=sha256(bruto).hexdigest(),
            tamanho=len(bruto),mime=mime,schema_versao=schema,
            coletado_em=coleta,competencia=competencia,
            referencia=referencia,publicacao=pub,tipo="SINTETICO")

    def preparar(self,bruto=None,**kwargs):
        args=dict(payload=payload() if bruto is None else bruto,plano=plano(),
                  coletado_em=COLETA,corte=CORTE,registro_db=self.db,
                  variavel_autorizada="214",produto_autorizado="2713",
                  unidade_autorizada="Toneladas")
        args.update(kwargs)
        return preparar_pam_anual_asof(**args)

    def test_snapshot_conhecido_gera_candidato_anual_nao_certificado(self):
        self.registrar()
        r=self.preparar()
        self.assertEqual(r["estado"],"PAM_ANUAL_CANDIDATO_NAO_CERTIFICADO")
        self.assertIsInstance(r["observacao"],Observacao)
        self.assertEqual(r["observacao"].calendario,"ANO_CIVIL")
        self.assertEqual(r["observacao"].natureza,"INFORMADO")
        self.assertEqual(r["observacao"].valor,1500.)
        self.assertEqual(r["observacao"].regiao,"MUN_5107925")
        self.assertEqual(r["data_publicacao_declarada"],"2026-09-01")
        self.assertEqual(r["data_referencia"],"2025-12-31")
        self.assertEqual(r["competencia"],"2025")
        self.assertFalse(r["treino_real_autorizado"])
        self.assertFalse(r["label_final_certificado"])
        self.assertFalse(r["homologacao_externa_verificada"])

    def test_sem_snapshot_registrado_bloqueado(self):
        with self.assertRaises(ErroPontePAM):
            self.preparar()

    def test_sem_data_de_publicacao_conhecida_bloqueado(self):
        self.registrar(pub=None)
        with self.assertRaises(ErroPontePAM):
            self.preparar()

    def test_publicacao_posterior_ao_corte_nao_visivel(self):
        self.registrar(pub="2026-10-19")
        with self.assertRaises(ErroPontePAM):
            self.preparar(corte=datetime(2026,10,18,15,tzinfo=UTC))

    def test_snapshot_com_hash_divergente_nao_burla(self):
        self.registrar(payload("1500"))
        with self.assertRaises(ErroPontePAM):
            self.preparar(payload("1501"))

    def test_coleta_futura_nao_serve(self):
        bruto=payload()
        self.registrar(bruto,coleta="2026-10-20T17:00:00Z")
        with self.assertRaises(ErroPontePAM):
            self.preparar(bruto,coletado_em="2026-10-20T17:00:00Z")

    def test_ano_civil_nao_equivale_a_safra_comercial(self):
        self.registrar()
        r=self.preparar()
        self.assertNotEqual(r["observacao"].calendario,"SAFRA")
        self.assertEqual(r["observacao"].competencia,"2025")
        self.assertNotEqual(r["observacao"].competencia,"2024/2025")

    def test_marcadores_especiais_nao_viram_rotulos(self):
        for marcador,estado in (("X","SUPRIMIDO_SIGILO"),
                                 ("..","NAO_APLICAVEL"),
                                 ("...","NAO_DISPONIVEL"),
                                 ("0","ZERO_ARREDONDADO"),
                                 ("-","ZERO_ABSOLUTO")):
            with self.subTest(marcador=marcador):
                bruto=payload(marcador)
                self.registrar(bruto)
                r=self.preparar(bruto)
                self.assertEqual(r["estado"],"BLOQUEADO_MARCADOR_SIDRA")
                self.assertIsNone(r["observacao"])
                self.assertEqual(r["motivo"],estado)

    def test_area_plantada_109_hectares_e_aceita_com_identidade_correta(self):
        # Mesma cultura e município, mas grandeza DISTINTA da produção.
        original=json.loads(payload("250").decode("utf-8"))
        original[1]["D2C"]="109"
        original[1]["MN"]="Hectares"
        bruto=json.dumps(original,ensure_ascii=False).encode("utf-8")
        self.registrar(bruto)
        p=planejar_pam_1612(municipio_ibge="5107925",ano=2025,
            codigo_produto_c81="2713",codigo_variavel="109")
        r=self.preparar(bruto,plano=p,
                        variavel_autorizada="109",unidade_autorizada="Hectares")
        self.assertEqual(r["semantica_sidra"]["indicador"],"AREA_PLANTADA")
        self.assertEqual(r["semantica_sidra"]["familia"],"AREA")
        self.assertEqual(r["observacao"].unidade,"Hectares")
        self.assertFalse(r["treino_real_autorizado"])

    def test_quantidade_214_toneladas_nao_e_hectare(self):
        self.registrar()
        r=self.preparar()
        self.assertEqual(r["semantica_sidra"]["indicador"],"QUANTIDADE_PRODUZIDA")
        self.assertEqual(r["semantica_sidra"]["familia"],"MASSA")
        self.assertEqual(r["semantica_sidra"]["produto"],"SOJA_EM_GRAO")
        self.assertEqual(r["observacao"].unidade,"Toneladas")

    def test_unidade_incorreta_bloqueada(self):
        self.registrar()
        with self.assertRaises(ErroPontePAM):
            self.preparar(unidade_autorizada="kg")

    def test_produto_nao_aprovado_bloqueado(self):
        self.registrar()
        with self.assertRaises(ErroPontePAM):
            self.preparar(produto_autorizado="1234")

    def test_fonte_de_snapshot_trocada_nao_serve(self):
        self.registrar()
        self.db.execute("UPDATE nivon_snapshots SET fonte_id='OUTRA' WHERE dataset_id='IBGE_PAM'")
        with self.assertRaises(ErroPontePAM):
            self.preparar()

    def test_schema_nao_auditado_bloqueado(self):
        self.registrar(schema="schema_nao_validado")
        with self.assertRaises(ErroPontePAM):
            self.preparar()

    def test_coleta_alterada_nao_servira(self):
        self.registrar()
        with self.assertRaises(ErroPontePAM):
            self.preparar(coletado_em="2026-10-19T13:00:00Z")

    def test_registro_real_declarado_nao_certifica_valor_agricola(self):
        # Flag real no catálogo DE TESTE comprova apenas o contrato local;
        # não há afirmação de licença real ou homologação externa.
        cat={"datasets":[{"id":"IBGE_PAM","source_id":"IBGE",
                          "enabled":True,"collection_authorized":True,
                          "training_authorized":False}]}
        raw=payload()
        registrar_snapshot(
            self.db,cat,dataset_id="IBGE_PAM",
            sha256=sha256(raw).hexdigest(),tamanho=len(raw),
            mime="application/json",schema_versao="sidra_pam_1612_v1",
            coletado_em=COLETA,competencia="2025",
            referencia="2025-12-31",publicacao="2026-09-01",
            tipo="REAL_AUTORIZADO",
            autorizacoes=frozenset(("COLETA","ARMAZENAMENTO")),
            evidencia_direitos="DIREITO_TESTE_SEM_VALIDADE_REAL")
        r=self.preparar()
        self.assertEqual(r["tipo_snapshot"],"REAL_AUTORIZADO")
        self.assertEqual(r["observacao"].natureza,"INFORMADO")
        self.assertFalse(r["treino_real_autorizado"])
        self.assertFalse(r["label_final_certificado"])
        self.assertEqual(r["fonte_publicacao"],
                         "DECLARACAO_LEDGER_NAO_CONFIRMADA_NO_JSON")

    def test_numerico_sem_proveniencia_exata_de_arquivo_nao_aceito(self):
        raw=payload()
        self.registrar(raw)
        self.db.execute(
            "UPDATE nivon_snapshots SET bytes=bytes+1 WHERE dataset_id='IBGE_PAM'")
        with self.assertRaises(ErroPontePAM):
            self.preparar(raw)

    def test_nao_promove_estatistica_pam_para_modelo_mensal(self):
        self.registrar()
        r=self.preparar()
        from nivon.ivo_lab_temporal import _base,ErroLab
        with self.assertRaises(ErroLab):
            _base([r["observacao"]],fonte="IBGE",variavel="PAM_109",
                  produto="C81_2692",regiao="MUN_5107925",unidade="Toneladas")


if __name__=="__main__":
    unittest.main()
