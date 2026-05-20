#!/bin/bash
# Ищем строки, начинающиеся с SELECT, INSERT, UPDATE, DELETE внутри PHP файлов
grep -rEi "SELECT|INSERT|UPDATE|DELETE" $1 | grep -v "vendor"