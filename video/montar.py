"""Monta o video final: abertura + 8 cenas (video gravado + narracao) + encerramento.

Uso:
    python video/montar.py                # audios reais de video/audio/
    python video/montar.py --provisorio   # audios de silencio (para testar)
Saida: video/out/video_explicativo.mp4 (H.264, 1080p, preset veryfast, AAC).
Sem legendas.
"""
import argparse
import shutil
import sys

from comum import FFMPEG, IDS, OUT, RAW, TMP, CENAS, duracao, preparar_audios, rodar

SEG = TMP / "segmentos"
ABERTURA_S = 5
ENCERRAMENTO_S = 6
VIDEO = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", "30"]
AUDIO = ["-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]


def cartao(nome, segundos):
    """Imagem estatica vira um clipe com audio de silencio (mesmos parametros dos outros clipes)."""
    saida = SEG / f"{nome}.mp4"
    rodar([FFMPEG, "-y", "-loop", "1", "-framerate", "30", "-i", str(RAW / f"{nome}.png"),
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(segundos),
           "-vf", "scale=1920:1080,format=yuv420p", *VIDEO, *AUDIO, str(saida)])
    return saida


def cena(cena_id, audio):
    """Une o video gravado da cena com a narracao. A saida dura o tempo do video; o audio e completado
    com silencio se for mais curto."""
    bruto = RAW / f"{cena_id}.webm"
    if not bruto.exists():
        sys.exit(f"Falta {bruto.name}. Rode: python video/gravar.py {cena_id}")
    saida = SEG / f"{cena_id}.mp4"
    rodar([FFMPEG, "-y", "-ss", "0.5", "-i", str(bruto), "-i", str(audio),   # descarta o 1o meio segundo (carregamento)
           
           "-filter_complex", "[0:v]scale=1920:1080:flags=lanczos,fps=30,format=yuv420p[v];[1:a]apad[a]",
           "-map", "[v]", "-map", "[a]", "-shortest", *VIDEO, *AUDIO, str(saida)])
    return saida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provisorio", action="store_true")
    args = ap.parse_args()
    audios = preparar_audios(args.provisorio)
    shutil.rmtree(SEG, ignore_errors=True)
    SEG.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for nome in ("abertura", "encerramento"):
        if not (RAW / f"{nome}.png").exists():
            sys.exit("Faltam as telas de abertura/encerramento. Rode antes: python video/gravar.py")

    partes = [("abertura", cartao("abertura", ABERTURA_S))]
    for c in IDS:
        print(f"montando {c} ...", flush=True)
        partes.append((c, cena(c, audios[c][0])))
    partes.append(("encerramento", cartao("encerramento", ENCERRAMENTO_S)))

    lista = SEG / "lista.txt"
    lista.write_text("".join(f"file '{p.as_posix()}'\n" for _, p in partes), encoding="utf-8")
    final = OUT / ("video_provisorio.mp4" if args.provisorio else "video_explicativo.mp4")
    rodar([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy",
           "-movflags", "+faststart", str(final)])

    print("\nCenas (inicio, duracao):")
    t = 0.0
    for nome, p in partes:
        d = duracao(p)
        titulo = CENAS[nome]["titulo"] if nome in CENAS else nome
        print(f"  {int(t // 60)}:{t % 60:04.1f}  {d:5.1f} s  {nome}: {titulo}")
        t += d
    print(f"\nArquivo: {final}")
    print(f"Duracao: {duracao(final):.1f} s ({duracao(final) / 60:.2f} min)")
    print(f"Tamanho: {final.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
