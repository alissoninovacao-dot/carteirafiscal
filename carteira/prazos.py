"""Cálculo de vencimentos de obrigações acessórias (dia fixo, N-ésimo dia útil, último dia útil, anuais).

Dia útil = segunda a sexta, exceto feriados nacionais e os pontos facultativos de Carnaval e Corpus Christi
(a Receita desloca os vencimentos para o dia útil seguinte nesses casos). Feriados estaduais/municipais não entram.
"""
import calendar
from datetime import date, timedelta
from functools import lru_cache

# regra -> descrição (usada nas telas)
REGRAS = {
    "dia_seguinte": "Dia N do mês seguinte",
    "dia_util_2m": "N-º dia útil do 2º mês seguinte",
    "ultimo_util_seguinte": "Último dia útil do mês seguinte",
    "dia_2m": "Dia N do 2º mês seguinte",
    "anual_dia": "Dia N do mês M do ano seguinte",
    "anual_ultimo_util": "Último dia útil do mês M do ano seguinte",
    "sem_data": "Sem data fixa (informar manualmente)",
}
REGRAS_ANUAIS = {"anual_dia", "anual_ultimo_util"}


def _pascoa(ano):
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


@lru_cache(maxsize=None)
def nao_uteis(ano):
    p = _pascoa(ano)
    fixos = [(1, 1), (21, 4), (1, 5), (7, 9), (12, 10), (2, 11), (15, 11), (20, 11), (25, 12)]
    return frozenset([date(ano, m, d) for d, m in fixos] +
                     [p - timedelta(days=48), p - timedelta(days=47), p - timedelta(days=2), p + timedelta(days=60)])


def eh_util(d):
    return d.weekday() < 5 and d not in nao_uteis(d.year)


def proximo_util(d):
    while not eh_util(d):
        d += timedelta(days=1)
    return d


def somar_meses(ano, mes, k):
    t = ano * 12 + (mes - 1) + k
    return t // 12, t % 12 + 1


def n_util(ano, mes, n):
    d, achados = date(ano, mes, 1), 0
    while True:
        if eh_util(d):
            achados += 1
            if achados == n:
                return d
        d += timedelta(days=1)


def ultimo_util(ano, mes):
    d = date(ano, mes, calendar.monthrange(ano, mes)[1])
    while not eh_util(d):
        d -= timedelta(days=1)
    return d


def _dia(ano, mes, dia):
    return date(ano, mes, min(int(dia), calendar.monthrange(ano, mes)[1]))


def calcular(regra, dia, mes_anual, periodo):
    """periodo: 'AAAA-MM' (mensal) ou 'AAAA' (ano-calendário). Retorna a data de vencimento ou None."""
    if regra not in REGRAS or regra == "sem_data":
        return None
    if regra in REGRAS_ANUAIS:
        if len(periodo) != 4 or not mes_anual:
            return None
        ano = int(periodo) + 1
        return proximo_util(_dia(ano, mes_anual, dia or 28)) if regra == "anual_dia" else ultimo_util(ano, mes_anual)
    if len(periodo) != 7:
        return None
    ano, mes = map(int, periodo.split("-"))
    if regra == "dia_seguinte" and dia:
        a, m = somar_meses(ano, mes, 1)
        return proximo_util(_dia(a, m, dia))
    if regra == "dia_2m" and dia:
        a, m = somar_meses(ano, mes, 2)
        return proximo_util(_dia(a, m, dia))
    if regra == "dia_util_2m" and dia:
        a, m = somar_meses(ano, mes, 2)
        return n_util(a, m, int(dia))
    if regra == "ultimo_util_seguinte":
        a, m = somar_meses(ano, mes, 1)
        return ultimo_util(a, m)
    return None
