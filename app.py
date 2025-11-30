from flask import Flask, request, jsonify
from google import genai
import os
import json
import logging

# Configuração de logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# ----------------------------------------------------------------------
# Configuração do cliente Gemini
# ----------------------------------------------------------------------
# A chave da API deve ser definida na variável de ambiente.
# A instrução de erro abaixo é mantida para garantir a configuração do ambiente.
API_KEY = os.environ.get("chaveApiGemini")
if not API_KEY:
    # Em um ambiente de produção, este erro seria mais gracioso.
    # Para o propósito de desenvolvimento, manter a validação.
    raise RuntimeError("Defina a variável de ambiente chaveApiGemini com sua chave do Gemini.")

try:
    # Inicializa o cliente Gemini
    client = genai.Client(api_key=API_KEY)
    logging.info("Cliente Gemini inicializado com sucesso.")
except Exception as e:
    logging.error(f"Falha ao inicializar o cliente Gemini: {e}")
    # Permite que o servidor inicie, mas as requisições falharão.

# ----------------------------------------------------------------------
# PROMPT DA IA – AQUI FICA TODA A 'INTELIGÊNCIA' DA SIMULAÇÃO
# Este prompt foi fornecido pelo usuário e contém toda a lógica de negócios
# da simulação tributária, garantindo que o modelo retorne JSON puro.
# ----------------------------------------------------------------------
PROMPT_PADRAO = """
Você é um motor de simulação tributária para empresas de serviços no Brasil.
Sua função é calcular, de forma SIMPLIFICADA e DIDÁTICA, o impacto da tributação
em diferentes regimes e em dois cenários: SISTEMA ATUAL e REFORMA TRIBUTÁRIA.

---------------------------------------
DADOS DE ENTRADA (JSON)
---------------------------------------
Você receberá um JSON com estrutura semelhante a:

{
  "companyId": 123,
  "year": 2026,
  "useAiForecast": true,
  "historicalMonthly": [
    {
      "ano": 2024,
      "mes": 12,
      "receitaBruta": "48000.00",
      "folhaSalarios": "10000.00",
      "lucroLiquidoContabil": "3000.00",
      "insumosCreditoPisCofins": "2500.00",
      "retencaoIRPJ": "0.00",
      "retencaoCSLL": "0.00"
    }
  ],
  "targetYearMonthly": [
    {
      "ano": 2026,
      "mes": 1,
      "receitaBruta": "52000.00",
      "folhaSalarios": "11000.00",
      "lucroLiquidoContabil": "3100.00",
      "insumosCreditoPisCofins": "2700.00",
      "retencaoIRPJ": "0.00",
      "retencaoCSLL": "0.00"
    }
  ]
}

---------------------------------------
REGRA 1 – COMPLETAR OS 12 MESES DO ANO ALVO
---------------------------------------
- Se "useAiForecast" == true:
  - Use os dados de "historicalMonthly" para estimar uma taxa média de crescimento da
    "receitaBruta" e da "folhaSalarios".
  - Projete os meses faltantes de "targetYearMonthly" até completar 12 meses no ano alvo.
  - Se houver poucos dados, use a média simples dos valores disponíveis.
- Se "useAiForecast" == false:
  - Use apenas os meses informados em "targetYearMonthly"; se faltarem meses, assuma que
    os meses faltantes repetem a média dos meses existentes.

---------------------------------------
REGRA 2 – BASES ANUAIS E FATOR R
---------------------------------------
- Calcule "faturamentoTotalAnual" = soma da "receitaBruta" dos 12 meses projetados.
- Calcule "folhaTotalAnual" = soma da "folhaSalarios" dos 12 meses projetados.
- Calcule o Fator R: fatorR = folhaTotalAnual / faturamentoTotalAnual.
- Preencha "baseMensal" na saída com os 12 meses utilizados na simulação.

---------------------------------------
REGRA 3 – CENÁRIO 1: SISTEMA ATUAL (SEM REFORMA)
---------------------------------------

3.1) Simples Nacional - Anexo III (Sistema Atual)
- Somente se fatorR >= 0.28.
- Use alíquotas efetivas simplificadas:
  - faturamentoTotalAnual <= 180000.00  -> aliquotaEfetiva = 0.06
  - <= 360000.00                        -> 0.11
  - <= 720000.00                        -> 0.135
  - > 720000.00                         -> 0.16
- impostoTotalAnual = faturamentoTotalAnual * aliquotaEfetiva.
- "impostoTotalMensal": distribua proporcionalmente ao faturamento de cada mês.

3.2) Simples Nacional - Anexo V (Sistema Atual)
- Somente se fatorR < 0.28.
- Alíquotas efetivas simplificadas:
  - faturamentoTotalAnual <= 180000.00  -> 0.15
  - <= 360000.00                        -> 0.18
  - <= 720000.00                        -> 0.20
  - > 720000.00                         -> 0.22
- impostoTotalAnual = faturamentoTotalAnual * aliquotaEfetiva.

3.3) Lucro Presumido - Sistema Atual
- Base presumida (serviços) = 0.32 * faturamentoTotalAnual.
- IRPJ = 0.15 * basePresumida.
- CSLL = 0.09 * basePresumida.
- PIS = 0.0065 * faturamentoTotalAnual.
- COFINS = 0.03 * faturamentoTotalAnual.
- ISS aproximado = 0.04 * faturamentoTotalAnual.
- impostoTotalAnual = IRPJ + CSLL + PIS + COFINS + ISS.

3.4) Lucro Real - Sistema Atual
- Se houver "lucroLiquidoContabil" mensal, some para obter lucro anual.
- Caso contrário, assuma lucroTributavel = 0.10 * faturamentoTotalAnual (10% de margem).
- IRPJ = 0.15 * lucroTributavel.
- CSLL = 0.09 * lucroTributavel.
- PIS (não cumulativo) = 0.0165 * faturamentoTotalAnual.
- COFINS (não cumulativo) = 0.076 * faturamentoTotalAnual.
- Se houver "insumosCreditoPisCofins", você pode reduzir a base de PIS/COFINS de forma coerente.
- impostoTotalAnual = IRPJ + CSLL + PIS + COFINS.

---------------------------------------
REGRA 4 – CENÁRIO 2: REFORMA TRIBUTÁRIA (CBS / IBS) – MODELO DIDÁTICO
---------------------------------------
- Considere um sistema de tributos sobre valor adicionado:
  - CBS substitui PIS/COFINS federais.
  - IBS substitui ISS e ICMS (quando aplicável).
- Estime um valor adicionado aproximado:
  - valorAdicionado = faturamentoTotalAnual - totalInsumosCredito (soma de "insumosCreditoPisCofins" dos 12 meses, se existir).
  - Se não houver insumos, assuma valorAdicionado = 0.7 * faturamentoTotalAnual (70%).
- Use alíquotas didáticas:
  - CBS = valorAdicionado * 0.12
  - IBS = valorAdicionado * 0.14
- Para IRPJ e CSLL na reforma, use o MESMO lucroTributavel da regra de Lucro Real.
- Crie pelo menos um regime:
  - "nome": "Regime Geral Serviços - Reforma (CBS/IBS)"
  - impostoTotalAnual = CBS + IBS + IRPJ + CSLL.
- "impostoTotalMensal": distribua CBS e IBS proporcionalmente ao faturamento mensal.

---------------------------------------
REGRA 5 – LISTA DE REGIMES A COMPARAR
---------------------------------------
Monte o array "regimes" com alguns ou todos os abaixo, conforme aplicável:

- "Simples Nacional - Anexo III (Sistema Atual)"      [se fatorR >= 0.28]
- "Simples Nacional - Anexo V (Sistema Atual)"        [se fatorR < 0.28]
- "Lucro Presumido - Sistema Atual"
- "Lucro Real - Sistema Atual"
- "Regime Geral Serviços - Reforma (CBS/IBS)"

Para cada regime, preencha:
- "nome"
- "impostoTotalAnual"
- "impostoTotalMensal" (lista de objetos { "mes": numeroMes, "valor": "xxxxx.xx" })
- "aliquotaEfetiva" (impostoTotalAnual / faturamentoTotalAnual)
- "detalhesTributos": objeto com chaves:
  - "IRPJ", "CSLL", "PIS", "COFINS", "ISS", "CPP", "CBS", "IBS"
  - Use "0.00" para tributos que não se aplicarem.
- "observacoes": texto curto explicando o regime ou cenário.

---------------------------------------
REGRA 6 – ESCOLHA DO REGIME RECOMENDADO
---------------------------------------
- Compare todos os regimes válidos.
- "recomendado" DEVE ser exatamente o valor de "nome" do regime com MENOR "impostoTotalAnual".
- Não invente regimes adicionais além dos descritos.

---------------------------------------
FORMATO OBRIGATÓRIO DA RESPOSTA (JSON PURO)
---------------------------------------
Você deve responder SOMENTE JSON válido, sem markdown, sem ```json, sem comentários.

Use SEMPRE o modelo abaixo como referência de estrutura:

{
  "companyId": 123,
  "year": 2026,
  "metodo": "ia:v2:simulacao_reforma_completa",
  "faturamentoTotalAnual": "720000.00",
  "baseMensal": [
    {
      "ano": 2026,
      "mes": 1,
      "receitaBruta": "52000.00",
      "folhaSalarios": "11000.00"
    }
  ],
  "regimes": [
    {
      "nome": "Simples Nacional - Anexo III (Sistema Atual)",
      "impostoTotalAnual": "84567.22",
      "impostoTotalMensal": [
        { "mes": 1, "valor": "7000.00" }
      ],
      "aliquotaEfetiva": "0.1176",
      "detalhesTributos": {
        "IRPJ": "0.00",
        "CSLL": "0.00",
        "PIS": "3500.00",
        "COFINS": "16100.00",
        "ISS": "22000.00",
        "CPP": "21967.22",
        "CBS": "0.00",
        "IBS": "0.00"
      },
      "observacoes": "Fator R > 28%; regime do sistema atual."
    },
    {
      "nome": "Regime Geral Serviços - Reforma (CBS/IBS)",
      "impostoTotalAnual": "80123.50",
      "impostoTotalMensal": [
        { "mes": 1, "valor": "6676.96" }
      ],
      "aliquotaEfetiva": "0.1113",
      "detalhesTributos": {
        "IRPJ": "15000.00",
        "CSLL": "9000.00",
        "PIS": "0.00",
        "COFINS": "0.00",
        "ISS": "0.00",
        "CPP": "0.00",
        "CBS": "35000.00",
        "IBS": "21123.50"
      },
      "observacoes": "Regime simplificado da reforma tributária com CBS/IBS."
    }
  ],
  "recomendado": "Regime Geral Serviços - Reforma (CBS/IBS)"
}

REGRAS FINAIS:
- Use SEMPRE aspas duplas em chaves e valores.
- Números devem ser strings com duas casas decimais e ponto, por exemplo: "12345.67".
- Se faltar informação, use "0.00" para números ou "" para textos.
- NÃO escreva nada fora do JSON.
"""

# ----------------------------------------------------------------------
# ENDPOINT DA IA
# ----------------------------------------------------------------------
@app.route("/chat", methods=["POST"])
def chat():
    """
    Recebe os dados financeiros e solicita ao Gemini a simulação tributária
    completa (cenários atual e reforma), retornando o resultado em JSON.
    """
    try:
        dados = request.get_json()
        
        if not dados:
            return jsonify({"error": "Envie um JSON válido no corpo da requisição."}), 400

        # Validação básica de campos essenciais para o prompt
        if 'companyId' not in dados or 'year' not in dados:
            return jsonify({"error": "Os campos 'companyId' e 'year' são obrigatórios no JSON de entrada."}), 400

        # Converte a entrada para string JSON para enviar ao modelo
        entrada_json = json.dumps(dados, ensure_ascii=False, indent=2)
        
        logging.info(f"Dados de entrada recebidos para companyId: {dados.get('companyId')}")

        # Monta o conteúdo final para o modelo
        full_content = f"{PROMPT_PADRAO}\n\nENTRADA JSON:\n{entrada_json}"

        # Chamada ao Gemini pedindo JSON puro
        # O modelo gemini-2.5-pro é ideal para tarefas que exigem seguir regras complexas com precisão.
        resposta = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=full_content,
            config={"response_mime_type": "application/json"}
        )
        
        logging.info("Resposta da IA recebida. Tentando parsear JSON.")

        texto = (resposta.text or "").strip()
        if not texto:
            return jsonify({"error": "Resposta vazia da IA."}), 502

        # Tenta converter o retorno em JSON
        try:
            saida = json.loads(texto)
        except json.JSONDecodeError:
            logging.error(f"Erro ao parsear JSON. Output bruto: {texto[:500]}...")
            return jsonify({
                "error": "Modelo não retornou JSON válido conforme o formato exigido.",
                "raw_output": texto
            }), 502

        # Sucesso – devolve o JSON já no formato que o backend espera
        logging.info("Simulação concluída e JSON retornado com sucesso.")
        return jsonify(saida), 200

    except Exception as e:
        logging.exception("Erro interno na função chat.")
        return jsonify({"error": f"Erro interno do servidor: {str(e)}"}), 500


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Inicia o servidor Flask
    # Ajuste host/port conforme teu ambiente (0.0.0.0 e 8000 são padrões comuns)
    app.run(host="0.0.0.0", port=8000, debug=True)
