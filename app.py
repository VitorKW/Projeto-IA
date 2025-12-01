from flask import Flask, request, jsonify
from google import genai
import os
import json
import logging
import time
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 28

API_KEY = os.environ.get("CHAVE_API_GEMINI") or os.environ.get("chaveApiGemini")
DEFAULT_CBS_RATE = Decimal(os.environ.get("DEFAULT_CBS_RATE", "0.12"))  # 12%
DEFAULT_IBS_RATE = Decimal(os.environ.get("DEFAULT_IBS_RATE", "0.14"))  # 14%
DEFAULT_CPP_RATE = Decimal(os.environ.get("DEFAULT_CPP_RATE", "0.20"))  # 20% sobre folha (exemplo)
SIMPLIFIED_SIMPLES_SHARE = Decimal(os.environ.get("SIMPLIFIED_SIMPLES_SHARE", "0.70"))  # % de CBS/IBS considerado "dentro do DAS"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

if not API_KEY:
    logger.error("Variável de ambiente CHAVE_API_GEMINI / chaveApiGemini não definida. endpoint responderá 503.")
    client = None
else:
    try:
        client = genai.Client(api_key=API_KEY)
        logger.info("Cliente Gemini inicializado.")
    except Exception as e:
        logger.exception("Falha ao inicializar cliente Gemini.")
        client = None

# Prompt para o Gemini: regras da Nova Reforma (apenas pós-reforma)
PROMPT_REFORMA = """
Você é um motor de simulação tributária (versão: reforma_v1) que calcula, de forma didática e determinística,
a carga tributária pós-Reforma Tributária (CBS + IBS) para empresas de SERVIÇOS no Brasil.

REQUISITOS GERAIS
- Responda SOMENTE em JSON válido, sem texto adicional, sem backticks, sem comentários.
- Use sempre strings para valores monetários, com duas casas decimais e ponto decimal (ex.: "12345.67").
- Quando um número não se aplicar, use "0.00". Quando faltar texto, use "".
- Use arredondamento HALF_UP para duas casas decimais.

ENTRADA (o modelo receberá a entrada após este prompt em formato JSON)
Exemplo de entrada (apenas referência):
{
  "companyId": 123,
  "year": 2026,
  "useAiForecast": true,
  "historicalMonthly": [ { "ano": 2025, "mes": 12, "receitaBruta": "48000.00", "folhaSalarios": "10000.00", "insumos": "2500.00", "lucroLiquidoContabil": "3000.00" } ],
  "targetYearMonthly": [ { "ano": 2026, "mes": 1, "receitaBruta": "52000.00", "folhaSalarios": "11000.00", "insumos": "2700.00", "lucroLiquidoContabil": "3100.00" } ]
}

REGRAS PARA PROJEÇÃO DOS 12 MESES
1) Se useAiForecast == true:
   - Estime taxa média de crescimento mensal para 'receitaBruta' e 'folhaSalarios' usando 'historicalMonthly'.
   - Projete meses faltantes de targetYearMonthly para completar 12 meses no ano alvo.
   - Se historicalMonthly estiver vazio ou insuficiente, use a média simples dos meses fornecidos em targetYearMonthly.
2) Se useAiForecast == false:
   - Preencha meses faltantes repetindo a média dos meses existentes em targetYearMonthly.
3) Sempre retorne 12 objetos em "baseMensal" (meses 1..12 do ano).

VARIÁVEIS ANUAIS
- faturamentoTotalAnual = soma de receitaBruta dos 12 meses
- folhaTotalAnual = soma de folhaSalarios dos 12 meses
- totalInsumos = soma de insumos dos 12 meses (se faltar, 0.00)
- valorAdicionado = faturamentoTotalAnual - totalInsumos
  - Se totalInsumos == 0, use valorAdicionado = 0.70 * faturamentoTotalAnual (70%)

REGRA DE CPP (contribuição patronal)
- Por padrão: CPP = DEFAULT_CPP_RATE * folhaTotalAnual (DEFAULT_CPP_RATE ser enviado pelo cliente; se ausente use 0.20)
- Em Simples assume-se que CPP está parcialmente incorporada no DAS; para simplificação, ainda incluir CPP no detalhamento.

TRIBUTOS (POST-REFORMA)
- CBS = valorAdicionado * DEFAULT_CBS_RATE
- IBS = valorAdicionado * DEFAULT_IBS_RATE
- IRPJ e CSLL continuam:
  - IRPJ = 0.15 * lucroTributavel
  - CSLL = 0.09 * lucroTributavel
- lucroTributavel:
  - se existirem lucros mensais (lucroLiquidoContabil), some para anual;
  - caso contrário, use lucroTributavel = 0.10 * faturamentoTotalAnual (10%).
- Imposto Seletivo (IS) = 0.00 por padrão (a menos que input declare valores).

REGIMES A CALCULAR (RETORNE OS 3 REGIMES A SEGUIR, TODOS PÓS-REFORMA)
1) "Simples Nacional - Pós-Reforma"
   - Para fins didáticos calcule CBS_simples = CBS * SIMPLIFIED_SIMPLES_SHARE
     e IBS_simples = IBS * SIMPLIFIED_SIMPLES_SHARE
   - Ainda retorne CBS_total e IBS_total (os valores integrais calculados a partir do valorAdicionado)
   - impostoTotalAnual = (CBS_simples + IBS_simples + IRPJ + CSLL + CPP_simples)
     - onde CPP_simples = CPP * SIMPLIFIED_SIMPLES_SHARE (assumir parte paga via DAS)
   - Observação: SIMPLIFIED_SIMPLES_SHARE (ex.: 0.70) será fornecida pelo cliente; se ausente use 0.70.
2) "Lucro Presumido - Pós-Reforma"
   - Calcule CBS e IBS integrais (não aplicar share)
   - Base presumida (serviços) = 0.32 * faturamentoTotalAnual
   - IRPJ = 0.15 * basePresumida
   - CSLL = 0.09 * basePresumida
   - CPP = DEFAULT_CPP_RATE * folhaTotalAnual
   - impostoTotalAnual = CBS + IBS + IRPJ + CSLL + CPP
3) "Lucro Real - Pós-Reforma"
   - Use lucroTributavel (soma mensal ou 10% fallback)
   - IRPJ = 0.15 * lucroTributavel
   - CSLL = 0.09 * lucroTributavel
   - CBS e IBS integrais (assumir sistema com créditos; mas, para didática, use CBS = valorAdicionado * DEFAULT_CBS_RATE, IBS = valorAdicionado * DEFAULT_IBS_RATE)
   - CPP = DEFAULT_CPP_RATE * folhaTotalAnual
   - impostoTotalAnual = CBS + IBS + IRPJ + CSLL + CPP

DISTRIBUIÇÃO MENSAL
- "impostoTotalMensal": distribua proporcionalmente ao faturamento de cada mês.
- Ao final ajuste o último mês para garantir soma(impostoTotalMensal) == impostoTotalAnual (evitar diferenças por arredondamento).

FORMATO OBRIGATÓRIO DE SAÍDA (EXATAMENTE ESTE JSON)
- Retorne um JSON com chaves:
  - companyId, year, metodo, faturamentoTotalAnual, folhaTotalAnual, valorAdicionado,
  - baseMensal (12 objetos),
  - regimes (lista com 3 regimes na ordem: Simples, Presumido, Real), cada regime com:
    - nome, impostoTotalAnual, aliquotaEfetiva, detalhesTributos (CBS, IBS, IRPJ, CSLL, CPP, IS),
    - impostoTotalMensal (lista de 12 objetos {mes, valor}), observacoes
  - recomendado (nome exato do regime com menor impostoTotalAnual)

REGRAS FINAIS
- Todas as chaves e valores devem usar aspas duplas.
- Todos os valores monetários em string com duas casas decimais.
- Não inclua nada fora do JSON.
- Use as alíquotas DEFAULT_CBS_RATE e DEFAULT_IBS_RATE passadas pelo cliente se fornecidas; caso contrário usar 0.12 e 0.14.
"""

def _decimal_from_str_or_num(x):
    if x is None:
        return Decimal("0.00")
    if isinstance(x, Decimal):
        return x
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal("0.00")

def _fmt_money(d: Decimal) -> str:
    # two decimals, HALF_UP
    q = d.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    return f"{q:.2f}"

def _extract_text_from_response(resp):
    try:
        if isinstance(resp, str):
            return resp.strip()
        if hasattr(resp, "text") and isinstance(getattr(resp, "text"), str):
            return getattr(resp, "text").strip()
        # fallback to JSON encoding
        try:
            return json.dumps(resp, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False)
        except Exception:
            return repr(resp)
    except Exception as e:
        logger.exception("Erro extraindo texto da resposta do modelo.")
        return None

def _validate_input_schema(data):
    if not isinstance(data, dict):
        return False, "JSON de entrada deve ser um objeto."
    if "companyId" not in data or "year" not in data:
        return False, "Campos obrigatórios ausentes: 'companyId' e 'year'."
    return True, ""

def _complete_12_months(target, historical, use_ai):
    # target: list of dicts (may be less than 12); historical: list of dicts
    # We'll produce 12 months for the given year in target (assume months 1..12)
    # Simple approach: if use_ai and historical present -> compute monthly growth rate avg and project
    # For simplicity here: if data for month exists, use it; else fill with average of provided target months.
    # This helper returns a list of 12 dicts with keys: ano, mes, receitaBruta, folhaSalarios, insumos, lucroLiquidoContabil (optional)
    year = target[0]["ano"] if target else (historical[0]["ano"] if historical else None)
    # prepare dict by month
    by_month = {}
    for m in (target or []):
        by_month[int(m["mes"])] = m
    # if not target months, try to derive from historical mapping on same months
    months_data = []
    # compute averages from target if any
    def avg_from_list(lst, key):
        vals = []
        for it in lst:
            try:
                vals.append(Decimal(str(it.get(key, "0") or "0")))
            except Exception:
                pass
        return (sum(vals) / len(vals)) if vals else Decimal("0.00")
    if len(by_month) == 12:
        # already complete
        for m in range(1,13):
            entry = by_month[m]
            months_data.append({
                "ano": entry.get("ano", year),
                "mes": m,
                "receitaBruta": _fmt_money( _decimal_from_str_or_num(entry.get("receitaBruta")) ),
                "folhaSalarios": _fmt_money( _decimal_from_str_or_num(entry.get("folhaSalarios")) ),
                "insumos": _fmt_money( _decimal_from_str_or_num(entry.get("insumos")) ),
                "lucroLiquidoContabil": _fmt_money( _decimal_from_str_or_num(entry.get("lucroLiquidoContabil")) ) if entry.get("lucroLiquidoContabil") is not None else None
            })
        return months_data
    # compute averages from target if exist, else from historical
    source_for_avg = target if target and len(target) > 0 else historical
    avg_receita = avg_from_list(source_for_avg, "receitaBruta")
    avg_folha = avg_from_list(source_for_avg, "folhaSalarios")
    avg_insumos = avg_from_list(source_for_avg, "insumos")
    avg_lucro = avg_from_list(source_for_avg, "lucroLiquidoContabil")
    for m in range(1,13):
        if m in by_month:
            e = by_month[m]
            months_data.append({
                "ano": e.get("ano", year),
                "mes": m,
                "receitaBruta": _fmt_money(_decimal_from_str_or_num(e.get("receitaBruta"))),
                "folhaSalarios": _fmt_money(_decimal_from_str_or_num(e.get("folhaSalarios"))),
                "insumos": _fmt_money(_decimal_from_str_or_num(e.get("insumos"))),
                "lucroLiquidoContabil": _fmt_money(_decimal_from_str_or_num(e.get("lucroLiquidoContabil"))) if e.get("lucroLiquidoContabil") is not None else None
            })
        else:
            months_data.append({
                "ano": year,
                "mes": m,
                "receitaBruta": _fmt_money(avg_receita),
                "folhaSalarios": _fmt_money(avg_folha),
                "insumos": _fmt_money(avg_insumos),
                "lucroLiquidoContabil": _fmt_money(avg_lucro) if avg_lucro != Decimal("0.00") else None
            })
    return months_data

def _distribute_monthly(imposto_total, faturamentos):
    # imposto_total: Decimal, faturamentos: list of Decimal for 12 months
    total_fat = sum(faturamentos) if faturamentos else Decimal("0.00")
    monthly = []
    accumulated = Decimal("0.00")
    for i, f in enumerate(faturamentos, start=1):
        if total_fat == 0:
            val = (imposto_total / Decimal(len(faturamentos))).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        else:
            val = (imposto_total * (f / total_fat)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        monthly.append((i, val))
        accumulated += val
    # adjust last month
    diff = imposto_total - accumulated
    if monthly:
        last_index, last_val = monthly[-1]
        monthly[-1] = (last_index, (last_val + diff).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
    return monthly

# Endpoint
@app.route("/chat", methods=["POST"])
def chat():
    if client is None:
        return jsonify({"error": "Serviço de IA indisponível: cliente não configurado (variável de ambiente faltando)."}), 503
    try:
        dados = request.get_json(silent=True)
        if not dados:
            return jsonify({"error": "Envie um JSON válido no corpo da requisição."}), 400

        ok, msg = _validate_input_schema(dados)
        if not ok:
            return jsonify({"error": msg}), 400

        # parametros configuráveis via entrada
        cbs_rate = _decimal_from_str_or_num(dados.get("cbsRate", DEFAULT_CBS_RATE))
        ibs_rate = _decimal_from_str_or_num(dados.get("ibsRate", DEFAULT_IBS_RATE))
        cpp_rate = _decimal_from_str_or_num(dados.get("cppRate", DEFAULT_CPP_RATE))
        simples_share = _decimal_from_str_or_num(dados.get("simplesShare", SIMPLIFIED_SIMPLES_SHARE))

        target = dados.get("targetYearMonthly", [])
        historical = dados.get("historicalMonthly", [])
        use_ai = bool(dados.get("useAiForecast", False))

        # completar 12 meses
        base_mensal = _complete_12_months(target, historical, use_ai)

        # calcular anuais
        faturamentoTotalAnual = sum(Decimal(b["receitaBruta"]) for b in base_mensal)
        folhaTotalAnual = sum(Decimal(b["folhaSalarios"]) for b in base_mensal)
        totalInsumos = sum(Decimal(b.get("insumos") or "0.00") for b in base_mensal)

        if totalInsumos == Decimal("0.00"):
            valorAdicionado = (faturamentoTotalAnual * Decimal("0.70")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        else:
            valorAdicionado = (faturamentoTotalAnual - totalInsumos).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

        # lucroTributavel
        soma_lucro_mensal = Decimal("0.00")
        lucro_flag = False
        for b in base_mensal:
            if b.get("lucroLiquidoContabil") is not None:
                lucro_flag = True
                soma_lucro_mensal += Decimal(b["lucroLiquidoContabil"])
        if lucro_flag:
            lucroTributavel = soma_lucro_mensal
        else:
            lucroTributavel = (faturamentoTotalAnual * Decimal("0.10")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

        # tributos gerais
        CBS_total = (valorAdicionado * cbs_rate).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        IBS_total = (valorAdicionado * ibs_rate).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        CPP_total = (folhaTotalAnual * cpp_rate).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

        # IRPJ / CSLL - regras por regime definidas abaixo (Presumido usa base presumida)
        # Simples: We'll include IRPJ/CSLL computed on lucroTributavel (same rule)
        IRPJ_base_simples = (lucroTributavel * Decimal("1.00")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        IRPJ_simples = (IRPJ_base_simples * Decimal("0.15")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        CSLL_simples = (IRPJ_base_simples * Decimal("0.09")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

        # Lucro Presumido
        basePresumida = (faturamentoTotalAnual * Decimal("0.32")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        IRPJ_presumido = (basePresumida * Decimal("0.15")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        CSLL_presumido = (basePresumida * Decimal("0.09")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

        # Lucro Real
        IRPJ_real = (lucroTributavel * Decimal("0.15")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        CSLL_real = (lucroTributavel * Decimal("0.09")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

        # Simples específico: aplicar share
        CBS_simples = (CBS_total * simples_share).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        IBS_simples = (IBS_total * simples_share).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        CPP_simples = (CPP_total * simples_share).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        imposto_simples_total = (CBS_simples + IBS_simples + IRPJ_simples + CSLL_simples + CPP_simples).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

        # Presumido total
        imposto_presumido_total = (CBS_total + IBS_total + IRPJ_presumido + CSLL_presumido + CPP_total).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

        # Real total
        imposto_real_total = (CBS_total + IBS_total + IRPJ_real + CSLL_real + CPP_total).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

        # Distribuição mensal (proporcional ao faturamento)
        faturamentos_mensais = [Decimal(m["receitaBruta"]) for m in base_mensal]
        simples_monthly = _distribute_monthly(imposto_simples_total, faturamentos_mensais)
        presumido_monthly = _distribute_monthly(imposto_presumido_total, faturamentos_mensais)
        real_monthly = _distribute_monthly(imposto_real_total, faturamentos_mensais)

        def monthly_to_list(monthly_tuples):
            return [ {"mes": int(m), "valor": _fmt_money(v)} for (m,v) in monthly_tuples ]

        regimes = [
            {
                "nome": "Simples Nacional - Pós-Reforma",
                "impostoTotalAnual": _fmt_money(imposto_simples_total),
                "aliquotaEfetiva": _fmt_money((imposto_simples_total / faturamentoTotalAnual) if faturamentoTotalAnual>0 else Decimal("0.00")),
                "detalhesTributos": {
                    "CBS": _fmt_money(CBS_simples),
                    "IBS": _fmt_money(IBS_simples),
                    "IRPJ": _fmt_money(IRPJ_simples),
                    "CSLL": _fmt_money(CSLL_simples),
                    "CPP": _fmt_money(CPP_simples),
                    "IS": "0.00"
                },
                "impostoTotalMensal": monthly_to_list(simples_monthly),
                "observacoes": f"Simples simplificado: {int((simples_share*100))}% do CBS/IBS e CPP considerados dentro do DAS (hipótese didática)."
            },
            {
                "nome": "Lucro Presumido - Pós-Reforma",
                "impostoTotalAnual": _fmt_money(imposto_presumido_total),
                "aliquotaEfetiva": _fmt_money((imposto_presumido_total / faturamentoTotalAnual) if faturamentoTotalAnual>0 else Decimal("0.00")),
                "detalhesTributos": {
                    "CBS": _fmt_money(CBS_total),
                    "IBS": _fmt_money(IBS_total),
                    "IRPJ": _fmt_money(IRPJ_presumido),
                    "CSLL": _fmt_money(CSLL_presumido),
                    "CPP": _fmt_money(CPP_total),
                    "IS": "0.00"
                },
                "impostoTotalMensal": monthly_to_list(presumido_monthly),
                "observacoes": "Regime presumido com CBS/IBS integrais e base presumida de 32% para serviços."
            },
            {
                "nome": "Lucro Real - Pós-Reforma",
                "impostoTotalAnual": _fmt_money(imposto_real_total),
                "aliquotaEfetiva": _fmt_money((imposto_real_total / faturamentoTotalAnual) if faturamentoTotalAnual>0 else Decimal("0.00")),
                "detalhesTributos": {
                    "CBS": _fmt_money(CBS_total),
                    "IBS": _fmt_money(IBS_total),
                    "IRPJ": _fmt_money(IRPJ_real),
                    "CSLL": _fmt_money(CSLL_real),
                    "CPP": _fmt_money(CPP_total),
                    "IS": "0.00"
                },
                "impostoTotalMensal": monthly_to_list(real_monthly),
                "observacoes": "Regime real com CBS/IBS integrais. Lucro tributável = soma dos lucros contábeis mensais ou 10% do faturamento se não informado."
            }
        ]

        # recomendado: menor impostoTotalAnual
        menor = min(regimes, key=lambda r: Decimal(r["impostoTotalAnual"]))
        recomendado = menor["nome"]

        # montar resposta
        resposta = {
            "companyId": dados.get("companyId"),
            "year": dados.get("year"),
            "metodo": "ia:v3:simulacao_reforma",
            "faturamentoTotalAnual": _fmt_money(faturamentoTotalAnual),
            "folhaTotalAnual": _fmt_money(folhaTotalAnual),
            "valorAdicionado": _fmt_money(valorAdicionado),
            "baseMensal": base_mensal,
            "regimes": regimes,
            "recomendado": recomendado
        }

        # retornar JSON já calculado pelo backend (não necessariamente chamar o modelo aqui)
        return jsonify(resposta), 200

    except Exception as e:
        logger.exception("Erro interno na função chat.")
        return jsonify({"error": f"Erro interno do servidor: {str(e)}"}), 500

if __name__ == "__main__":
    # Em produção, remova debug=True
    app.run(host="0.0.0.0", port=8000, debug=True)
