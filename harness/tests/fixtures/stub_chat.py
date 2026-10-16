#!/usr/bin/env python3
"""Заглушка чата: печатает ответ на последний аргумент (вопрос)."""
from __future__ import annotations
import sys
print(f"Ответ агента на вопрос: {sys.argv[-1]}")
