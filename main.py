# === BOT TEOREMA DA DUPLICATA + ROBUSTEZ TOTAL ===
import time
import os
import ccxt

# CONFIG BASE - INTACTO
MARGEM_INICIAL = 2
SEQUENCIA = [MARGEM_INICIAL * (2**i) for i in range(10)] # 2,4,8,16...1024
ALAVANCAGEM = 50
SL_SALDO = 0.10
TP_SALDO = 2.00

# ROBUSTEZ -
ROBUSTEZ = {
    "MAX_SPREAD_PCT": 0.8,
    "VOLUME_MIN_X_MEDIA": 1.2,
    "COOLDOWN_PERDA": 30,
    "COOLDOWN_WIN": 10,
    "MAX_REENTRADA_MESMA_MOEDA": 120,
    "RSI_HISTERESIS": 5,
    "FUNDING_MAX": 0.05,
    "EQUITY_STUCK_TIMEOUT": 600
}

ESTADO = {
    "indice": 0,
    "wins_consec": 0,
    "loss_consec": 0,
    "loss_dia": 0,
    "ultimo_trade_por_moeda": {},
    "equity_inicial_trade": 0
}

BLACKLIST = ["USDC","DAI","TUSD","FDUSD","BULL","BEAR","UP","DOWN"]

# CONEXÃO COM A EXCHANGE (BINGX) via CCXT usando Variáveis de Ambiente
exchange = ccxt.bingx({
    'apiKey': os.environ.get('BINGX_API_KEY'),
    'secret': os.environ.get('BINGX_SECRET_KEY'),
    'options': {
        'defaultType': 'swap', # Define para o mercado de Perpétuos/Futures
    }
})

def get_equity():
    try:
        balance = exchange.fetch_balance()
        # Retorna o saldo total em USDT ou Equity total da conta de futuros
        return float(balance['total']['USDT'])
    except Exception as e:
        print(f"Erro ao buscar saldo: {e}")
        return 0.0

def get_dados_mercado(simbolo):
    # NOTA: Implemente aqui o cálculo dos seus indicadores (EMA, RSI, Volume Médio)
    # usando as funções exchange.fetch_ohlcv() e exchange.fetch_ticker()
    dados_ficticios = {
        'ask': 1.0, 'bid': 1.0, 'volume': 1000, 'volume_media20': 800,
        'funding_rate': 0.01, 'ema9': 10, 'ema21': 9, 'rsi': 50,
        'cruzou_agora': True, 'variacao_5m': -3
    }
    return dados_ficticios

def abrir_isolada(simbolo, sinal, margem, alavancagem):
    try:
        # Configura a alavancagem na BingX antes de abrir a ordem
        exchange.set_leverage(alavancagem, simbolo)
        
        # Altera para modo de margem ISOLADA se necessário
        # exchange.set_margin_mode('isolated', simbolo)
        
        side = 'buy' if sinal == "LONG" else 'sell'
        print(f"Executando {sinal} em {simbolo} com margem de {margem} USDT")
        
        # Exemplo de ordem a mercado (Market Order)
        # ordem = exchange.create_market_order(simbolo, side, margem)
        # return ordem
        return {"status": "success"}
    except Exception as e:
        print(f"Erro ao abrir ordem: {e}")
        return None

def monitorar_equity_ate_tp_sl(tp_alvo, sl_alvo, timeout):
    tempo_inicial = time.time()
    while time.time() - tempo_inicial < timeout:
        saldo_atual = get_equity()
        if saldo_atual >= tp_alvo:
            return "WIN"
        if saldo_atual <= sl_alvo:
            return "LOSS"
        time.sleep(5)
    return "LOSS" # Timeout interpretado como Loss por travamento

def check_robustez(simbolo, dados):
    if any(x in simbolo for x in BLACKLIST):
        return False, "BLACKLIST"
    spread = (dados['ask'] - dados['bid']) / dados['bid'] * 100
    if spread > ROBUSTEZ["MAX_SPREAD_PCT"]:
        return False, f"SPREAD_ALTO {spread:.2f}%"
    if dados['volume'] < dados['volume_media20'] * ROBUSTEZ["VOLUME_MIN_X_MEDIA"]:
        return False, "VOLUME_FRACO"
    if abs(dados['funding_rate']) > ROBUSTEZ["FUNDING_MAX"]:
        return False, "FUNDING_ALTO"
    ultimo = ESTADO["ultimo_trade_por_moeda"].get(simbolo, 0)
    if time.time() - ultimo < ROBUSTEZ["MAX_REENTRADA_MESMA_MOEDA"]:
        return False, "COOLDOWN_MOEDA"
    return True, "OK"

def sinal_entrada(dados):
    ema9 = dados['ema9']
    ema21 = dados['ema21']
    rsi = dados['rsi']
    long_ok = ema9 > ema21 and dados['cruzou_agora'] and rsi < (60 - ROBUSTEZ["RSI_HISTERESIS"])
    queda = dados['variacao_5m']
    short_ok = (-5 <= queda <= -2) and rsi > (40 + ROBUSTEZ["RSI_HISTERESIS"])
    if long_ok:
        return "LONG"
    if short_ok:
        return "SHORT"
    return None

def executar_com_teorema():
    print("🤖 Bot Iniciado com sucesso no Railway!")
    while True:
        if ESTADO["loss_consec"] >= 6:
            print("🚨 Circuit Breaker! 6 prejuízos seguidos. Pausando 2 horas.")
            time.sleep(7200)
            ESTADO["loss_consec"] = 0
            continue

        margem = SEQUENCIA[ESTADO["indice"]]

        for simbolo in ["WIF/USDT:USDT", "BONK/USDT:USDT"]: # Padrão de símbolos CCXT para Perpétuos BingX
            dados = get_dados_mercado(simbolo)
            pode, motivo = check_robustez(simbolo, dados)
            if not pode:
                continue
            sinal = sinal_entrada(dados)
            if not sinal:
                continue

            equity_start = get_equity()
            if equity_start == 0.0:
                print("Aguardando saldo válido...")
                time.sleep(10)
                continue
                
            ESTADO["equity_inicial_trade"] = equity_start
            tp_alvo = equity_start * (1 + TP_SALDO)
            sl_alvo = equity_start * (1 - SL_SALDO)
            ordem = abrir_isolada(simbolo, sinal, margem, ALAVANCAGEM)
            
            if not ordem:
                continue
                
            resultado = monitorar_equity_ate_tp_sl(tp_alvo, sl_alvo, timeout=ROBUSTEZ["EQUITY_STUCK_TIMEOUT"])

            if resultado == "WIN":
                ESTADO["wins_consec"] += 1
                ESTADO["loss_consec"] = 0
                ESTADO["loss_dia"] = 0
                if ESTADO["wins_consec"] >= 2:
                    if ESTADO["indice"] < 9:
                        ESTADO["indice"] += 1
                        print(f"🔥 DOBRA -> {SEQUENCIA[ESTADO['indice']]}")
                    else:
                        print("🏁 SEQUÊNCIA 10/10 COMPLETA")
                        return
                    ESTADO["wins_consec"] = 0
                time.sleep(ROBUSTEZ["COOLDOWN_WIN"])
            else:
                ESTADO["wins_consec"] = 0
                ESTADO["loss_consec"] += 1
                ESTADO["loss_dia"] += 1
                if ESTADO["loss_consec"] >= 6 and ESTADO["indice"] > 0:
                    ESTADO["indice"] -= 1
                    print(f"⚠️ RECUO -> {SEQUENCIA[ESTADO['indice']]}")
                    ESTADO["loss_consec"] = 0
                time.sleep(ROBUSTEZ["COOLDOWN_PERDA"])

            ESTADO["ultimo_trade_por_moeda"][simbolo] = time.time()
            break
        time.sleep(1)

if __name__ == "__main__":
    executar_com_teorema()
