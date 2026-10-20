import unittest
from unittest.mock import patch
from scripts.inspecionar_conab_armazens_integral import main

class TestInspecaoIntegralConab(unittest.TestCase):
    def test_sem_optin_nao_acessa_rede(self):
        with patch("scripts.inspecionar_conab_armazens_integral.build_opener",
                   side_effect=AssertionError("network forbidden")):
            self.assertEqual(main([]),2)
