"""Fixtures sinteticas de portal CONAB; nenhum arquivo oficial incluido."""
from datetime import datetime, timezone
from hashlib import sha256
import unittest

from nivon.conab_indice_progresso import (
    INDICE, ErroIndiceConab, consultar_indice, extrair_edicoes_indice,
)

AGORA = datetime(2026,10,22,tzinfo=timezone.utc)
HTML = ("""<!doctype html><html><head><title>Conab</title></head><body>
<a href="/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/acompanhamento-das-lavouras-12-10-a-18-10-26">
Acompanhamento das Lavouras - 12/10 a 18/10/26</a>
<a href="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/acompanhamento-das-lavouras-12-10-a-18-10-26">Acompanhamento das Lavouras - 12/10 a 18/10/26</a>
<a href="https://ataque.org/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/acompanhamento-das-lavouras-12-10-a-18-10-26">Acompanhamento das Lavouras - 12/10 a 18/10/26</a>
<a href="javascript:alert(1)">Acompanhamento das Lavouras - 01/01 a 07/01/26</a>
<a href="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/outro-caminho">Acompanhamento das Lavouras - 01/01 a 07/01/26</a>
<a href="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/acompanhamento-das-lavouras-01-01-a-07-01-26?token=abc">Acompanhamento das Lavouras - 01/01 a 07/01/26</a>
<a href="https://www.gov.br/conab/pt-br/atuacao/informacoes-agropecuarias/safras/progresso-de-safra/acompanhamento-das-lavouras-05-10-a-11-10-26">Acompanhamento das Lavouras - 05/10 a 11/10/26</a>
</body></html>""").encode()

class TestIndiceConab(unittest.TestCase):
    def test_paginas_permitidas_sem_dados_ficticios(self):
        r = extrair_edicoes_indice(HTML, coletado_em=AGORA)
        self.assertEqual(len(r['edicoes_candidatas']),2)
        self.assertEqual(r['sha256_indice'],sha256(HTML).hexdigest())
        self.assertEqual(r['edicoes_candidatas'][0]['periodo_rotulo'],'12/10 a 18/10/26')
        self.assertIsNone(r['edicoes_candidatas'][0]['publicado_em'])
        self.assertIsNone(r['edicoes_candidatas'][0]['arquivo_xlsx'])

    def test_falha_fechada_sem_execucao(self):
        with self.assertRaises(PermissionError):
            consultar_indice()

    def test_falha_fechada_sem_origem(self):
        with self.assertRaises(ErroIndiceConab):
            extrair_edicoes_indice(HTML,origem='https://ataque.org/x')
        with self.assertRaises(ErroIndiceConab):
            extrair_edicoes_indice(HTML,origem=INDICE+'?x=1')

    def test_nao_aceita_waf_ou_payload_gigante(self):
        for b in (b'<html>request rejected</html>', b'', b'x'*2_000_001):
            with self.assertRaises(ErroIndiceConab):
                extrair_edicoes_indice(b, coletado_em=AGORA)

    def test_sem_fuso_rejeitado(self):
        with self.assertRaises(ErroIndiceConab):
            extrair_edicoes_indice(HTML,coletado_em=datetime(2026,10,22))

if __name__=='__main__':
    unittest.main()
