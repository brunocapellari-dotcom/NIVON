"""Testes do parser CSV experimental: RAW presente, mudança de bytes e no-go."""
import csv
import hashlib
import io
import unittest
from datetime import datetime

from nivon.conab_replay_raw import (
    CAMPOS_CSV, PARSER_ID, ErroReplayConab, reexecutar_csv_conab,
)

SOURCE="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/fixture"
CAPTURE="2026-10-20T12:00:00+00:00"
PUBLICATION="2026-10-19T11:00:00+00:00"
BASE={
    "cultura":"Soja","safra":"2026/27","operacao":"Semeadura",
    "uf":"MT","semana_atual":"2026-10-18",
    "pct_ano_anterior":"0.32", "pct_semana_anterior":"0.27",
    "pct_semana_atual":"0.35","pct_media_5_anos":"0.30",
    "revisado":"","n_estados":"","cobertura_area_pct":"",
}


def payload(rows=None, *, header=CAMPOS_CSV):
    out=io.StringIO(newline="")
    writer=csv.writer(out)
    writer.writerow(header)
    for r in (rows if rows is not None else [BASE]):
        writer.writerow([r.get(k,"") for k in header])
    return out.getvalue().encode("utf-8")


def run(raw, **kw):
    return reexecutar_csv_conab(
        raw, sha256_origem=kw.get("hash",hashlib.sha256(raw).hexdigest()),
        url_origem=kw.get("url",SOURCE), coletado_em=kw.get("capture",CAPTURE),
        publicado_em=kw.get("publication",PUBLICATION))


class TestConabCsvReplay(unittest.TestCase):
    def test_bytes_sinteticos_executam_parser_e_normalizam(self):
        r=run(payload())
        self.assertEqual(r["parser_id"],PARSER_ID)
        self.assertEqual(r["observacoes"],1)
        d=next(iter(r["mapa_semantico"].values()))
        self.assertIn('"pct_semana_atual":0.35',d)
        self.assertEqual(len(r["parser_codigo_sha256"]),64)
        self.assertFalse(r["formato_oficial_conab_homologado"])
        self.assertFalse(r["publicacao_extraida_do_arquivo"])
        self.assertFalse(r["migracao_permitida"])

    def test_mudanca_raw_sem_atualizar_hash_rejeitada(self):
        raw=payload()
        changed=payload([{**BASE,"pct_semana_atual":"0.36"}])
        with self.assertRaises(ErroReplayConab):
            run(changed,hash=hashlib.sha256(raw).hexdigest())

    def test_mudanca_raw_e_hash_muda_valores(self):
        a=run(payload())
        b=run(payload([{**BASE,"pct_semana_atual":"0.36"}]))
        self.assertNotEqual(a["mapa_semantico"],b["mapa_semantico"])
        self.assertNotEqual(a["raw_sha256"],b["raw_sha256"])

    def test_sem_pub_nao_cria_publicacao(self):
        r=run(payload(),publication=None)
        self.assertIn('"publicacao":null',next(iter(r["mapa_semantico"].values())))

    def test_publicacao_depois_da_coleta_rejeitada(self):
        with self.assertRaises(ErroReplayConab):
            run(payload(),publication="2026-10-21T12:00:00+00:00")

    def test_sem_fuso_rejeitado(self):
        with self.assertRaises(ErroReplayConab):
            run(payload(),capture="2026-10-20T12:00:00")

    def test_url_host_nao_oficial_rejeitado(self):
        with self.assertRaises(ErroReplayConab):
            run(payload(),url="https://attacker.example/")

    def test_cabecalho_reordenado_rejeitado(self):
        with self.assertRaises(ErroReplayConab):
            run(payload(header=tuple(reversed(CAMPOS_CSV))))

    def test_linha_extra_coluna_rejeitada(self):
        raw=payload()+b"1,2,3,4,5,6,7,8,9,10,11,12,13\n"
        with self.assertRaises(ErroReplayConab):
            run(raw)

    def test_nan_e_expoente_recusados(self):
        for v in ("nan","NaN","1e-2","-0.1","1.01","0,5",""):
            with self.subTest(v=v),self.assertRaises(ErroReplayConab):
                run(payload([{**BASE,"pct_semana_atual":v}]))

    def test_media_estados_com_cobertura_explicita(self):
        row={**BASE,"uf":"MEDIA_ESTADOS","n_estados":"12","cobertura_area_pct":"0.80"}
        r=run(payload([row]))
        self.assertIn('"uf":"MEDIA_ESTADOS"',next(iter(r["mapa_semantico"].values())))
        self.assertIn('"n_estados":12',next(iter(r["mapa_semantico"].values())))

    def test_media_estados_sem_n_recusada(self):
        with self.assertRaises(ErroReplayConab):
            run(payload([{**BASE,"uf":"MEDIA_ESTADOS"}]))

    def test_cobertura_nacional_para_uf_recusada(self):
        with self.assertRaises(ErroReplayConab):
            run(payload([{**BASE,"n_estados":"12"}]))

    def test_mesma_chave_repetida_recusada(self):
        with self.assertRaises(ErroReplayConab):
            run(payload([BASE,BASE]))

    def test_uf_brasil_inferida_bloqueada(self):
        with self.assertRaises(ErroReplayConab):
            run(payload([{**BASE,"uf":"BR"}]))

    def test_conteudo_html_disfarcado_de_csv_rejeitado(self):
        with self.assertRaises(ErroReplayConab):
            run(b"<html>bloqueio</html>")

    def test_csv_invalido_utf8_bloqueado(self):
        with self.assertRaises(ErroReplayConab):
            run(payload()+b"\xff")

    def test_csv_vazio_ou_so_cabecalho_bloqueado(self):
        with self.assertRaises(ErroReplayConab):
            run(payload([]))

    def test_booleano_revisado_normalizado(self):
        r=run(payload([{**BASE,"revisado":"true"}]))
        self.assertIn('"revisado":true',next(iter(r["mapa_semantico"].values())))

    def test_codigo_nao_recebe_direito_por_csv(self):
        r=run(payload())
        self.assertFalse(r["direitos_de_uso_verificados"])
        self.assertFalse(r["origem_conab_comprovada"])


if __name__=="__main__":
    unittest.main()
