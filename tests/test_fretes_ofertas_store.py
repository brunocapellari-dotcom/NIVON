"""Teste de fluxo: OfertaFrete -> store SQLite -> consulta -> análise arquivada.

Os comprovantes são SOMENTE digests declarados de fixtures, não prova RAW.
"""
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from nivon.fretes_ofertas_store import (
    GENESIS, ErroStoreOfertaFrete, inicializar_store_ofertas_frete,
    anexar_lote_ofertas_frete, verificar_store_ofertas_frete,
)
from nivon.fretes_ledger_persistente import (
    GENESIS as PREV_GENESIS, inicializar_ledger_frete,
    anexar_lote_previsoes_frete, avaliar_ledger_frete,
)
from test_fretes_previsoes_arquivadas import (
    KEY, CUTOFF, PARAMS, SOURCE, MODEL, historico, emissao,
)
from test_fretes_ledger_persistente import recebido


def evidencias(rows):
    return {x.registro_id: {
        "raw_sha256":"a"*64,"direitos_sha256":"b"*64,
        "resolucao_sha256":"c"*64,"provedor":"fixture",
        "tenant_pseudonimizado":"tenant_sintetico",
    } for x in rows}


def gravar_em_lotes(db, rows):
    head=GENESIS
    for inicio in range(0,len(rows),500):
        parte=rows[inicio:inicio+500]
        r=anexar_lote_ofertas_frete(
            db,parte,evidencias=evidencias(parte),cabeca_anterior_sha256=head,
        )
        head=r["cabeca_sha256"]
    return head


class TestStoreOfertasE2E(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        inicializar_store_ofertas_frete(self.db)
        self.rows=historico(110)

    def test_persistir_recuperar_e_avaliar_tres_horizontes(self):
        head=gravar_em_lotes(self.db,self.rows)
        v=verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=head,
        )
        self.assertEqual(v["registros"],220)
        self.assertEqual(v["ofertas"],self.rows)
        self.assertFalse(v["raw_autenticado_externamente"])
        self.assertFalse(v["direitos_comprovados_externamente"])
        inicializar_ledger_frete(self.db)
        ps=sorted([
            emissao(self.rows,j,h) for j in range(1,6) for h in (7,30,90)
        ],key=lambda p:(p["registrado_em"],p["horizonte_dias_corridos"]))
        l=anexar_lote_previsoes_frete(
            self.db,ps,recebimentos=[recebido(p) for p in ps],
            cabeca_anterior_sha256=PREV_GENESIS,chave_verificacao=KEY,
            emissor_esperado="fixture-archive",
        )
        for h in (7,30,90):
            r=avaliar_ledger_frete(
                self.db,v["ofertas"],
                cabeca_esperada_sha256=l["cabeca_sha256"],
                chave_verificacao=KEY,emissor_esperado="fixture-archive",
                as_of=CUTOFF,fonte_id=SOURCE,modelo_versao=MODEL,
                horizonte_dias_corridos=h,**PARAMS,
            )
            self.assertEqual(r["mae_brl_t"],0)
            self.assertFalse(r["publicavel"])

    def test_lote_com_id_repetido_nao_persiste_metade(self):
        a=self.rows[:10]
        b=list(a)+[a[2]]
        with self.assertRaises(ErroStoreOfertaFrete):
            anexar_lote_ofertas_frete(
                self.db,b,evidencias=evidencias(b),
                cabeca_anterior_sha256=GENESIS,
            )
        self.assertEqual(verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=GENESIS
        )["registros"],0)

    def test_inconsistencia_evidencia_recusada(self):
        rows=self.rows[:10]
        e=evidencias(rows)
        del e[rows[3].registro_id]
        with self.assertRaisesRegex(ErroStoreOfertaFrete,"evidência"):
            anexar_lote_ofertas_frete(
                self.db,rows,evidencias=e,cabeca_anterior_sha256=GENESIS,
            )

    def test_arquivo_store_reabertura(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"ofertas.sqlite"
            db=sqlite3.connect(p)
            inicializar_store_ofertas_frete(db)
            head=gravar_em_lotes(db,self.rows[:20])
            db.close()
            with sqlite3.connect(p) as reaberto:
                v=verificar_store_ofertas_frete(
                    reaberto,cabeca_esperada_sha256=head
                )
                self.assertEqual(v["ofertas"],self.rows[:20])

    def test_tentativa_update_delete_impedida(self):
        head=gravar_em_lotes(self.db,self.rows[:10])
        for sql in (
            "UPDATE nivon_frete_ofertas_v1 SET registro_id='ALTERADO'",
            "DELETE FROM nivon_frete_ofertas_v1",
        ):
            with self.subTest(sql=sql),self.assertRaises(sqlite3.DatabaseError):
                self.db.execute(sql)
        self.db.rollback()
        self.assertEqual(verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=head
        )["registros"],10)

    def test_tampering_detectado_mas_nao_worm_fisico(self):
        head=gravar_em_lotes(self.db,self.rows[:10])
        self.db.execute("DROP TRIGGER nivon_frete_ofertas_sem_update")
        self.db.execute("UPDATE nivon_frete_ofertas_v1 SET payload_json='{}'")
        self.db.commit()
        with self.assertRaises(ErroStoreOfertaFrete):
            verificar_store_ofertas_frete(
                self.db,cabeca_esperada_sha256=head
            )

    def test_cabeca_falsa_ou_truncamento_bloqueia(self):
        head=gravar_em_lotes(self.db,self.rows[:10])
        with self.assertRaisesRegex(ErroStoreOfertaFrete,"cabeça"):
            verificar_store_ofertas_frete(
                self.db,cabeca_esperada_sha256=GENESIS
            )
        self.assertEqual(verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=head
        )["registros"],10)

    def test_segunda_rodada_sem_cabeca_atual_bloqueia(self):
        head=gravar_em_lotes(self.db,self.rows[:10])
        with self.assertRaisesRegex(ErroStoreOfertaFrete,"cabeça"):
            anexar_lote_ofertas_frete(
                self.db,self.rows[10:20],
                evidencias=evidencias(self.rows[10:20]),
                cabeca_anterior_sha256=GENESIS,
            )
        self.assertEqual(verificar_store_ofertas_frete(
            self.db,cabeca_esperada_sha256=head
        )["registros"],10)


if __name__=="__main__":
    unittest.main()
