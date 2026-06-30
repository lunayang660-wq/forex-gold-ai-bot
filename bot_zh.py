#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot/bot_zh.py — Octopus Smart TG Bot (中文频道版)
# 版本: v1.2 | 2026-06-15 | 频道: @OctopusAITrader_ZH
# 功能：信号推送(中文) + 市场开盘/休市提醒(中文) + 每日欢迎消息(中文) + HTTP保活

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

BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "8951847612:AAGYXG5YvLkjzSLGfJVeF6uPRT_B1E2eXHU")
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
    """调用 Octopus API 获取信号数据（与 bot.py 保持一致）"""
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


def get_beijing_weekday():
    """返回北京时间星期几 (0=周一, 6=周日)"""
    beijing_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(beijing_tz)
    return now.weekday()


def get_local_weekday(tz_str):
    """返回指定时区的星期几 (0=周一, 6=周日)"""
    try:
        tz = pytz.timezone(tz_str)
        now = datetime.now(tz)
        return now.weekday()
    except:
        return get_beijing_weekday()


def seconds_to_next_utc(target_hour_local, target_minute_local, tz_str="Asia/Shanghai"):
    """计算到下一个目标本地时间的UTC秒数"""
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

# 品种名中文映射（API 目前只返回英文名）
SYMBOL_NAMES_ZH = {
    "XAUUSD": "黃金",
    "BTCUSDT": "比特幣",
    "XAGUSD": "白銀",
    "USOUSD": "原油",
    "ETHUSDT": "以太坊",
    "EURUSD": "歐元美元",
    "GBPUSD": "英鎊美元",
    "USDJPY": "美元日圓",
}

def build_signal_message(symbol="XAUUSD"):
    data = fetch_octopus(symbol)
    if not data:
        if symbol == "XAUUSD":
            log.info(f"  {symbol} 无数据，尝试 BTCUSDT")
            return build_signal_message("BTCUSDT")
        return None
    try:
        direction    = data.get("direction", "NEUTRAL").upper()
        prob        = int(data.get("directionProbability", 0))
        support_p   = data.get("supportPrice", "N/A")
        resist_p    = data.get("resistancePrice", "N/A")
        target_p    = data.get("targetPrice", "N/A")
        change_r    = data.get("changeRate", "")
        period      = data.get("updatePeriod", "1H")
        # 品种名：API 对 zh-TW 请求直接返回中文字符串（如 "黃金"）
        name_raw = data.get("name", symbol)
        sym_name = str(name_raw).strip() or SYMBOL_NAMES_ZH.get(symbol, symbol)
        # AI 分析：API 直接返回中文（如 "背靠$4034.77支撑轻仓做多..."）
        suggestion_raw = data.get("suggestion", "")
        ai_text = str(suggestion_raw).strip()
        
        # 方向判断
        if direction == "UP":
            emoji, arrow, dir_text = "🔵", "⬆️", "\u505a\u591a"
        elif direction == "DOWN":
            emoji, arrow, dir_text = "🔴", "⬇️", "\u505a\u7a7a"
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
        
        return "\n".join(lines)
    except Exception as e:
        log.warning(f"  构造消息失败: {e}")
        return None


def send_signal_to_channel():
    log.info("  [信号] 开始推送...")
    msg = build_signal_message("XAUUSD")
    if not msg:
        log.warning("  [信号] 无数据，跳过")
        return
    
    payload = {
        "chat_id": CHINESE_CID,
        "text": msg,
        "parse_mode": "HTML",
        # 信号消息不带按钮，纯文字推送
    }

    result = tg_api("sendMessage", payload)
    if result and result.get("ok"):
        log.info("  [信号] 推送成功")
    else:
        log.warning(f"  [信号] 推送失败: {result}")


# ─── 市场提醒 ─────────────────────────────────────────────────────────────

# 温馨语池（中文版）
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
    """发送市场开盘提醒（中文版）"""
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
    """发送市场休市提醒（周五）"""
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
    """后台线程 — 市场开盘/休市提醒（中文版）"""
    log.info("  [提醒] 市场提醒线程启动")
    
    # 提醒配置：(本地时区小时, 本地时区分钟, 交易所名称, emoji, 时区, 星期几过滤)
    # 星期几：0=周一, 1=周二, ..., 4=周五, 5=周六, 6=周日
    MARKET_REMINDERS = [
        # 周一：Wellington + Sydney 合并提醒
        (6, 50, "惠灵顿 + 悉尼", "🇳🇿🇦🇺", "Australia/Sydney", [0]),
        # 亚洲主力时段
        (8, 50, "东京", "🇯🇵", "Asia/Tokyo", None),
        # 欧洲盘（伦敦 08:00 开盘，提前 10 分钟提醒）
        (7, 50, "伦敦", "🇬🇧", "Europe/London", None),
        # 美盘（纽约 09:30 开盘，提前 10 分钟提醒）
        (9, 20, "纽约", "🇺🇸", "US/Eastern", None),
    ]
    
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            
            for (lh, lm, name, emoji, tz_str, days_filter) in MARKET_REMINDERS:
                # 检查星期几（使用当地时区）
                if days_filter is not None:
                    local_wd = get_local_weekday(tz_str)
                    if local_wd not in days_filter:
                        continue
                
                # 计算下次提醒时间
                secs = seconds_to_next_utc(lh, lm, tz_str)
                
                # 如果距离下次提醒小于60秒，发送提醒
                if secs <= 60:
                    # 确定 tip_key
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
                    
                    # 跳过今天剩余时间
                    time.sleep(secs + 3600)
                    continue
            
            # 检查周五休市提醒（纽约时间15:50 = 北京时间03:50）
            local_wd = get_beijing_weekday()
            if local_wd == 4:  # 周五
                secs_close = seconds_to_next_utc(15, 50, "US/Eastern")
                if secs_close <= 60:
                    send_market_close_reminder()
                    time.sleep(secs_close + 3600)
            
            # 每分钟检查一次
            time.sleep(60)
            
        except Exception as e:
            log.warning(f"  [提醒] 异常: {e}")
            time.sleep(60)


# ─── 每日欢迎消息 ─────────────────────────────────────────────────────────

def start_daily_welcome():
    """后台线程 — 每天 14:00–18:00 和 19:00–23:00 CST 各随机发一次欢迎消息（中文版）"""
    log.info("  [欢迎] 每日欢迎消息线程启动")
    
    last_sent_date = None
    targets_today  = []  # [(datetime, sent_flag), ...]
    
    def pick_random_targets():
        """生成本次的随机时间点"""
        beijing_tz = pytz.timezone("Asia/Shanghai")
        now = datetime.now(beijing_tz)
        
        # 第一档：14:00–18:00
        base1 = now.replace(hour=14, minute=0, second=0, microsecond=0)
        rand1 = random.randint(0, 4 * 60 - 1)
        t1 = base1 + timedelta(minutes=rand1)
        
        # 第二档：19:00–23:00
        base2 = now.replace(hour=19, minute=0, second=0, microsecond=0)
        rand2 = random.randint(0, 4 * 60 - 1)
        t2 = base2 + timedelta(minutes=rand2)
        
        return [(t1, False), (t2, False)]
    
    while True:
        try:
            beijing_tz = pytz.timezone("Asia/Shanghai")
            now = datetime.now(beijing_tz)
            today_str = now.strftime("%Y-%m-%d")
            
            # 新的一天，重新生成目标时间
            if today_str != last_sent_date:
                targets_today = pick_random_targets()
                last_sent_date = today_str
                log.info(f"  [欢迎] 今日推送时间: {[t[0].strftime('%H:%M') for t in targets_today]}")
            
            # 检查是否到了发送时间
            for i, (target_time, sent_flag) in enumerate(targets_today):
                if not sent_flag and now >= target_time:
                    # 发送欢迎消息（中文版）
                    msg = (
                        "🤖 欢迎来到Gold & Forex · 章鱼智投AI交易信号社区\n\n"
                    "🤖 AI行情预测 / AI XAUUSD & Forex Signals\n"
                    "· 入场点 / Entry\n"
                        "· 多空方向 BUY / SELL\n"
                        "· 压力位 \u0026 支撑位 / Resistance \u0026 Support\n"
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
            
            # 每30秒检查一次
            time.sleep(30)
            
        except Exception as e:
            log.warning(f"  [欢迎] 异常: {e}")
            time.sleep(30)


# ─── HTTP 保活服务器 ──────────────────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    """Render 健康检查接口 — 返回 200 OK"""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "channel": "zh",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }).encode())

    def log_message(self, format, *args):
        log.debug(f"  [HTTP] {format % args}")


def start_http_server(port=10000):
    """启动 HTTP 保活服务器（主线程阻塞运行）"""
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


# ─── 主函数 ────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 60)
    log.info("Octopus Smart TG Bot (中文频道版) v1.1 启动")
    log.info(f"  中文频道 ID: {CHINESE_CID}")
    log.info("=" * 60)

    # 测试 Bot Token
    me = tg_api("getMe")
    if not me or not me.get("ok"):
        log.error("  Bot Token 无效，退出")
        sys.exit(1)

    bot_username = me["result"]["username"]
    log.info(f"  Bot 用户名: @{bot_username}")

    # 启动后台线程（全部 daemon）
    import threading

    # 1. 信号推送线程
    t_signal = threading.Thread(target=start_signal_loop, daemon=True)
    t_signal.start()
    log.info("  [✓] 信号推送线程已启动")

    # 2. 市场提醒线程
    t_reminder = threading.Thread(target=start_market_reminder, daemon=True)
    t_reminder.start()
    log.info("  [✓] 市场提醒线程已启动")

    # 3. 每日欢迎消息线程
    t_welcome = threading.Thread(target=start_daily_welcome, daemon=True)
    t_welcome.start()
    log.info("  [✓] 每日欢迎消息线程已启动")

    # 4. 自我保活线程（ping 自己的 HTTP 端口）
    t_keepalive = threading.Thread(target=keep_alive_self, daemon=True)
    t_keepalive.start()
    log.info("  [✓] 自我保活线程已启动")

    # 主线程：启动 HTTP 服务器（阻塞，Render 需要这个端口存活检测）
    start_http_server()


# ─── 信号推送循环（独立线程） ────────────────────────────────────────────

def start_signal_loop():
    """后台线程 — 定时推送信号"""
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


# ─── 自我保活 ──────────────────────────────────────────────────────────────

def keep_alive_self():
    """后台线程 — 每5分钟 ping 自己的外部 Render URL，防止免费版休眠"""
    log.info("  [保活] 自我保活线程启动")
    time.sleep(10)
    
    # Render 免费版需要外部 HTTP 请求才能保持唤醒
    # 用 RENDER_URL（手动设置）或构造默认 URL
    render_url = os.environ.get("RENDER_URL", "").strip()
    if not render_url:
        #  fallback：尝试从服务名构造（Render 服务名.onrender.com）
        service_name = os.environ.get("RENDER_SERVICE_NAME", "octatrade-tg-bot-zh")
        render_url = f"https://{service_name}.onrender.com"
    
    log.info(f"  [保活] 目标 URL: {render_url}")
    headers = {"User-Agent": "Render-KeepAlive/1.0"}
    while True:
        try:
            time.sleep(300)  # 5分钟
            r = requests.get(render_url, headers=headers, timeout=10)
            log.info(f"  [保活] ping {render_url} -> {r.status_code}")
        except Exception as e:
            log.warning(f"  [保活] ping失败: {e}")


if __name__ == "__main__":
    main()
