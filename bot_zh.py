#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot_zh.py — Gold & Forex · 章鱼智投 AI 交易信号 Bot
# 版本: v2.0 | 2026-07-01 | 频道: @forex_gold_ai
# 功能：信号推送 + 止盈监控 + 市场提醒 + 欢迎消息 + HTTP保活

import os
import sys
import json
import time
import random
import logging
import requests
import pytz
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ─── 配置区 ──────────────────────────────────────────────────────────────

BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "8951847612:AAGYXG5YvLkjzSLGfJVeF6uPRT_B1E2eXHU")
CHINESE_CID = os.environ.get("CHINESE_CID", "-1003902939336")  # @forex_gold_ai

OCTOPUS_API     = "https://app.octopus-vision.com/prod-api/appHuginn/app-api/ai/quote-predict/latest"
OCTOPUS_HEADERS = {"Client-Type": "ANDROID", "Platform": "OCTOPUS", "Accept-Language": "zh-TW"}

# ─── 日志 ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("bot_zh")

# ─── 全局状态（止盈监控）─────────────────────────────────────────────────

active_signals = []  # 正在监控的信号列表
# 每个元素: {"entry_time", "entry_price", "direction", "target_price", "notified"}

# ─── 工具函数 ──────────────────────────────────────────────────────────────

def tg_api(method, payload=None, retries=3):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    for i in range(retries):
        try:
            if payload:
                r = requests.post(url, json=payload, timeout=10)
            else:
                r = requests.get(url, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning(f"  tg_api {method} 失败({i+1}/{retries}): {e}")
            time.sleep(2)
    return None


def fetch_octopus(symbol="XAUUSD"):
    """调用 Octopus API 获取信号数据"""
    try:
        url = f"{OCTOPUS_API}?systemCode={symbol}"
        resp = requests.get(url, headers=OCTOPUS_HEADERS, timeout=15)
        data = resp.json()
        if data.get("code") == 200 and data.get("data"):
            return data["data"]
        log.warning(f"  [API] {symbol} 返回异常: {data}")
    except Exception as e:
        log.warning(f"  [API] 获取 {symbol} 失败: {e}")
    return None


def fetch_current_xauusd_price():
    """获取 XAUUSD 当前价格（用于止盈监控）"""
    try:
        # 方案1：用 Octopus API 获取当前数据
        data = fetch_octopus("XAUUSD")
        if data:
            # API 返回的数据中包含当前价格相关字段
            # 尝试从返回数据中提取当前价
            # 如果有 currentPrice 字段直接用
            if "currentPrice" in data:
                return float(data["currentPrice"])
            # 否则用支撑位和阻力位的中间值作为近似当前价
            support = data.get("supportPrice")
            resist  = data.get("resistancePrice")
            if support and resist:
                return (float(support) + float(resist)) / 2
        # 方案2：备用免费金价 API
        r = requests.get("https://data-asg.goldprice.org/dbXRates/USD", timeout=10)
        js = r.json()
        # 返回格式: {"items":[{"xauPrice": 2345.67, ...}]}
        price = js.get("items", [{}])[0].get("xauPrice")
        if price:
            return float(price)
    except Exception as e:
        log.warning(f"  [TP] 获取当前金价失败: {e}")
    return None


def get_beijing_weekday():
    beijing_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(beijing_tz)
    return now.weekday()


def get_local_weekday(tz_str):
    try:
        tz = pytz.timezone(tz_str)
        now = datetime.now(tz)
        return now.weekday()
    except:
        return get_beijing_weekday()


def seconds_to_next_utc(target_hour_local, target_minute_local, tz_str="Asia/Shanghai"):
    tz = pytz.timezone(tz_str)
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(tz)
    target_local = now_local.replace(
        hour=target_hour_local,
        minute=target_minute_local,
        second=0,
        microsecond=0
    )
    if target_local <= now_local:
        target_local += timedelta(days=1)
    target_utc = target_local.astimezone(timezone.utc)
    return int((target_utc - now_utc).total_seconds())


# ─── 信号推送 ─────────────────────────────────────────────────────────────

SYMBOL_NAMES_ZH = {
    "XAUUSD": "黃金",
    "BTCUSDT": "比特币",
    "XAGUSD": "白銀",
    "USOUSD": "原油",
    "ETHUSDT": "以太坊",
}

def build_signal_message(symbol="XAUUSD"):
    data = fetch_octopus(symbol)
    if not data:
        if symbol == "XAUUSD":
            log.info(f"  {symbol} 无数据，尝试 BTCUSDT")
            return build_signal_message("BTCUSDT")
        return None
    try:
        direction     = data.get("direction", "NEUTRAL").upper()
        prob         = int(data.get("directionProbability", 0))
        support_p    = data.get("supportPrice", "N/A")
        resist_p     = data.get("resistancePrice", "N/A")
        target_p     = data.get("targetPrice", "N/A")
        change_r     = data.get("changeRate", "")
        period       = data.get("updatePeriod", "1H")
        name_raw     = data.get("name", symbol)
        sym_name    = str(name_raw).strip() or SYMBOL_NAMES_ZH.get(symbol, symbol)
        suggestion_raw = data.get("suggestion", "")
        ai_text      = str(suggestion_raw).strip()

        if direction == "UP":
            emoji, arrow, dir_text = "🔵", "⬆️", "做多"
        elif direction == "DOWN":
            emoji, arrow, dir_text = "🔴", "⬇️", "做空"
        else:
            emoji, arrow, dir_text = "⚪", "➖", "持有"

        lines = [
            f"{emoji} {symbol} · {sym_name}",
            f"{arrow} {dir_text}  {prob}%  |  {period}  |  {change_r}",
            "",
            f"🎯 目标位:  {target_p}",
            f"🛡️ 支撑位:  {support_p}",
            f"🚧 阻力位:  {resist_p}",
            "",
            f"📊 AI分析: {ai_text}",
            "",
            "⚠️ 投资有风险，入市需谨慎。",
            "🤝 商务合作: @Luna_OctaTradeHK",
        ]

        # 保存信号数据供止盈监控使用
        result = {
            "symbol":       symbol,
            "sym_name":    sym_name,
            "direction":   direction,
            "prob":        prob,
            "target_price": float(target_p) if isinstance(target_p, (int, float)) or (isinstance(target_p, str) and target_p.replace(".","").isdigit()) else None,
            "support_price": float(support_p) if isinstance(support_p, (int, float)) or (isinstance(support_p, str) and support_p.replace(".","").isdigit()) else None,
            "msg_lines":   lines,
        }
        return result  # 返回 dict，send_signal_to_channel 负责格式化为字符串

    except Exception as e:
        log.warning(f"  构造消息失败: {e}")
        return None


def format_signal_message(signal_dict):
    """将信号 dict 格式化为 TG 消息字符串"""
    lines = signal_dict["msg_lines"]
    return "\n".join(lines)


def send_signal_to_channel():
    """推送信号到频道，并注册止盈监控"""
    log.info("  [信号] 开始推送...")
    signal_dict = build_signal_message("XAUUSD")
    if not signal_dict:
        log.warning("  [信号] 无数据，跳过")
        return

    msg = format_signal_message(signal_dict)
    payload = {
        "chat_id": CHINESE_CID,
        "text": msg,
        "parse_mode": "HTML",
    }

    result = tg_api("sendMessage", payload)
    if result and result.get("ok"):
        signal_msg_id = result["result"]["message_id"]
        log.info("  [信号] 推送成功 (msg_id=%s)", signal_msg_id)
        # 注册止盈监控（仅 XAUUSD 且目标价有效时）
        if signal_dict["symbol"] == "XAUUSD" and signal_dict["target_price"] is not None:
            entry_price = fetch_current_xauusd_price()
            if entry_price:
                active_signals.append({
                    "entry_time":   datetime.now(pytz.timezone("Asia/Shanghai")),
                    "entry_price":  entry_price,
                    "direction":    signal_dict["direction"],
                    "target_price": signal_dict["target_price"],
                    "support_price": signal_dict["support_price"],
                    "signal_msg_id": signal_msg_id,
                    "notified":     False,
                })
                log.info(f"  [TP] 开始监控：入场价 {entry_price:.2f}，目标价 {signal_dict['target_price']:.2f}")
            else:
                log.warning("  [TP] 无法获取当前金价，跳过监控注册")
    else:
        log.warning(f"  [信号] 推送失败: {result}")


# ─── 止盈监控 ─────────────────────────────────────────────────────────────

def start_tp_monitor():
    """后台线程 — 每5分钟检查止盈位，触达即提醒"""
    log.info("  [TP] 止盈监控线程启动")
    while True:
        try:
            now = datetime.now(pytz.timezone("Asia/Shanghai"))

            # 清理超过 2 小时未触发的旧信号
            active_signals[:] = [
                s for s in active_signals
                if (now - s["entry_time"]).total_seconds() < 7200
            ]

            if not active_signals:
                time.sleep(300)
                continue

            # 获取当前金价
            current_price = fetch_current_xauusd_price()
            if current_price is None:
                log.warning("  [TP] 无法获取当前金价，跳过本轮检查")
                time.sleep(300)
                continue

            log.info(f"  [TP] 当前金价: {current_price:.2f}，监控中信号数: {len(active_signals)}")

            for sig in active_signals:
                if sig["notified"]:
                    continue

                direction    = sig["direction"]
                target_price = sig["target_price"]
                tp_hit      = False

                if direction == "UP" and current_price >= target_price:
                    tp_hit = True
                elif direction == "DOWN" and current_price <= target_price:
                    tp_hit = True

                if tp_hit:
                    entry_price = sig["entry_price"]
                    # 计算止盈点数（XAUUSD: 价格差 × 100 = 点数）
                    point_val = 100  # XAUUSD 0.01 = 1 point
                    if direction == "UP":
                        points = int(round((current_price - entry_price) * point_val))
                    else:
                        points = int(round((entry_price - current_price) * point_val))

                    entry_time_str = sig["entry_time"].strftime("%H:%M")

                    notify_msg = (
                        "🎉 <b>止盈提醒</b>\n\n"
                        f"🕐 上车时间: {entry_time_str}\n"
                        f"💰 上车单价: {entry_price:.2f}\n"
                        f"💰 下车单价: {current_price:.2f}\n"
                        f"📈 止盈: <b>{points} 点</b>"
                    )

                    payload = {
                        "chat_id": CHINESE_CID,
                        "text": notify_msg,
                        "parse_mode": "HTML",
                    }
                    # 引用原始信号消息（引用05分推送的那条）
                    if sig.get("signal_msg_id"):
                        payload["reply_to_message_id"] = sig["signal_msg_id"]
                    result = tg_api("sendMessage", payload)
                    if result and result.get("ok"):
                        log.info(f"  [TP] 止盈提醒已发送！点数: {points}")
                        # 发送贴纸 💰
                        sticker_payload = {
                            "chat_id": CHINESE_CID,
                            "sticker": "CAACAgUAAyEFAATooiDIAANmakTNYWL42MUfQAEuXqxqIpOlOhQAAmoSAAL2IslWYpFBlKEWcp88BA",
                            "reply_to_message_id": result["result"]["message_id"],
                        }
                        tg_api("sendSticker", sticker_payload)
                        sig["notified"] = True
                    else:
                        log.warning(f"  [TP] 止盈提醒发送失败: {result}")

            # 本轮检查完毕，移除已通知的信号
            active_signals[:] = [s for s in active_signals if not s.get("notified", False)]

            time.sleep(300)  # 每 5 分钟检查一次

        except Exception as e:
            log.warning(f"  [TP] 异常: {e}")
            time.sleep(300)


# ─── 市场提醒 ─────────────────────────────────────────────────────────────

TIPS_ZH = {
    "Wellington": [
        "亚太时段开启 — 新的一周开始了！🌏",
        "悉尼开盘 — 关注澳元货币对 🇦🇺",
        "新的一周，新的机会！🚀",
    ],
    "Tokyo": [
        "东京时段开启 — 关注日元货币对 🇯🇵",
        "亚洲流动性涌入 — 保持敏锐！⚡",
        "东京定盘时间临近 — 预计波动加大 📊",
    ],
    "London": [
        "伦敦开盘 — 欧洲流动性闸门开启 🇬🇧",
        "英国时段开启 — 欧元/英镑预计波动加大 📈",
        "法兰克福 🇩🇪、苏黎世 🇨🇭 和巴黎 🇫🇷 即将开市。",
        "祝你交易顺利！📈",
    ],
    "New_York": [
        "美国时段开启 — 华尔街正在醒来 🇺🇸",
        "纽约开盘 — 准备好迎接波动！📊",
        "美国经济数据即将公布 — 关注财经日历！📋",
    ],
}


def send_market_reminder(exchange_name, emoji, tz_str, tip_key):
    tips = TIPS_ZH.get(tip_key, ["市场即将开盘！"])
    tip = random.choice(tips)
    msg = (
        f"<b>{exchange_name} 市场即将开盘（10分钟后）</b>\n\n"
        f"{emoji} {tip}"
    )
    payload = {
        "chat_id": CHINESE_CID,
        "text": msg,
        "parse_mode": "HTML"
    }
    result = tg_api("sendMessage", payload)
    if result and result.get("ok"):
        log.info(f"  [提醒] {exchange_name} 开盘提醒发送成功")
    else:
        log.warning(f"  [提醒] {exchange_name} 开盘提醒发送失败")


def send_market_close_reminder():
    msg = (
        "<b>📊 本周交易即将结束</b>\n\n"
        "纽约市场将在10分钟后收盘。\n"
        "祝周末愉快！我们下周见 👋"
    )
    payload = {
        "chat_id": CHINESE_CID,
        "text": msg,
        "parse_mode": "HTML"
    }
    result = tg_api("sendMessage", payload)
    if result and result.get("ok"):
        log.info("  [提醒] 休市提醒发送成功")
    else:
        log.warning(f"  [提醒] 休市提醒发送失败")


def start_market_reminder():
    log.info("  [提醒] 市场提醒线程启动")
    MARKET_REMINDERS = [
        (6, 50, "惠灵顿 + 悉尼", "🇳🇿🇦🇺", "Australia/Sydney", [0]),
        (8, 50, "东京", "🇯🇵", "Asia/Tokyo", None),
        (7, 50, "伦敦", "🇬🇧", "Europe/London", None),
        (9, 20, "纽约", "🇺🇸", "US/Eastern", None),
    ]
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            for (lh, lm, name, emoji, tz_str, days_filter) in MARKET_REMINDERS:
                if days_filter is not None:
                    local_wd = get_local_weekday(tz_str)
                    if local_wd not in days_filter:
                        continue
                secs = seconds_to_next_utc(lh, lm, tz_str)
                if secs <= 60:
                    if "惠灵顿" in name or "Wellington" in name:
                        tip_key = "Wellington"
                    elif "东京" in name or "Tokyo" in name:
                        tip_key = "Tokyo"
                    elif "伦敦" in name or "London" in name:
                        tip_key = "London"
                    elif "纽约" in name or "New_York" in name:
                        tip_key = "New_York"
                    else:
                        tip_key = name
                    send_market_reminder(name, emoji, tz_str, tip_key)
                    time.sleep(secs + 3600)
                    continue

            local_wd = get_beijing_weekday()
            if local_wd == 4:
                secs_close = seconds_to_next_utc(15, 50, "US/Eastern")
                if secs_close <= 60:
                    send_market_close_reminder()
                    time.sleep(secs_close + 3600)

            time.sleep(60)
        except Exception as e:
            log.warning(f"  [提醒] 异常: {e}")
            time.sleep(60)


# ─── 每日欢迎消息 ─────────────────────────────────────────────────────────

def start_daily_welcome():
    log.info("  [欢迎] 每日欢迎消息线程启动")
    last_sent_date = None
    targets_today  = []

    def pick_random_targets():
        beijing_tz = pytz.timezone("Asia/Shanghai")
        now = datetime.now(beijing_tz)
        base1 = now.replace(hour=14, minute=0, second=0, microsecond=0)
        rand1 = random.randint(0, 4 * 60 - 1)
        t1 = base1 + timedelta(minutes=rand1)
        base2 = now.replace(hour=19, minute=0, second=0, microsecond=0)
        rand2 = random.randint(0, 4 * 60 - 1)
        t2 = base2 + timedelta(minutes=rand2)
        return [(t1, False), (t2, False)]

    while True:
        try:
            beijing_tz = pytz.timezone("Asia/Shanghai")
            now = datetime.now(beijing_tz)
            today_str = now.strftime("%Y-%m-%d")

            if today_str != last_sent_date:
                targets_today = pick_random_targets()
                last_sent_date = today_str
                log.info(f"  [欢迎] 今日推送时间: {[t[0].strftime('%H:%M') for t in targets_today]}")

            for i, (target_time, sent_flag) in enumerate(targets_today):
                if not sent_flag and now >= target_time:
                    msg = (
                        "🤖 欢迎来到Gold & Forex · 章鱼智投AI交易信号社区\n\n"
                        "🤖 AI行情预测 / AI XAUUSD & Forex Signals\n"
                        "· 入场点 / Entry\n"
                        "· 多空方向 BUY / SELL\n"
                        "· 压力位 & 支撑位 / Resistance & Support\n"
                        "· 止盈止损 / TP / SL\n\n"
                        "🔗 分享邀请链接，邀请好友注册\n"
                        "即可获得好友消费的 50% 返利奖励\n"
                        "https://app.octopus-vision.com/html/register.html?code=C0145\n\n"
                        "📲 APP下载填写邀请码 ZJ7236 领取38算力 + 6美金交易体验券\n\n"
                        "🤝 商务合作：@Luna_OctaTradeHK"
                    )

                    payload = {
                        "chat_id": CHINESE_CID,
                        "text": msg,
                        "parse_mode": "HTML",
                        "reply_markup": {
                            "inline_keyboard": [
                                [
                                    {"text": "📝 注册福利", "url": "https://app.octopus-vision.com/html/register.html?code=C0145"}
                                ],
                                [
                                    {"text": "📱 APP下载", "url": "https://www.octopus-vision.com/#download"}
                                ],
                                [
                                    {"text": "🤝 商务合作", "url": "https://t.me/Luna_OctaTradeHK"}
                                ]
                            ]
                        }
                    }

                    result = tg_api("sendMessage", payload)
                    if result and result.get("ok"):
                        log.info(f"  [欢迎] 消息发送成功 ({target_time.strftime('%H:%M')})")
                        targets_today[i] = (target_time, True)
                    else:
                        log.warning(f"  [欢迎] 消息发送失败: {result}")

            time.sleep(30)
        except Exception as e:
            log.warning(f"  [欢迎] 异常: {e}")
            time.sleep(30)


# ─── HTTP 保活服务器 ──────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status":    "ok",
            "channel":   "zh",
            "tp_monitor": len(active_signals),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }).encode())

    def log_message(self, format, *args):
        log.debug(f"  [HTTP] {format % args}")


def start_http_server(port=10000):
    try:
        port = int(os.environ.get("PORT", port))
    except:
        port = port
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    log.info(f"  [HTTP] 保活服务器已启动，端口: {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()


# ─── 自我保活 ──────────────────────────────────────────────────────────────

def keep_alive_self():
    log.info("  [保活] 自我保活线程启动")
    time.sleep(10)
    render_url = os.environ.get("RENDER_URL", "").strip()
    if not render_url:
        service_name = os.environ.get("RENDER_SERVICE_NAME", "forex-gold-ai-bot")
        render_url = f"https://{service_name}.onrender.com"
    log.info(f"  [保活] 目标 URL: {render_url}")
    headers = {"User-Agent": "Render-KeepAlive/1.0"}
    while True:
        try:
            time.sleep(300)
            r = requests.get(render_url, headers=headers, timeout=10)
            log.info(f"  [保活] ping {render_url} -> {r.status_code}")
        except Exception as e:
            log.warning(f"  [保活] ping失败: {e}")


# ─── 主函数 ────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("Gold & Forex · 章鱼智投 AI 信号 Bot v2.0 启动")
    log.info(f"  频道 ID: {CHINESE_CID}")
    log.info("=" * 60)

    me = tg_api("getMe")
    if not me or not me.get("ok"):
        log.error("  Bot Token 无效，退出")
        sys.exit(1)

    bot_username = me["result"]["username"]
    log.info(f"  Bot 用户名: @{bot_username}")

    import threading

    # 1. 信号推送线程
    t_signal = threading.Thread(target=start_signal_loop, daemon=True)
    t_signal.start()
    log.info("  [✓] 信号推送线程已启动")

    # 2. 止盈监控线程
    t_tp = threading.Thread(target=start_tp_monitor, daemon=True)
    t_tp.start()
    log.info("  [✓] 止盈监控线程已启动")

    # 3. 市场提醒线程
    t_reminder = threading.Thread(target=start_market_reminder, daemon=True)
    t_reminder.start()
    log.info("  [✓] 市场提醒线程已启动")

    # 4. 每日欢迎消息线程
    t_welcome = threading.Thread(target=start_daily_welcome, daemon=True)
    t_welcome.start()
    log.info("  [✓] 每日欢迎消息线程已启动")

    # 5. 自我保活线程
    t_keepalive = threading.Thread(target=keep_alive_self, daemon=True)
    t_keepalive.start()
    log.info("  [✓] 自我保活线程已启动")

    # 主线程：启动 HTTP 服务器
    start_http_server()


# ─── 信号推送循环 ──────────────────────────────────────────────────────────

def start_signal_loop():
    log.info("  [信号] 信号推送循环启动")
    last_signal_time = None

    while True:
        try:
            now = datetime.now(pytz.timezone("Asia/Shanghai"))
            weekday = now.weekday()
            should_send = False

            if weekday < 5:  # 工作日
                if now.minute == 5 and (last_signal_time is None or (now - last_signal_time).total_seconds() > 3000):
                    should_send = True
            else:  # 周末
                if now.minute == 5 and now.hour % 2 == 0 and (last_signal_time is None or (now - last_signal_time).total_seconds() > 3000):
                    should_send = True

            if should_send:
                send_signal_to_channel()
                last_signal_time = now

            time.sleep(60)

        except Exception as e:
            log.warning(f"  [信号] 异常: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
