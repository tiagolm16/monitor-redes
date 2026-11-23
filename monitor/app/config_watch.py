"""Deteccao de alteracao de configuracao por hash SHA-256.

Um hash criptografico transforma qualquer conteudo em 64 caracteres hexadecimais. Mudar UM caractere
do arquivo muda o hash inteiro, e e inviavel produzir outro conteudo com o mesmo hash. Entao comparar
o hash de agora com o hash guardado (baseline) mostra se o arquivo foi alterado.

A baseline e criada na primeira execucao (confiamos no estado inicial) e guardada no SQLite junto com o
conteudo do arquivo, para podermos mostrar um diff do que mudou.
"""
import difflib
import hashlib
import os
import time

from . import storage

CONFIG_DIR = os.getenv("CONFIG_DIR", "/config")
MAX_CONTEUDO = 200_000  # arquivos maiores que isso so guardam o hash (sem diff)


def varrer() -> dict[str, dict]:
    """Le todos os arquivos de CONFIG_DIR: {caminho_relativo: {sha, conteudo}}."""
    saida = {}
    for raiz, _, arquivos in os.walk(CONFIG_DIR):
        for nome in arquivos:
            caminho = os.path.join(raiz, nome)
            rel = os.path.relpath(caminho, CONFIG_DIR).replace(os.sep, "/")
            try:
                with open(caminho, "rb") as f:
                    dados = f.read()
            except OSError:
                continue
            conteudo = None
            if len(dados) <= MAX_CONTEUDO:
                conteudo = dados.decode("utf-8", errors="replace")
            saida[rel] = {"sha": hashlib.sha256(dados).hexdigest(), "conteudo": conteudo}
    return saida


def comparar() -> list[dict]:
    """Compara o estado atual com a baseline. Cria a baseline se ainda nao existir."""
    atual = varrer()
    base = storage.config_baseline_get()
    if not base:
        storage.config_baseline_set(atual)
        base = {k: {"sha": v["sha"], "conteudo": v["conteudo"], "ts": time.time()} for k, v in atual.items()}
    arquivos = []
    for rel in sorted(set(atual) | set(base)):
        a, b = atual.get(rel), base.get(rel)
        if a and b and a["sha"] == b["sha"]:
            status = "ok"
        elif a and b:
            status = "alterado"
        elif a:
            status = "novo"
        else:
            status = "removido"
        item = {
            "arquivo": rel, "status": status,
            "hash_baseline": b["sha"] if b else None, "hash_atual": a["sha"] if a else None,
            "diff": "",
        }
        if status != "ok":
            antigo = ((b or {}).get("conteudo") or "").splitlines()
            novo = ((a or {}).get("conteudo") or "").splitlines()
            linhas = list(difflib.unified_diff(antigo, novo, "baseline", "atual", lineterm="", n=1))
            item["diff"] = "\n".join(linhas[:40]) + ("\n..." if len(linhas) > 40 else "")
        arquivos.append(item)
    return arquivos


def aceitar_baseline() -> None:
    """Aceita o estado atual como a nova baseline (mudanca autorizada)."""
    storage.config_baseline_set(varrer(), substituir=True)
