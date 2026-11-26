"""Funcoes comuns de gravar.py e montar.py: localizar o ffmpeg, preparar os audios e medir duracoes.

Audios reais: video/audio/cena01.m4a ... cena08.m4a (mp3, wav, aac, ogg ou flac tambem servem).
Modo provisorio (--provisorio): gera audios de silencio com a duracao estimada em video/cenas.json.
"""
import glob
import json
import os
import shutil
import subprocess
from pathlib import Path

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parent
AUDIO = PASTA / "audio"
TMP = PASTA / "tmp"
RAW = PASTA / "raw"
OUT = PASTA / "out"
CENAS = json.loads((PASTA / "cenas.json").read_text(encoding="utf-8"))
IDS = list(CENAS)
EXTENSOES = ("m4a", "mp3", "wav", "aac", "ogg", "flac")

BASE = "http://localhost:8000"
MAILPIT = "http://localhost:8025"
LOADGEN = "http://localhost:8090"


def achar(nome: str) -> str:
    """Localiza ffmpeg/ffprobe: no PATH ou na pasta onde o winget instala."""
    p = shutil.which(nome)
    if p:
        return p
    padrao = os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg-*\bin\{nome}.exe")
    achados = glob.glob(padrao)
    if achados:
        return achados[0]
    raise SystemExit(f"{nome} nao encontrado. Instale com: winget install Gyan.FFmpeg")


FFMPEG = achar("ffmpeg")
FFPROBE = achar("ffprobe")


def rodar(args, **kw):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if r.returncode != 0:
        raise RuntimeError(f"falhou: {' '.join(map(str, args))[:200]}\n{r.stderr[-1500:]}")
    return r


def duracao(arquivo) -> float:
    r = rodar([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(arquivo)])
    return float(r.stdout.strip())


def audio_do_usuario(cena: str):
    for ext in EXTENSOES:
        p = AUDIO / f"{cena}.{ext}"
        if p.exists():
            return p
    return None


def preparar_audios(provisorio: bool) -> dict:
    """Retorna {cena: (caminho_do_audio_pronto, duracao_em_segundos)}.
    Audio real: corta silencio longo do comeco e do fim e normaliza o volume (loudnorm).
    Provisorio: silencio com a duracao estimada."""
    destino = TMP / ("audio_provisorio" if provisorio else "audio_pronto")
    destino.mkdir(parents=True, exist_ok=True)
    saida = {}
    faltando = []
    for cena in IDS:
        alvo = destino / f"{cena}.m4a"
        if provisorio:
            seg = CENAS[cena]["segundos"]
            rodar([FFMPEG, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(seg),
                   "-c:a", "aac", "-b:a", "128k", str(alvo)])
        else:
            origem = audio_do_usuario(cena)
            if origem is None:
                faltando.append(cena)
                continue
            # Se o audio original nao mudou desde o ultimo processamento, reaproveita
            if not alvo.exists() or alvo.stat().st_mtime < origem.stat().st_mtime:
                corta = ("silenceremove=start_periods=1:start_duration=0.1:start_threshold=-45dB:start_silence=0.25,"
                         "areverse,"
                         "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-45dB:start_silence=0.35,"
                         "areverse")
                rodar([FFMPEG, "-y", "-i", str(origem), "-af", f"{corta},loudnorm=I=-16:TP=-1.5:LRA=11",
                       "-ar", "44100", "-ac", "2", "-c:a", "aac", "-b:a", "160k", str(alvo)])
        saida[cena] = (alvo, duracao(alvo))
    if faltando:
        raise SystemExit("Faltam audios em video/audio/: " + ", ".join(f"{c}.m4a" for c in faltando))
    return saida
