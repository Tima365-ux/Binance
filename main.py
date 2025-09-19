# main.py
# This is our main file, now upgraded to a full web application!
# It runs a web server to provide an admin panel AND checks for trading signals in the background.

import os
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional
from collections import deque
import random

import ccxt.async_support as ccxt
import pandas as pd
import talib
import telegram
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

# --- SETUP & CONFIGURATION ---
load_dotenv()

# --- Environment Variables ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET = os.getenv("BINANCE_SECRET")
BOT_PIN = os.getenv("BOT_PIN", "1234")

# Load multiple Telegram account credentials
telegram_accounts = []
for i in range(1, 5):
    token = os.getenv(f"TELEGRAM_TOKEN_{i}")
    chat_id = os.getenv(f"TELEGRAM_CHAT_ID_{i}")
    name = os.getenv(f"TELEGRAM_NAME_{i}", f"Account {i}")
    if token and chat_id:
        telegram_accounts.append({"id": i, "token": token, "chat_id": chat_id, "name": name})

# --- File Paths for Persistence ---
CONFIG_FILE = "config.json"
HISTORY_FILE = "trade_history.json"

# --- Default Bot Configuration ---
DEFAULT_CONFIG = {
    "active_symbols": ['BTC/USDT', 'ETH/USDT'],
    "entry_timeframe": '5m',
    "higher_timeframes": ['30m', '1h', '4h'],
    "max_open_trades": 2,
    "rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70,
    "volume_avg_period": 20, "volume_factor": 1.5,
    "ema_short_period": 50, "ema_long_period": 200, "ema_entry_period": 20,
    "atr_period": 14, 
    "atr_stop_loss_factor": 1.0, 
    "atr_take_profit_factor": 2.0,
    "telegram_channels": [{"id": acc["id"], "name": acc["name"], "active": (i == 0)} for i, acc in enumerate(telegram_accounts)]
}

# --- Functions to load and save settings ---
def load_json(file_path, default_data):
    if not os.path.exists(file_path):
        return default_data
    with open(file_path, 'r') as f:
        try:
            saved_data = json.load(f)
            if isinstance(default_data, dict):
                updated_config = default_data.copy()
                updated_config.update(saved_data)
                return updated_config
            elif isinstance(saved_data, list):
                return saved_data
            else:
                return default_data
        except json.JSONDecodeError:
            return default_data

def save_json(file_path, data):
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=4)

# --- Initialize bot state ---
bot_config = load_json(CONFIG_FILE, DEFAULT_CONFIG)
trade_history = deque(load_json(HISTORY_FILE, []), maxlen=50) 
bot_status = {"status": "Working", "last_check": "Never", "binance_connection": "Connecting...", "last_error": "None", "market_type": "Futures"}
open_trades = 0

# --- CONNECTIONS ---
binance = ccxt.binance({
    'apiKey': BINANCE_API_KEY,
    'secret': BINANCE_SECRET,
    'options': {'defaultType': 'future'},
})

# --- HTML FRONTEND (with PIN screen, history table, status, and theme) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Crypto Bot Admin Panel</title>
    <link rel="icon" href="https://upload.wikimedia.org/wikipedia/commons/4/46/Bitcoin.svg" type="image/svg+xml">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        'primary-dark': '#5b21b6', 'primary-light': '#a78bfa',
                        'bkg-dark': '#111827', 'bkg-light': '#f3f4f6',
                        'card-dark': '#1f2937', 'card-light': '#ffffff',
                        'text-dark': '#d1d5db', 'text-light': '#1f2937',
                        'border-dark': '#374151', 'border-light': '#e5e7eb',
                    }
                }
            }
        }
    </script>
    <style> body { transition: background-color 0.3s, color 0.3s; } </style>
</head>
<body class="bg-bkg-light dark:bg-bkg-dark text-text-light dark:text-text-dark p-4 sm:p-8">

    <div id="pin-screen" class="fixed inset-0 bg-bkg-dark bg-opacity-90 flex items-center justify-center z-50">
        <div class="bg-card-dark p-8 rounded-lg shadow-2xl text-center w-80">
            <h2 class="text-2xl font-bold text-white mb-4">Enter PIN</h2>
            <input type="password" id="pin-input" maxlength="4" class="w-full p-3 mb-4 text-center text-2xl tracking-widest bg-border-dark rounded-md text-white focus:outline-none focus:ring-2 focus:ring-primary-light">
            <button id="pin-submit" class="w-full bg-primary-dark hover:bg-primary-light text-white font-bold py-2 px-4 rounded-lg">Unlock</button>
            <p id="pin-error" class="text-red-500 mt-2 h-4"></p>
        </div>
    </div>

    <div id="main-content" class="max-w-7xl mx-auto space-y-8 hidden">
        <div class="flex justify-between items-center">
            <h1 class="text-4xl font-bold">Crypto Bot Admin Panel</h1>
            <button id="theme-toggle" class="p-2 rounded-full bg-card-light dark:bg-card-dark border border-border-light dark:border-border-dark"></button>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div class="lg:col-span-1 bg-card-light dark:bg-card-dark border border-border-light dark:border-border-dark p-6 rounded-lg shadow-lg">
                <h2 class="text-2xl font-semibold mb-4">Bot Status</h2>
                <div id="bot-status" class="space-y-2 text-lg">...</div>
            </div>
            <div class="lg:col-span-2 bg-card-light dark:bg-card-dark border border-border-light dark:border-border-dark p-6 rounded-lg shadow-lg">
                <h2 class="text-2xl font-semibold mb-4">Live Prices</h2>
                <div id="live-prices" class="grid grid-cols-2 sm:grid-cols-4 gap-4 text-center">
                    <div id="price-BTCUSDT">...</div> <div id="price-ETHUSDT">...</div>
                    <div id="price-XRPUSDT">...</div> <div id="price-BNBUSDT">...</div>
                </div>
            </div>
        </div>
        
        <div class="bg-card-light dark:bg-card-dark border border-border-light dark:border-border-dark p-6 rounded-lg shadow-lg">
             <h2 class="text-2xl font-semibold mb-4">Recent Signals</h2>
             <div class="overflow-x-auto">
                <table class="w-full text-left">
                    <thead class="border-b border-border-light dark:border-border-dark">
                        <tr>
                            <th class="p-2">Time</th><th class="p-2">Asset</th><th class="p-2">Type</th>
                            <th class="p-2">Entry Price</th><th class="p-2">Stop Loss</th>
                        </tr>
                    </thead>
                    <tbody id="history-table"></tbody>
                </table>
            </div>
        </div>
        
        <form id="settings-form" class="space-y-8">
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                <div class="lg:col-span-2 bg-card-light dark:bg-card-dark border border-border-light dark:border-border-dark p-6 rounded-lg shadow-lg space-y-6">
                    <h2 class="text-2xl font-semibold">Bot Settings</h2>
                    <div>
                        <label class="block mb-2 font-medium">Active Symbols</label>
                        <div class="flex space-x-4">
                            <label><input type="checkbox" name="symbols" value="BTC/USDT"> BTC</label>
                            <label><input type="checkbox" name="symbols" value="ETH/USDT"> ETH</label>
                            <label><input type="checkbox" name="symbols" value="XRP/USDT"> XRP</label>
                            <label><input type="checkbox" name="symbols" value="BNB/USDT"> BNB</label>
                        </div>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="rsi_oversold" class="block mb-2 font-medium">RSI Oversold (Buy)</label>
                            <input type="number" step="1" id="rsi_oversold" name="rsi_oversold" class="w-full p-2 rounded-md bg-bkg-light dark:bg-bkg-dark border border-border-light dark:border-border-dark">
                        </div>
                        <div>
                            <label for="rsi_overbought" class="block mb-2 font-medium">RSI Overbought (Sell)</label>
                            <input type="number" step="1" id="rsi_overbought" name="rsi_overbought" class="w-full p-2 rounded-md bg-bkg-light dark:bg-bkg-dark border border-border-light dark:border-border-dark">
                        </div>
                    </div>
                     <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                            <label for="atr_stop_loss_factor" class="block mb-2 font-medium">Stop Loss (ATR Multiplier)</label>
                            <input type="number" step="0.1" id="atr_stop_loss_factor" name="atr_stop_loss_factor" class="w-full p-2 rounded-md bg-bkg-light dark:bg-bkg-dark border border-border-light dark:border-border-dark">
                        </div>
                        <div>
                            <label for="atr_take_profit_factor" class="block mb-2 font-medium">Take Profit (ATR Multiplier)</label>
                            <input type="number" step="0.1" id="atr_take_profit_factor" name="atr_take_profit_factor" class="w-full p-2 rounded-md bg-bkg-light dark:bg-bkg-dark border border-border-light dark:border-border-dark">
                        </div>
                    </div>
                </div>
                <div class="bg-card-light dark:bg-card-dark border border-border-light dark:border-border-dark p-6 rounded-lg shadow-lg">
                    <h2 class="text-2xl font-semibold mb-4">Telegram Channels</h2>
                    <div id="telegram-channels" class="space-y-4"></div>
                </div>
            </div>
            <div class="flex justify-end pt-4">
                <button type="submit" class="bg-primary-dark hover:bg-primary-light text-white font-bold py-3 px-6 rounded-lg shadow-md text-lg">Save All Settings</button>
            </div>
        </form>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div class="bg-card-light dark:bg-card-dark border border-border-light dark:border-border-dark p-6 rounded-lg shadow-lg">
                <h2 class="text-2xl font-semibold mb-4">Test Mode</h2>
                <div class="flex flex-col space-y-4">
                    <button id="force-check-btn" class="bg-blue-600 hover:bg-blue-500 text-white font-bold py-2 px-4 rounded-lg shadow-md">Force Signal Check</button>
                    <button id="fake-signal-btn" class="bg-yellow-600 hover:bg-yellow-500 text-white font-bold py-2 px-4 rounded-lg shadow-md">Generate Fake Signal</button>
                    <button id="test-telegram-btn" class="bg-green-600 hover:bg-green-500 text-white font-bold py-2 px-4 rounded-lg shadow-md">Send Test Message</button>
                </div>
            </div>
            <div class="bg-card-light dark:bg-card-dark border border-border-light dark:border-border-dark p-6 rounded-lg shadow-lg">
                <h2 class="text-2xl font-semibold mb-4">Connectivity Test</h2>
                <button id="run-test-btn" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold py-2 px-4 rounded-lg shadow-md">Run Test</button>
                <div id="test-results" class="mt-4 space-y-2 text-sm"></div>
            </div>
        </div>
        <div id="status-message" class="text-center p-4 rounded-md hidden"></div>
    </div>

    <script>
        const pinScreen = document.getElementById('pin-screen');
        const mainContent = document.getElementById('main-content');
        const pinInput = document.getElementById('pin-input');
        const pinSubmit = document.getElementById('pin-submit');
        const pinError = document.getElementById('pin-error');
        const themeToggle = document.getElementById('theme-toggle');

        pinSubmit.addEventListener('click', async () => {
            const response = await fetch('/api/verify_pin', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pin: pinInput.value })
            });
            if (response.ok) {
                pinScreen.classList.add('hidden');
                mainContent.classList.remove('hidden');
                startApp();
            } else {
                pinError.textContent = 'Incorrect PIN'; pinInput.value = '';
            }
        });
        pinInput.addEventListener('keyup', (e) => { if(e.key === 'Enter') pinSubmit.click() });

        const sunIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" /></svg>`;
        const moonIcon = `<svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" /></svg>`;
        function applyTheme(isDark) {
            document.documentElement.classList.toggle('dark', isDark);
            themeToggle.innerHTML = isDark ? sunIcon : moonIcon;
            localStorage.theme = isDark ? 'dark' : 'light';
        }
        themeToggle.addEventListener('click', () => applyTheme(!document.documentElement.classList.contains('dark')));
        applyTheme(localStorage.theme === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches));

        function startApp() {
            fetchSettings();
            setInterval(fetchPrices, 10000); fetchPrices();
            setInterval(fetchStatus, 5000); fetchStatus();
            setInterval(fetchHistory, 5000); fetchHistory();
        }
        
        function fetchSettings() {
            fetch('/api/settings').then(res => res.json()).then(config => {
                document.getElementById('rsi_oversold').value = config.rsi_oversold;
                document.getElementById('rsi_overbought').value = config.rsi_overbought;
                document.getElementById('atr_stop_loss_factor').value = config.atr_stop_loss_factor;
                document.getElementById('atr_take_profit_factor').value = config.atr_take_profit_factor;
                
                document.querySelectorAll('input[name="symbols"]').forEach(cb => {
                    cb.checked = config.active_symbols.includes(cb.value);
                });

                const channelsContainer = document.getElementById('telegram-channels');
                channelsContainer.innerHTML = '';
                if (config.telegram_channels && config.telegram_channels.length > 0) {
                    config.telegram_channels.forEach(ch => {
                        const div = document.createElement('div');
                        div.className = 'flex items-center space-x-2';
                        div.innerHTML = `
                            <input type="checkbox" id="tg_active_${ch.id}" name="tg_active_${ch.id}" ${ch.active ? 'checked' : ''} class="h-5 w-5 rounded">
                            <input type="text" id="tg_name_${ch.id}" name="tg_name_${ch.id}" value="${ch.name}" class="w-full p-2 rounded-md bg-bkg-light dark:bg-bkg-dark border border-border-light dark:border-border-dark">
                        `;
                        channelsContainer.appendChild(div);
                    });
                } else {
                    channelsContainer.innerHTML = '<p class="text-gray-400">No Telegram accounts found. Please configure them in your .env file.</p>';
                }
            });
        }

        async function fetchPrices() {
            try {
                const response = await fetch('/api/live_prices');
                if (!response.ok) { return; }
                const prices = await response.json();
                ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'BNB/USDT'].forEach(symbol => {
                    const el = document.getElementById(`price-${symbol.replace('/', '')}`);
                    if (!el) return;
                    const priceData = prices[symbol];
                    if (priceData && typeof priceData.price === 'number') {
                        el.innerHTML = `<div class="font-bold text-lg">${symbol.replace('/USDT', '')}</div><div class="text-2xl font-mono ${priceData.change >= 0 ? 'text-green-400' : 'text-red-400'}">$${priceData.price.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 4})}</div><div class="text-sm ${priceData.change >= 0 ? 'text-green-500' : 'text-red-500'}">${priceData.change.toFixed(2)}%</div>`;
                    } else {
                        el.innerHTML = `<div class="font-bold text-lg">${symbol.replace('/USDT', '')}</div><div class="text-gray-500">N/A</div>`;
                    }
                });
            } catch (error) { console.error("Error fetching prices:", error); }
        }

        async function fetchStatus() {
            const res = await fetch('/api/status'); const data = await res.json();
            const statusColor = data.status === 'Working' ? 'text-green-500' : 'text-yellow-500';
            const binanceColor = data.binance_connection === 'Connected' ? 'text-green-500' : 'text-red-500';
            let statusHTML = `
                <div>Status: <span class="font-bold ${statusColor}">${data.status}</span></div>
                <div>Binance: <span class="font-bold ${binanceColor}">${data.binance_connection}</span></div>
                <div>Market Type: <span class="font-bold text-blue-400">${data.market_type}</span></div>
                <div>Last Check: <span class="font-mono">${data.last_check}</span></div>`;
            if (data.last_error && data.last_error !== "None") {
                statusHTML += `<div class="mt-2 p-2 bg-red-900 bg-opacity-50 rounded-md break-words"><span class="font-bold text-red-400">Error:</span> <span class="text-sm text-red-300">${data.last_error}</span></div>`;
            }
            document.getElementById('bot-status').innerHTML = statusHTML;
        }

        async function fetchHistory() {
            const res = await fetch('/api/trade_history'); const data = await res.json();
            const tableBody = document.getElementById('history-table');
            tableBody.innerHTML = data.map(trade => `
                <tr class="border-b border-border-light dark:border-border-dark">
                    <td class="p-2">${trade.time}</td>
                    <td class="p-2 font-bold">${trade.asset}</td>
                    <td class="p-2 font-bold ${trade.type === 'Long' ? 'text-green-500' : 'text-red-500'}">${trade.type}</td>
                    <td class="p-2 font-mono">$${trade.entry_price}</td>
                    <td class="p-2 font-mono">$${trade.sl_price}</td>
                </tr>`).join('');
        }

        const form = document.getElementById('settings-form');
        const statusMessage = document.getElementById('status-message');
        
        form.addEventListener('submit', async (e) => {
             e.preventDefault();
             const formData = new FormData(form);
             const data = {
                 active_symbols: formData.getAll('symbols'),
                 rsi_oversold: parseFloat(formData.get('rsi_oversold')),
                 rsi_overbought: parseFloat(formData.get('rsi_overbought')),
                 atr_stop_loss_factor: parseFloat(formData.get('atr_stop_loss_factor')),
                 atr_take_profit_factor: parseFloat(formData.get('atr_take_profit_factor')),
                 telegram_channels: []
             };
             
             const tgContainer = document.getElementById('telegram-channels');
             const channelDivs = tgContainer.querySelectorAll('div');
             channelDivs.forEach(div => {
                 const idInput = div.querySelector('input[type="checkbox"]');
                 if (idInput) {
                    const id = idInput.id.split('_').pop();
                    const name = div.querySelector('input[type="text"]').value;
                    const active = idInput.checked;
                    data.telegram_channels.push({ id: parseInt(id), name, active });
                 }
             });

             const response = await fetch('/api/settings', {
                 method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
             });
             showStatus(response.ok ? "Settings saved!" : "Failed to save.", response.ok);
        });

        document.getElementById('test-telegram-btn').addEventListener('click', async () => {
            const res = await fetch('/api/test_telegram', { method: 'POST' });
            showStatus(res.ok ? "Test message sent to active channels!" : "Failed to send.", res.ok);
        });
        document.getElementById('force-check-btn').addEventListener('click', async () => {
            const res = await fetch('/api/force_check', { method: 'POST' });
            showStatus(res.ok ? "Forced signal check started." : "Failed to force check.", res.ok);
        });
        document.getElementById('fake-signal-btn').addEventListener('click', async () => {
            const res = await fetch('/api/fake_signal', { method: 'POST' });
            showStatus(res.ok ? "Fake signal generated!" : "Failed to generate.", res.ok);
            fetchHistory();
        });
        
        document.getElementById('run-test-btn').addEventListener('click', async () => {
            const resultsEl = document.getElementById('test-results');
            resultsEl.innerHTML = '<p>Running test...</p>';
            const res = await fetch('/api/connectivity_test', { method: 'POST' });
            const data = await res.json();
            
            let resultsHTML = `
                <div class="p-2 rounded ${data.futures_success ? 'bg-green-900 bg-opacity-50' : 'bg-red-900 bg-opacity-50'}">
                    <p class="font-bold">Futures Market:</p>
                    <p class="font-mono break-all text-xs">${data.futures_result}</p>
                </div>
                <div class="p-2 rounded ${data.spot_success ? 'bg-green-900 bg-opacity-50' : 'bg-red-900 bg-opacity-50'}">
                    <p class="font-bold">Spot Market:</p>
                    <p class="font-mono break-all text-xs">${data.spot_result}</p>
                </div>
            `;
            resultsEl.innerHTML = resultsHTML;
        });

        function showStatus(message, isSuccess) {
            statusMessage.textContent = message;
            statusMessage.className = `text-center p-4 rounded-md ${isSuccess ? 'bg-green-600' : 'bg-red-600'} text-white`;
            statusMessage.classList.remove('hidden');
            setTimeout(() => { statusMessage.classList.add('hidden'); }, 3000);
        }
    </script>
</body>
</html>
"""

# --- FASTAPI WEB SERVER ---
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def get_admin_panel(): return HTML_TEMPLATE

@app.post("/api/verify_pin")
async def verify_pin(req: Request):
    data = await req.json()
    if data.get("pin") == BOT_PIN: return JSONResponse({"status": "success"})
    raise HTTPException(status_code=401, detail="Incorrect PIN")

@app.get("/api/settings")
async def get_settings(): return JSONResponse(bot_config)
@app.get("/api/status")
async def get_status(): return JSONResponse(bot_status)
@app.get("/api/trade_history")
async def get_trade_history(): return JSONResponse(list(trade_history)[:10])

@app.post("/api/connectivity_test")
async def connectivity_test():
    futures_ok, futures_res = False, ""
    spot_ok, spot_res = False, ""
    
    try:
        binance.options['defaultType'] = 'future'
        ticker = await binance.fetch_ticker('BTC/USDT')
        if ticker and 'last' in ticker:
            futures_ok = True; futures_res = f"Success! Last price: ${ticker['last']}"
        else:
            futures_res = "Connection OK, but received empty data. Please check if your Binance account is fully activated for Futures trading (e.g., have you completed the Futures Quiz?)."
    except Exception as e: futures_res = f"Error: {e}"

    try:
        binance.options['defaultType'] = 'spot'
        ticker = await binance.fetch_ticker('BTC/USDT')
        if ticker and 'last' in ticker:
            spot_ok = True; spot_res = f"Success! Last price: ${ticker['last']}"
        else: spot_res = "Connection OK, but received empty data."
    except Exception as e: spot_res = f"Error: {e}"
        
    return JSONResponse({
        "futures_success": futures_ok, "futures_result": futures_res,
        "spot_success": spot_ok, "spot_result": spot_res
    })

@app.get("/api/live_prices")
async def live_prices():
    global bot_status
    symbols = ['BTC/USDT', 'ETH/USDT', 'XRP/USDT', 'BNB/USDT']
    tickers = {}
    
    market_to_try = 'future'
    try:
        active_market = bot_status.get("market_type", "Futures").lower()
        if "spot" in active_market: market_to_try = 'spot'
        binance.options['defaultType'] = market_to_try
        
        for symbol in symbols:
            try:
                ticker_data = await binance.fetch_ticker(symbol)
                if ticker_data: tickers[symbol] = ticker_data
            except Exception as e: print(f"Could not fetch {symbol} from {market_to_try}: {e}")
                
        if tickers:
            bot_status.update({"binance_connection": "Connected", "last_error": "None", "market_type": market_to_try.capitalize()})
            return JSONResponse({s: {"price": t['last'], "change": t['percentage']} for s, t in tickers.items()})

        fallback_market = 'spot' if market_to_try == 'future' else 'future'
        print(f"Primary market '{market_to_try}' empty, trying fallback '{fallback_market}'...")
        binance.options['defaultType'] = fallback_market
        
        for symbol in symbols:
            try:
                ticker_data = await binance.fetch_ticker(symbol)
                if ticker_data: tickers[symbol] = ticker_data
            except Exception as e: print(f"Could not fetch {symbol} from {fallback_market}: {e}")

        if tickers:
            bot_status.update({"binance_connection": "Connected", "last_error": "None", "market_type": f"{fallback_market.capitalize()} (Fallback)"})
            return JSONResponse({s: {"price": t['last'], "change": t['percentage']} for s, t in tickers.items()})
        
        raise Exception("Failed to fetch price data from both Futures and Spot markets.")
    except Exception as e:
        bot_status.update({"binance_connection": "Price Fetch Failed", "last_error": str(e)})
        return JSONResponse({}, status_code=500)

@app.post("/api/settings")
async def update_settings(req: Request):
    data = await req.json()
    bot_config.update(data)
    save_json(CONFIG_FILE, bot_config)
    print("Bot settings updated.")
    return JSONResponse({"status": "success"})

# --- CORE BOT LOGIC ---
async def send_single_telegram_message(token, chat_id, message):
    try:
        bot = telegram.Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=message, parse_mode='HTML')
        print(f"Sent message to chat_id {chat_id}")
    except Exception as e:
        print(f"Error sending to chat_id {chat_id}: {e}")
        bot_status["last_error"] = f"Failed to send to {chat_id}: {e}"

async def send_telegram_message(message: str):
    active_channels_config = [ch for ch in bot_config.get("telegram_channels", []) if ch.get("active")]
    if not active_channels_config:
        print("No active Telegram channels to send message to.")
        return

    tasks = []
    for channel_config in active_channels_config:
        for account in telegram_accounts:
            if account["id"] == channel_config["id"]:
                tasks.append(send_single_telegram_message(account["token"], account["chat_id"], message))
                break
    
    await asyncio.gather(*tasks, return_exceptions=True)

@app.post("/api/test_telegram")
async def test_telegram():
    await send_telegram_message("✅ Admin Panel Test: Your Telegram connection is working!")
    return JSONResponse({"status": "success"})

@app.post("/api/force_check")
async def force_check():
    asyncio.create_task(check_signals())
    return JSONResponse({"status": "check_started"})

@app.post("/api/fake_signal")
async def fake_signal():
    try:
        # Fetch the current price for a more realistic fake signal
        ticker = await binance.fetch_ticker('BTC/USDT')
        price = ticker['last']
        atr = price * 0.01 # Use a simple ATR estimation for the fake signal
    except Exception:
        # Fallback to random price if API fails
        price = random.uniform(60000, 70000)
        atr = price * 0.01

    sl = price - (atr * bot_config['atr_stop_loss_factor'])
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "asset": "BTC/USDT",
        "type": "Long", "entry_price": f"{price:,.2f}", "sl_price": f"{sl:,.2f}"
    }
    trade_history.appendleft(entry)
    save_json(HISTORY_FILE, list(trade_history))
    await send_telegram_message(f"🧪 FAKE SIGNAL: See history for details.")
    return JSONResponse({"status": "fake_signal_generated"})

async def get_market_data(s, t, l=201): return pd.DataFrame(await binance.fetch_ohlcv(s, t, limit=l), columns=['t', 'o', 'h', 'l', 'c', 'v'])

def calculate_indicators(df, cfg):
    df['ema_s'] = talib.EMA(df['c'], cfg['ema_short_period'])
    df['ema_l'] = talib.EMA(df['c'], cfg['ema_long_period'])
    df['ema_e'] = talib.EMA(df['c'], cfg['ema_entry_period'])
    df['rsi'] = talib.RSI(df['c'], cfg['rsi_period'])
    df['atr'] = talib.ATR(df['h'], df['l'], df['c'], cfg['atr_period'])
    df['vol_avg'] = df['v'].rolling(cfg['volume_avg_period']).mean()
    return df

async def process_signal(symbol, signal_type, entry_price, atr):
    global open_trades
    open_trades += 1
    
    sl_factor = bot_config['atr_stop_loss_factor']
    tp_factor = bot_config['atr_take_profit_factor']
    
    if signal_type == "Long":
        sl_price = entry_price - (atr * sl_factor); tp_price = entry_price + (atr * tp_factor)
    else: # Short
        sl_price = entry_price + (atr * sl_factor); tp_price = entry_price - (atr * sl_factor)

    trade_entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "asset": symbol,
        "type": signal_type, "entry_price": f"{entry_price:,.2f}", "sl_price": f"{sl_price:,.2f}"
    }
    trade_history.appendleft(trade_entry)
    save_json(HISTORY_FILE, list(trade_entry))

    msg = (f"🚨 <b>{signal_type.upper()} {symbol}</b>\n\n"
           f"<b>Entry:</b> ${entry_price:,.2f}\n"
           f"<b>Stop Loss:</b> ${sl_price:,.2f}\n"
           f"<b>Take Profit:</b> ${tp_price:,.2f}")
    await send_telegram_message(msg)
    print(f"!!! {signal_type.upper()} SIGNAL for {symbol} !!!")

async def check_signals():
    global open_trades, bot_status
    bot_status["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if open_trades >= bot_config['max_open_trades']: return

    for symbol in bot_config['active_symbols']:
        try:
            binance.options['defaultType'] = 'future'
            htf_data = await asyncio.gather(*[get_market_data(symbol, tf) for tf in bot_config['higher_timeframes']])
            
            long_align, short_align = 0, 0
            for df_htf in htf_data:
                if df_htf.empty: continue
                df_htf = calculate_indicators(df_htf, bot_config)
                if df_htf['ema_s'].iloc[-1] > df_htf['ema_l'].iloc[-1]: long_align += 1
                if df_htf['ema_s'].iloc[-1] < df_htf['ema_l'].iloc[-1]: short_align += 1

            df_5m = await get_market_data(symbol, bot_config['entry_timeframe'])
            if df_5m.empty: continue
            df_5m = calculate_indicators(df_5m, bot_config)
            last, prev = df_5m.iloc[-1], df_5m.iloc[-2]
            
            if long_align >= 2 and (prev['rsi'] < bot_config['rsi_oversold'] and last['rsi'] > bot_config['rsi_oversold'] and
                last['v'] > bot_config['volume_factor'] * last['vol_avg'] and last['c'] > last['ema_e']):
                await process_signal(symbol, "Long", last['c'], last['atr'])
                if open_trades >= bot_config['max_open_trades']: break
                continue

            if short_align >= 2 and (prev['rsi'] > bot_config['rsi_overbought'] and last['rsi'] < bot_config['rsi_overbought'] and
                last['v'] > bot_config['volume_factor'] * last['vol_avg'] and last['c'] < last['ema_e']):
                await process_signal(symbol, "Short", last['c'], last['atr'])
                if open_trades >= bot_config['max_open_trades']: break

        except Exception as e: 
            error_message = f"Signal Check Error: {e}"
            print(f"Error checking {symbol}: {error_message}")
            bot_status["last_error"] = error_message

@app.on_event("startup")
async def startup_event():
    global bot_status
    try:
        await binance.load_markets()
        await binance.fetch_time()
        bot_status["binance_connection"] = "Connected"
        print("Successfully connected to Binance.")
    except Exception as e:
        bot_status["binance_connection"] = "Failed"
        bot_status["last_error"] = str(e)
        print(f"!!! FAILED to connect to Binance: {e}")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_signals, 'interval', minutes=5, misfire_grace_time=60)
    scheduler.start()
    print("FastAPI server started. Background checker is running.")
    asyncio.create_task(check_signals())

@app.on_event("shutdown")
async def shutdown_event(): await binance.close()
