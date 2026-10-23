import tempfile
import unittest
from pathlib import Path

from nivon.antaq_replica_detalhe import (
    ErroReplicaANTAQ, classificar_sh4, normalizar_texto,
    resumo_parquets, resumo_agro, soma_carga_unica_2025
)


class TestHidroviaProduto(unittest.TestCase):
    def test_taxonomia_cautelosa(self):
        self.assertEqual(classificar_sh4("1201"), "SOJA")
        self.assertEqual(classificar_sh4("1005"), "MILHO")
        self.assertEqual(classificar_sh4("2304"), "FARELO_DE_SOJA")
        self.assertEqual(classificar_sh4("3105"), "FERTILIZANTES_CAP31")
        self.assertIn("NAO_SO_DIESEL", classificar_sh4("2710"))
        self.assertEqual(normalizar_texto("NavegaÃ§Ã£o Interior"), "Navegação Interior")

    def test_join_e_grupos_agro(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as temp:
            h = Path(temp) / "hidro.parquet"
            c = Path(temp) / "carga.parquet"
            pq.write_table(pa.table({
                "IDCarga": [101.0, 102.0, 103.0],
                "Hidrovia": ["Hidrovia do Madeira", "Hidrovia do TapajÃ³s", "Hidrovia do Madeira"],
                "ValorMovimentado": [100.0, 55.3, 40.0]}), h)
            pq.write_table(pa.table({
                "IDCarga": [101.0, 102.0, 103.0],
                "Tipo Navegação": ["Interior", "Longo Curso", "Interior"],
                "CDMercadoria": ["1201", "1005", "3105"],
                "VLPesoCargaBruta": [100.0, 55.3, 40.0],
                "Sentido": ["Embarcados", "Embarcados", "Desembarcados"]}), c)
            doc = resumo_parquets(h,c)
            self.assertEqual(doc["linhas_qualificadas"],3)
            self.assertEqual(doc["linhas_sem_vinculo"],0)
            agro = resumo_agro(doc)
            self.assertEqual(len(agro["recortes_agro"]),3)
            self.assertEqual(agro["recortes_agro"][0]["grupo_produto"], "SOJA")
            self.assertEqual(agro["recortes_agro"][1]["hidrovia"],"Hidrovia do Tapajós")
            unico = soma_carga_unica_2025(h,c)
            self.assertEqual(unico["total_ton"], 140.0)
            self.assertEqual(unico["cargas_unicas"],2)
            self.assertEqual(unico["cobertura_de_classificacao_hidrovia_pct"],100.0)
            pq.write_table(pa.table({
                "IDCarga": [101.0, 101.0, 102.0, 103.0],
                "Hidrovia": ["Hidrovia do Madeira","Hidrovia do Tapajós",
                             "Hidrovia do Tapajós","Hidrovia do Madeira"],
                "ValorMovimentado": [100.0, 100.0, 55.3, 40.0]}), h)
            unico_repetido = soma_carga_unica_2025(h,c)
            self.assertEqual(unico_repetido["total_ton"], 140.0)
            self.assertEqual(unico_repetido["cargas_unicas"], 2)


    def test_duplicacao_de_id_impede_soma_dupla(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as temp:
            h=Path(temp)/"h.parquet"
            c=Path(temp)/"c.parquet"
            pq.write_table(pa.table({"IDCarga":[1.0],"Hidrovia":["Madeira"],
                 "ValorMovimentado":[10.0]}),h)
            pq.write_table(pa.table({"IDCarga":[1.0,1.0],
                "Tipo Navegação":["Interior","Interior"],
                "CDMercadoria":["1201","1201"],"Sentido":["Embarcados","Embarcados"]}),c)
            with self.assertRaises(ErroReplicaANTAQ):
                resumo_parquets(h,c)


if __name__=="__main__":
    unittest.main()
