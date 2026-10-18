"""Adaptador canônico ANTT/SIADE: CSV ferroviário de produção origem-destino.

Fonte CC BY (atribuição obrigatória). Estações não equivalem a municípios.
Unidades: TU toneladas úteis, TKU toneladas úteis x quilômetros.
"""
from __future__ import annotations
import csv
import io
import re
from .antt_ferrovia import ErroFerrovia, UFS
