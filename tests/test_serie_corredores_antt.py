"""Contrato mensal SIADE (CSV, SHA, vintages, RGI não é estação)."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from nivon.transporte_multimodal import interpretar_csv_antt,link_antt,ErroTransporte
from nivon.serie_corredores_antt import serie_staging
from nivon.conciliacao_corredores_ferrovia import ErroConciliacao

COLS="Mes_Ano;Ferrovia;Mercadoria_ANTT;Estacao_Origem;UF_Origem;Estacao_Destino;UF_Destino;TU;TKU\n"

def staging(root):
    for ano in (2025,2026):
        rows=(
           (f"08/{ano};RMO;Grãos - Milho;Rondonópolis;MT;Santos;SP;100;10000",
            f"08/{ano};RMO;Soja;Itiquira;MT;Santos;SP;40;4000",
            f"08/{ano};RMO;Grãos - Milho;Terminal Rondonópolis Norte;MT;Santos;SP;999;99900",
            f"08/{ano};RMO;Soja;Rondonópolis;MT;Conceiçãozinha;SP;20;2000")
            if ano==2025 else
           (f"08/{ano};RMO;Grãos - Milho;Rondonópolis;MT;Santos;SP;130;13000",
            f"08/{ano};RMO;Soja;Itiquira;MT;Santos;SP;40;4000",
            f"08/{ano};RMO;Farelo de Soja;Rondonópolis;MT;Paranagua;PR;30;3000",
            f"08/{ano};RMO;Soja;Dom Aquino;MT;Santos;SP;15;1500")
        )
        data=(COLS+"\n".join(rows)+"\n").encode("utf-8")
        sha=hashlib.sha256(data).hexdigest()
        (root/f"antt-od-{ano}.csv").write_bytes(data)
        if ano==2025:
            m={"formato":"nivon-antt-staging-v1","anos":{}}
        m["anos"][str(ano)]={
            "status":"STAGING_NAO_HOMOLOGADO","sha256":sha,
            "verificado_utc":"2026-10-23T12:00:00Z","competencia_maxima":f"{ano}-08",
            "registros":4,"url":link_antt(ano),
        }
    (root/"manifesto-antt.json").write_text(json.dumps(m),encoding="utf-8")


class TestSeriePolos(unittest.TestCase):
    def test_volumes_mercadorias_yoy_e_lacunas(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);staging(p)
            d=serie_staging(p,[2025,2026])
            by={(x["competencia"],x["polo_id"]):x for x in d["serie"]}
            self.assertEqual(d["polos_meses_com_registro"],5)
            self.assertEqual(by["2025-08","MT_RONDONOPOLIS_FERRO"]["toneladas_uteis"],"120")
            self.assertEqual(by["2026-08","MT_RONDONOPOLIS_FERRO"]["toneladas_uteis"],"160")
            self.assertEqual(by["2026-08","MT_RONDONOPOLIS_FERRO"]["variacao_yoy_pct"],"33.33")
            self.assertEqual(by["2026-08","MT_ITIQUIRA_FERRO"]["variacao_yoy_pct"],"0.00")
            self.assertEqual(by["2026-08","MT_DOM_AQUINO_BR070"]["comparacao_yoy"],"MES_ANTERIOR_AUSENTE_NAO_ZERO")
            self.assertFalse(by["2026-08","MT_DOM_AQUINO_BR070"]["terminal_confirmado"])
            self.assertEqual(by["2026-08","MT_RONDONOPOLIS_FERRO"]["produtos"][0]["produto_normalizado"],"FARELO_SOJA")
            self.assertEqual(d["competencias_distintas"],["2025-08","2026-08"])
            self.assertTrue(all(not x["transbordo_confirmado"] for x in d["serie"]))
            self.assertEqual(len(d["evidencias"]),2)
            self.assertEqual(d["abrangencia"],"FERROVIAS_FEDERAIS_CONCEDIDAS")

    def test_nao_homologar_outros_nomes_de_estacao(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);staging(p)
            doc=serie_staging(p,[2025])
            self.assertNotIn("999",str(doc["serie"]))
            self.assertFalse(any("Terminal Rondonópolis Norte" in str(x) for x in doc["serie"]))

    def test_lote_sem_sha_correto_rejeitado(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);staging(p)
            csv=p/"antt-od-2026.csv"
            csv.write_bytes(csv.read_bytes()+b"\n")
            with self.assertRaises(ErroTransporte):
                serie_staging(p,[2025,2026])

    def test_sem_fabricar_zero_ou_anos_duplicados(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);staging(p)
            doc=serie_staging(p,[2025])
            self.assertFalse(any(x["competencia"]=="2026-08" for x in doc["serie"]))
            with self.assertRaises(ErroConciliacao):
                serie_staging(p,[2025,2025])
            with self.assertRaises(ErroConciliacao):
                serie_staging(p,[2025],max_rank=0)

if __name__=="__main__":
    unittest.main()
