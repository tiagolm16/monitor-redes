"""Funcoes de apoio usadas pelos coletores."""
import re
import time
from collections import deque


class Taxas:
    """Converte contadores crescentes (ex.: total de requisicoes) em taxa por segundo.

    Os servicos expoem CONTADORES ("ja recebi 10234 requisicoes"). Para saber o RPS
    guardamos a leitura anterior e calculamos (agora - antes) / segundos.
    """

    def __init__(self) -> None:
        self._anterior: dict[str, tuple[float, float]] = {}

    def delta(self, chave: str, valor: float) -> tuple[float, float] | None:
        """Retorna (variacao, segundos) desde a leitura anterior, ou None na primeira vez."""
        agora = time.monotonic()
        ant = self._anterior.get(chave)
        self._anterior[chave] = (agora, valor)
        if ant is None:
            return None
        variacao = valor - ant[1]
        if variacao < 0:  # contador zerou (servico reiniciou)
            variacao = 0
        return variacao, max(agora - ant[0], 0.001)

    def por_segundo(self, chave: str, valor: float) -> float | None:
        d = self.delta(chave, valor)
        return None if d is None else d[0] / d[1]


_LINHA_PROM = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{(.*)\})?\s+([^\s]+)")
_LABEL = re.compile(r'(\w+)="((?:[^"\\]|\\.)*)"')


def parse_prometheus(texto: str) -> list[tuple[str, dict, float]]:
    """Le o formato texto do Prometheus: nome{label="x"} valor -> (nome, {label: x}, valor)."""
    saida = []
    for linha in texto.splitlines():
        if not linha or linha.startswith("#"):
            continue
        m = _LINHA_PROM.match(linha)
        if not m:
            continue
        try:
            valor = float(m.group(4))
        except ValueError:
            continue
        labels = dict(_LABEL.findall(m.group(3) or ""))
        saida.append((m.group(1), labels, valor))
    return saida


class Janela:
    """Soma valores dos ultimos N segundos (janela deslizante).

    Taxas de erro calculadas so com o ultimo ciclo de 5 s oscilam muito (1 erro em 25
    requisicoes = 4%). Somando uma janela maior (ex.: 30 s) a taxa fica estavel.
    """

    def __init__(self, segundos: float) -> None:
        self.segundos = segundos
        self.itens: deque[tuple[float, dict]] = deque()

    def add(self, **valores: float) -> None:
        agora = time.monotonic()
        self.itens.append((agora, valores))
        while self.itens and agora - self.itens[0][0] > self.segundos:
            self.itens.popleft()

    def soma(self, chave: str) -> float:
        return sum(v.get(chave, 0) for _, v in self.itens)
