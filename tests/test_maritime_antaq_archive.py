"""ANTAQ official historical archives: synthetic, offline, no network."""
import io
import zipfile
import unittest
from datetime import datetime, timezone

from nivon.maritime.antaq_archive import analyze_antaq_archive

STAMP = "2026-10-20T14:00:00Z"
AT_HEADER = "IDAtracacao;Ano;Mes;Porto Atracação;Terminal;SGUF;Data Atracação\n"
CA_HEADER = "IDAtracacao;CDMercadoria;VLPesoCargaBruta;Sentido;Natureza da Carga;Tipo Navegação\n"
ME_HEADER = "CDMercadoria;Nomenclatura Simplificada Mercadoria\n"


def makezip(
    atr=AT_HEADER+"100;2024;jan;Santos;TEG;SP;22/12/2023 12:00\n"
                  +"200;2024;fev;Santarém;Fertilizantes;PA;10/02/2024 11:00\n",
    cargo=CA_HEADER+"100;1201;1.234,50;Embarcados;Granel Sólido;Longo Curso\n"
                    +"100;1201;100,50;Embarcados;Granel Sólido;Longo Curso\n"
                    +"200;3105;450,00;Desembarcados;Granel Sólido;Longo Curso\n",
    merc=ME_HEADER+"1201;Soja\n3105;Fertilizantes\n",
    extra=None,
):
    items = {
        "2024Atracacao.txt": atr,
        "2024Carga.txt": cargo,
        "2024Mercadoria.txt": merc,
    }
    if extra:
        items.update(extra)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, value in items.items():
            z.writestr(name, value.encode("utf-8-sig"))
    return buf.getvalue()


def evaluate(payload, **kwargs):
    return analyze_antaq_archive(
        payload, year=2024, source_id="ANTAQ_EA_2024_ARCHIVE",
        collected_at=STAMP, rights_to_read=True, **kwargs
    )


class TestAntaqArchive(unittest.TestCase):
    def test_rights_missing_fail_closed(self):
        with self.assertRaises(PermissionError):
            analyze_antaq_archive(makezip(), year=2024, source_id="ANTAQ",
                                  collected_at=STAMP)

    def test_one_atracacao_many_cargas_are_not_many_ships(self):
        out = evaluate(makezip())
        self.assertEqual(out.count_atracacoes_distinct, 2)
        self.assertEqual(out.count_carga_rows, 3)
        self.assertEqual(out.count_aggregated_groups, 2)
        self.assertFalse(out.publication_allowed)
        soja = next(x for x in out.monthly_port_cargo if x["commodity_name_published"] == "Soja")
        self.assertEqual(soja["gross_tonnes_published"], "1335.00")
        self.assertEqual(soja["source_cargo_rows"], 2)
        self.assertIsNone(soja["observed_ship_count"])
        self.assertEqual(soja["competence"], "2024-01")
        self.assertEqual(soja["evidence_class"], "DECLARADO_ESTATISTICO_ANTAQ")

    def test_publication_year_can_differ_from_berth_date(self):
        out = evaluate(makezip())
        self.assertEqual(out.archive_year, 2024)
        self.assertEqual(out.monthly_port_cargo[0]["year"], 2024)
        self.assertEqual(out.status, "OFFLINE_SOURCE_FILE_ONLY")

    def test_orphan_cargo_record_is_counted_not_silently_joined(self):
        archive = makezip(cargo=CA_HEADER+"999;1201;100,00;Embarcados;Granel Sólido;Longo Curso\n"
                                     +"100;1201;80,00;Embarcados;Granel Sólido;Longo Curso\n")
        out = evaluate(archive)
        self.assertEqual(out.count_carga_without_atracacao, 1)
        self.assertEqual(out.count_carga_rows, 2)
        self.assertEqual(out.monthly_port_cargo[0]["gross_tonnes_published"], "80.00")
        self.assertIn("cargo_orphan_rows: reconciliar IDAtracacao sem converter zero", out.warnings)

    def test_missing_commodity_keeps_code_and_warns(self):
        out = evaluate(makezip(cargo=CA_HEADER+"100;9999;10,50;Embarcados;Granel Sólido;Longo Curso\n"))
        self.assertEqual(out.monthly_port_cargo[0]["commodity_code"], "9999")
        self.assertIsNone(out.monthly_port_cargo[0]["commodity_name_published"])
        self.assertIn("unknown_commodity_code_in_source", out.warnings)

    def test_conflicting_commodity_duplicates_rejected(self):
        merc=ME_HEADER+"1201;Soja\n1201;Trigo\n"
        with self.assertRaisesRegex(ValueError, "contraditorio"):
            evaluate(makezip(merc=merc))

    def test_duplicate_berth_id_rejected(self):
        atr=AT_HEADER+"100;2024;jan;Santos;T;SP;10/01/2024 12:00\n"*2
        with self.assertRaisesRegex(ValueError, "repetida"):
            evaluate(makezip(atr=atr))

    def test_year_mismatch_rejected(self):
        atr=AT_HEADER+"100;2023;jan;Santos;T;SP;10/01/2024 12:00\n"
        with self.assertRaisesRegex(ValueError, "Ano"):
            evaluate(makezip(atr=atr))

    def test_negative_weight_rejected(self):
        cargo=CA_HEADER+"100;1201;-10,00;Embarcados;Granel Sólido;Longo Curso\n"
        with self.assertRaisesRegex(ValueError, "peso"):
            evaluate(makezip(cargo=cargo))

    def test_ambiguous_month_rejected(self):
        atr=AT_HEADER+"100;2024;maia;Santos;T;SP;10/01/2024 12:00\n"
        with self.assertRaises(ValueError):
            evaluate(makezip(atr=atr))

    def test_wrong_headers_rejected(self):
        cargo=CA_HEADER.replace("VLPesoCargaBruta","INVALID_WEIGHT")+"100;1201;1,00;Embarcados;Granel Sólido;Longo Curso\n"
        with self.assertRaisesRegex(ValueError, "esquema incompleto"):
            evaluate(makezip(cargo=cargo))

    def test_zip_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, "insegura"):
            evaluate(makezip(extra={"../evil.py":"print('bad')"}))

    def test_zip_enumeration_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError, "arquivo duplicado"):
            evaluate(makezip(extra={"folder/2024Atracacao.txt":AT_HEADER}))

    def test_max_rows_does_not_silently_truncate(self):
        with self.assertRaisesRegex(ValueError, "limite"):
            evaluate(makezip(),max_cargo_rows=2)

    def test_naive_collection_date_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            analyze_antaq_archive(makezip(),year=2024,source_id="ANTAQ",
                                  collected_at="2026-10-20T14:00:00",rights_to_read=True)

    def test_corrupt_zip_rejected(self):
        with self.assertRaises(zipfile.BadZipFile):
            evaluate(b"not a ZIP")

    def test_no_data_release_unless_validated(self):
        out = evaluate(makezip())
        self.assertEqual(out.classification, "HISTORICO_MENSAL_DECLARADO_NAO_AIS")
        self.assertFalse(out.to_dict()["publication_allowed"])


if __name__ == "__main__":
    unittest.main()
