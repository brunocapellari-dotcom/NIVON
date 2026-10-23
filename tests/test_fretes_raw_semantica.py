"""Testes adversariais de JSON estruturado original versus registro."""
import json
import unittest
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from hashlib import sha256

from nivon.fretes_raw_semantica import CONTRATO, conferir_semantica_json_estruturado
from nivon.quant_core import ErroQuantitativo
from nivon.fretes_registros import OfertaFrete,consolidar_ofertas


def fixture():
    d=datetime(2026,10,20,16,tzinfo=timezone.utc)
    x=OfertaFrete(
        publicacao_id="pub:1",registro_id="reg:1",oferta_id="oferta:1",
        municipio_ibge="5107925",pickup_entity_id="fazenda:1",
        transportadora_id="transportadora:1",destino_ibge="5107602",
        descarga_entity_id="terminal:1",produto="SOJA",equipamento="RODOTREM",
        regime="PJ",frete_base_brl_t=Decimal("150.25"),
        pedagio_brl_t=Decimal("10.10"),frete_cheio_brl_t=Decimal("160.35"),
        data_referencia=d.date(),data_publicacao=d,
        data_coleta=d+timedelta(hours=1),fonte_id="FONTE_OFFLINE",
    )
    row=consolidar_ofertas([x])["registros"][0]
    fields=("registro_id","oferta_id","fonte_id","municipio_ibge","pickup_entity_id",
            "transportadora_id","destino_ibge","descarga_entity_id","produto",
            "equipamento","regime","data_referencia","data_publicacao",
            "frete_base_brl_t","pedagio_brl_t","frete_cheio_brl_t")
    obj={k:row[k] for k in fields}
    obj.update({"tipo":"FRETE_ANUNCIADO","contrato":CONTRATO,
                "publicacao_id":row["publicacoes_origem"][0]})
    return row,obj


def raw(obj):
    return json.dumps(obj,ensure_ascii=False).encode()


class TestRAWValores(unittest.TestCase):
    def test_campos_equivalentes_incluindo_decimais(self):
        row,obj=fixture()
        v=conferir_semantica_json_estruturado(raw(obj),row)
        self.assertEqual(v["raw_sha256"],sha256(raw(obj)).hexdigest())
        self.assertEqual(v["campos_comparados"],17)
        self.assertFalse(v["publicavel"])

    def test_adulteracao_de_cada_campo_economico_nao_passa(self):
        row,obj=fixture()
        for name in ("frete_base_brl_t","pedagio_brl_t","frete_cheio_brl_t",
                     "regime","descarga_entity_id","pickup_entity_id",
                     "transportadora_id","destino_ibge","produto","equipamento"):
            altered=dict(obj)
            altered[name]="PF" if name=="regime" else "900.55" if name.endswith("_brl_t") else "OUTRO"
            with self.subTest(field=name),self.assertRaises(ErroQuantitativo):
                conferir_semantica_json_estruturado(raw(altered),row)

    def test_chaves_duplicadas_e_numeros_inseguros(self):
        row,obj=fixture()
        base=raw(obj)
        dup=base[:-1]+b',"produto":"MILHO"}'
        with self.assertRaisesRegex(ErroQuantitativo,"duplicado"):
            conferir_semantica_json_estruturado(dup,row)
        for value in ("NaN","Infinity","1e309","true","-5","1,000","01","1.000000"):
            changed=dict(obj)
            changed["frete_base_brl_t"]=value
            with self.subTest(value=value),self.assertRaises(ErroQuantitativo):
                conferir_semantica_json_estruturado(raw(changed),row)

    def test_raw_livre_nao_promovido_a_estruturado(self):
        row,_=fixture()
        for b in (b"Milho 150 R$/t","áudio".encode(),b"<html>fake</html>",b"{}"):
            with self.subTest(size=len(b)),self.assertRaises(ErroQuantitativo):
                conferir_semantica_json_estruturado(b,row)

    def test_documentos_extra_incompletos_ou_schema_errado(self):
        row,obj=fixture()
        for key in ("registro_id","fonte_id","publicacao_id","data_publicacao"):
            missing=dict(obj)
            missing.pop(key)
            with self.subTest(key=key),self.assertRaises(ErroQuantitativo):
                conferir_semantica_json_estruturado(raw(missing),row)
        extra=dict(obj);extra["permission"]="PUBLICAR"
        with self.assertRaises(ErroQuantitativo):
            conferir_semantica_json_estruturado(raw(extra),row)
        wrong=dict(obj);wrong["contrato"]="PARSED_FROM_WHATSAPP_NOT_RAW"
        with self.assertRaises(ErroQuantitativo):
            conferir_semantica_json_estruturado(raw(wrong),row)

    def test_zeros_e_tipos_monetarios(self):
        row,obj=fixture()
        for value in (None,True,150.25,0,"-1","9999999999999","1_000","0."):
            changed=dict(obj);changed["frete_base_brl_t"]=value
            with self.subTest(value=value),self.assertRaises(ErroQuantitativo):
                conferir_semantica_json_estruturado(raw(changed),row)


if __name__=="__main__":
    unittest.main()
