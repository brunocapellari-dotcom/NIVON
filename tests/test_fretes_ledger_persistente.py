"""Aceitação E2E: OfertaFrete -> snapshot -> forecast HMAC -> SQLite -> D+H.

As chaves, oferta e recibos deste teste são FICTÍCIOS. HMAC não autentica
um timestamp passado: o teste apenas verifica invariantes do software.
"""
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nivon.fretes_ledger_persistente import (
    GENESIS, ErroLedgerFrete, inicializar_ledger_frete,
    anexar_previsao_frete, anexar_lote_previsoes_frete,
    verificar_ledger_frete, avaliar_ledger_frete,
)
from nivon.fretes_previsoes_arquivadas import ErroAvaliacaoFrete
from test_fretes_previsoes_arquivadas import (
    KEY, BASE, CUTOFF, PARAMS, SOURCE, MODEL, historico, emissao, assinar,
)


def recebido(p):
    return datetime.fromisoformat(p["registrado_em"]) + timedelta(minutes=1)


def lote_detalhado(rows, h=7, indices=(1,2,3,4,5)):
    return [emissao(rows,j,h) for j in indices]


def validar(con, head):
    return verificar_ledger_frete(
        con,cabeca_esperada_sha256=head,
        chave_verificacao=KEY,emissor_esperado="fixture-archive",
    )


def gravar(con, ps, head=GENESIS):
    return anexar_lote_previsoes_frete(
        con,ps,recebimentos=[recebido(p) for p in ps],
        cabeca_anterior_sha256=head,chave_verificacao=KEY,
        emissor_esperado="fixture-archive",
    )


def medir(con,rows,head,h=7,**kw):
    opts=dict(**PARAMS,fonte_id=SOURCE,modelo_versao=MODEL,
              horizonte_dias_corridos=h,as_of=CUTOFF,
              cabeca_esperada_sha256=head,chave_verificacao=KEY,
              emissor_esperado="fixture-archive")
    opts.update(kw)
    return avaliar_ledger_frete(con,rows,**opts)


class TestLedgerFreteE2E(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        inicializar_ledger_frete(self.db)
        self.rows=historico(110)

    def tearDown(self):
        self.db.close()

    def test_fluxo_completo_tres_horizontes_e_persistencia(self):
        ps=sorted([
            emissao(self.rows,j,h)
            for j in range(1,6) for h in (7,30,90)
        ],key=lambda p:(p["registrado_em"],p["horizonte_dias_corridos"]))
        with tempfile.TemporaryDirectory() as tmp:
            filepath=Path(tmp)/"fretes_local.db"
            db=sqlite3.connect(str(filepath))
            inicializar_ledger_frete(db)
            resultado=gravar(db,ps)
            self.assertEqual(resultado["adicionados"],15)
            self.assertEqual(resultado["total"],15)
            head=resultado["cabeca_sha256"]
            db.close()
            db=sqlite3.connect(str(filepath))
            self.assertEqual(validar(db,head)["quantidade"],15)
            for h in (7,30,90):
                metric=medir(db,self.rows,head,h)
                self.assertEqual(metric["n_previsoes_declaradas"],5)
                self.assertEqual(metric["mae_brl_t"],0)
                self.assertEqual(metric["mae_baseline_zero_brl_t"],h)
                self.assertEqual(metric["ganho_mae_vs_zero"],1)
                self.assertEqual(metric["ledger_total_registros"],15)
                self.assertTrue(metric["ledger_hmac_sha256_validado"])
                self.assertFalse(metric["ancora_temporal_independente_comprovada"])
                self.assertFalse(metric["publicavel"])
            db.close()

    def test_lote_com_um_item_invalido_faz_rollback_integral(self):
        ps=lote_detalhado(self.rows)
        ps[3]["delta_previsto_brl_t"]="999"
        with self.assertRaisesRegex(ErroLedgerFrete,"HMAC"):
            gravar(self.db,ps)
        self.assertEqual(validar(self.db,GENESIS)["quantidade"],0)
        self.assertFalse(self.db.in_transaction)

    def test_lote_duplicado_cancela_sem_registros_parciais(self):
        ps=lote_detalhado(self.rows)
        ps[1]=dict(ps[0])
        with self.assertRaisesRegex(ErroLedgerFrete,"repetida"):
            gravar(self.db,ps)
        self.assertEqual(validar(self.db,GENESIS)["quantidade"],0)

    def test_single_append_e_ancora_stale_bloqueia(self):
        p=emissao(self.rows,1)
        a=anexar_previsao_frete(
            self.db,p,recebido_em=recebido(p),
            cabeca_anterior_sha256=GENESIS,
            chave_verificacao=KEY,emissor_esperado="fixture-archive",
        )
        self.assertEqual(validar(self.db,a["cabeca_sha256"])["quantidade"],1)
        with self.assertRaisesRegex(ErroLedgerFrete,"cabeça"):
            gravar(self.db,[emissao(self.rows,2)],head=GENESIS)
        self.assertEqual(validar(self.db,a["cabeca_sha256"])["quantidade"],1)

    def test_lote_inclui_lote_anterior_sem_reescrever(self):
        a=gravar(self.db,lote_detalhado(self.rows,indices=(1,2,3)))
        b=gravar(self.db,lote_detalhado(self.rows,indices=(4,5,6)),
                head=a["cabeca_sha256"])
        self.assertEqual(validar(self.db,b["cabeca_sha256"])["quantidade"],6)
        self.assertNotEqual(a["cabeca_sha256"],b["cabeca_sha256"])

    def test_registro_tardio_ou_retroativo_rejeita(self):
        p=emissao(self.rows,1)
        with self.assertRaisesRegex(ErroLedgerFrete,"tardi"):
            anexar_previsao_frete(
                self.db,p,recebido_em=recebido(p)+timedelta(days=1),
                cabeca_anterior_sha256=GENESIS,chave_verificacao=KEY,
                emissor_esperado="fixture-archive",
            )
        self.assertEqual(validar(self.db,GENESIS)["quantidade"],0)

    def test_sql_update_delete_falham(self):
        r=gravar(self.db,[emissao(self.rows,1)])
        for sql in ("UPDATE nivon_frete_previsoes_v1 SET previsao_id='x'",
                    "DELETE FROM nivon_frete_previsoes_v1"):
            with self.subTest(sql=sql),self.assertRaises(sqlite3.DatabaseError):
                self.db.execute(sql)
        self.db.rollback()
        self.assertEqual(validar(self.db,r["cabeca_sha256"])["quantidade"],1)

    def test_banco_tampered_sem_triggers_detectado(self):
        r=gravar(self.db,[emissao(self.rows,1)])
        # Dono do SQLite pode remover trigger: não é WORM. Auditoria recusa.
        self.db.execute("DROP TRIGGER nivon_frete_previsoes_sem_update")
        self.db.execute("UPDATE nivon_frete_previsoes_v1 SET previsao_json='{}'")
        self.db.commit()
        with self.assertRaises(ErroLedgerFrete):
            validar(self.db,r["cabeca_sha256"])

    def test_ancora_externa_errada_falha_fechada(self):
        r=gravar(self.db,lote_detalhado(self.rows))
        with self.assertRaisesRegex(ErroLedgerFrete,"cabeça"):
            validar(self.db,GENESIS)
        self.assertEqual(validar(self.db,r["cabeca_sha256"])["quantidade"],5)

    def test_previsoes_nao_assinadas_jamais_sao_aceitas(self):
        p=emissao(self.rows,1);p["assinatura_hmac_sha256"]="0"*64
        with self.assertRaisesRegex(ErroLedgerFrete,"HMAC"):
            gravar(self.db,[p])
        self.assertEqual(validar(self.db,GENESIS)["quantidade"],0)

    def test_mesma_origem_modelo_horizonte_outro_id_bloqueia(self):
        p=emissao(self.rows,1)
        alt=dict(p);alt.pop("assinatura_hmac_sha256")
        alt["previsao_id"]="alternate:id"
        alt=assinar(alt)
        with self.assertRaisesRegex(ErroLedgerFrete,"repetida"):
            gravar(self.db,[p,alt])

    def test_avaliacao_sem_pares_no_alvo_falha_sem_lixo_de_resultados(self):
        ps=lote_detalhado(self.rows)
        head=gravar(self.db,ps)["cabeca_sha256"]
        # j=1 atinge D+7; elimina par 2 no alvo.
        rows=[r for r in self.rows if not (
            r.data_referencia==BASE+timedelta(days=8)
            and r.pickup_entity_id=="ponto:2"
        )]
        with self.assertRaisesRegex(ErroAvaliacaoFrete,"alvo sem pares"):
            medir(self.db,rows,head)
        self.assertEqual(validar(self.db,head)["quantidade"],5)

    def test_integridade_temporal_dependente_de_prova_externa(self):
        r=gravar(self.db,lote_detalhado(self.rows))
        check=validar(self.db,r["cabeca_sha256"])
        self.assertFalse(check["ancora_temporal_externa_autenticada"])
        self.assertFalse(check["worm_fisico"])
        res=medir(self.db,self.rows,r["cabeca_sha256"])
        self.assertFalse(res["carimbo_temporal_externo_comprovado"])
        self.assertFalse(res["integridade_raw_provedor_comprovada"])


if __name__=="__main__":
    unittest.main()
