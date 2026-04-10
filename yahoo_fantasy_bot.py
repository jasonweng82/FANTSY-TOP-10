"""
Yahoo Fantasy MLB Bot
- 每天抓取本季累積得分前10名球員
- 比較與前一天排名變化
- 今日上場球員得分最高前10名 & 最低5名
- 推送到 Discord
"""

import os
import json
import time
import requests
from datetime import datetime, date
from pathlib import Path

# ─────────────────────────────────────────────
# 你的聯盟計分規則
# ─────────────────────────────────────────────
BATTER_SCORING = {
    "R":    1.0,    # Runs
    "1B":   2.6,    # Singles
    "2B":   5.2,    # Doubles
    "3B":   7.8,    # Triples
    "HR":  10.4,    # Home Runs
    "RBI":  1.0,    # Runs Batted In
    "SB":   3.5,    # Stolen Bases
    "CS":  -0.5,    # Caught Stealing
    "BB":   2.6,    # Walks
    "HBP":  2.6,    # Hit By Pitch
    "K":   -0.5,    # Strikeouts (batter)
    "GIDP":-1.0,    # Ground Into Double Play
}

PITCHER_SCORING = {
    "W":    3.0,    # Wins
    "SV":   6.0,    # Saves
    "OUT":  1.0,    # Outs (每個出局數)
    "H":   -1.3,    # Hits allowed
    "ER":  -2.5,    # Earned Runs
    "BB":  -1.3,    # Walks
    "HBP": -1.3,    # Hit Batters
    "K":    2.0,    # Strikeouts (pitcher)
    "GIDP": 1.0,    # Batters Grounded Into Double Plays
    "HLD":  5.0,    # Holds
    "QS":   6.0,    # Quality Starts
}

# Yahoo Fantasy stat ID mapping (MLB)
# https://developer.yahoo.com/fantasysports/guide/
BATTER_STAT_IDS = {
    "R":    "7",    # Runs           confirmed
    "1B":   "9",    # Singles        confirmed (fixed from 14)
    "2B":   "10",   # Doubles        confirmed (fixed from 9)
    "3B":   "11",   # Triples        confirmed (fixed from 10)
    "HR":   "12",   # Home Runs      confirmed (fixed from 11)
    "RBI":  "13",   # RBI            confirmed
    "SB":   "16",   # Stolen Bases   confirmed
    "CS":   "17",   # Caught Stealing
    "BB":   "18",   # Walks          confirmed
    "HBP":  "20",   # Hit By Pitch   (guessed, was 21)
    "K":    "21",   # Strikeouts     confirmed (fixed from 25)
    "GIDP": "22",   # GIDP confirmed (fixed from 23)
}

PITCHER_STAT_IDS = {
    "W":    "28",   # Wins          confirmed
    "SV":   "32",   # Saves
    "OUT":  "33",   # Outs pitched  confirmed 
    "H":    "34",   # Hits allowed  confirmed
    "ER":   "37",   # Earned Runs   confirmed
    "BB":   "39",   # Walks         confirmed 
    "HBP":  "41",   # Hit Batters   confirmed
    "K":    "42",   # Strikeouts    confirmed 
    "HLD":  "82",   # Holds         confirmed 
    "QS":   "83",   # Quality Start 
    "GIDP": "46",   # GIDP confirmed
}

# ─────────────────────────────────────────────
# Yahoo OAuth 設定 (從環境變數讀取)
# ─────────────────────────────────────────────
YAHOO_CLIENT_ID     = os.environ["YAHOO_CLIENT_ID"]
YAHOO_CLIENT_SECRET = os.environ["YAHOO_CLIENT_SECRET"]
YAHOO_REFRESH_TOKEN = os.environ["YAHOO_REFRESH_TOKEN"]
YAHOO_LEAGUE_ID     = os.environ["YAHOO_LEAGUE_ID"]   # e.g. "mlb.l.123456"
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

# 暫存排名的 JSON 檔（GitHub Actions artifact 或你自己保留）
RANK_CACHE_FILE = "rank_cache.json"

# ─────────────────────────────────────────────
# OAuth
# ─────────────────────────────────────────────
def refresh_access_token():
    resp = requests.post(
        "https://api.login.yahoo.com/oauth2/get_token",
        data={"grant_type": "refresh_token", "refresh_token": YAHOO_REFRESH_TOKEN},
        auth=(YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]
 
# ─────────────────────────────────────────────
# API 抓取（分頁）
# ─────────────────────────────────────────────
def yahoo_get(url, token):
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    return resp.json()
 
def fetch_all_players(token, stats_type, date_str=None):
    base = "https://fantasysports.yahooapis.com/fantasy/v2"
    all_raw = []
    start = 0
    page_size = 25
 
    while True:
        if stats_type == "season":
            url = (f"{base}/league/{YAHOO_LEAGUE_ID}/players;status=T"
                   f";start={start};count={page_size}"
                   f"/stats;type=season?format=json")
        else:
            url = (f"{base}/league/{YAHOO_LEAGUE_ID}/players;status=T"
                   f";start={start};count={page_size}"
                   f"/stats;type=date;date={date_str}?format=json")
 
        data = yahoo_get(url, token)
        try:
            player_list = data["fantasy_content"]["league"][1]["players"]
            count = player_list.get("count", 0)
        except Exception:
            break
 
        if count == 0:
            break
 
        for i in range(count):
            entry = player_list.get(str(i))
            if entry:
                all_raw.append(entry)
 
        print(f"  已抓取 {start + count} 位球員...")
        if count < page_size:
            break
        start += page_size
        time.sleep(0.5)
 
    return all_raw
 
# ─────────────────────────────────────────────
# 計分
# ─────────────────────────────────────────────
def calc_score(stats, is_pitcher):
    scoring  = PITCHER_SCORING  if is_pitcher else BATTER_SCORING
    stat_ids = PITCHER_STAT_IDS if is_pitcher else BATTER_STAT_IDS
    total = 0.0
    for stat_name, pts in scoring.items():
        sid = stat_ids.get(stat_name)
        if sid and sid in stats:
            v = stats[sid]
            if v in INVALID_STAT:
                continue
            try:
                total += float(v) * pts
            except (ValueError, TypeError):
                pass
    return round(total, 2)
 
# ─────────────────────────────────────────────
# 解析球員
# ─────────────────────────────────────────────
def get_field(info_list, key):
    for item in info_list:
        if isinstance(item, dict) and key in item:
            return item[key]
    return None
 
def parse_players(raw_list):
    players = []
    for entry in raw_list:
        try:
            player   = entry["player"]
            info     = player[0]
            stats_raw = player[1]["player_stats"]["stats"]
 
            # 名字
            name_obj = get_field(info, "name")
            name = name_obj["full"] if name_obj else "Unknown"
 
            # 隊伍
            team = get_field(info, "editorial_team_abbr") or "N/A"
 
            # 守位：先找 display_position
            position = get_field(info, "display_position") or ""
            if not position:
                ep = get_field(info, "eligible_positions")
                if isinstance(ep, dict):
                    pos_vals = []
                    for v in ep.values():
                        if isinstance(v, dict):
                            p = v.get("position", "")
                            if p and p not in ("BN", "DL", "NA", "IL"):
                                pos_vals.append(p)
                    position = ",".join(pos_vals)
 
            # 投打判斷
            pos_set    = set(position.replace(",", " ").split())
            is_pitcher = bool(pos_set & PITCHER_POS)
 
            # Stats
            stats = {s["stat"]["stat_id"]: s["stat"]["value"] for s in stats_raw}
 
            players.append({
                "name":       name,
                "team":       team,
                "position":   position,
                "is_pitcher": is_pitcher,
                "score":      calc_score(stats, is_pitcher),
                "stats":      stats,
            })
        except Exception as e:
            print(f"[WARN] parse error: {e}")
    return players
 
# ─────────────────────────────────────────────
# 今日上場過濾
# ─────────────────────────────────────────────
def played_today_filter(players):
    result = []
    for p in players:
        if p["score"] != 0:
            result.append(p)
            continue
        for v in p["stats"].values():
            if v not in INVALID_STAT:
                try:
                    if float(v) != 0:
                        result.append(p)
                        break
                except (ValueError, TypeError):
                    pass
    return result
 
# ─────────────────────────────────────────────
# 排名快取
# ─────────────────────────────────────────────
def load_prev_ranks():
    if Path(RANK_CACHE_FILE).exists():
        with open(RANK_CACHE_FILE) as f:
            return json.load(f)
    return {}
 
def save_ranks(ranks):
    with open(RANK_CACHE_FILE, "w") as f:
        json.dump(ranks, f, ensure_ascii=False, indent=2)
 
# ─────────────────────────────────────────────
# Discord 格式
# ─────────────────────────────────────────────
def rank_arrow(diff):
    if diff > 0: return f"🟢▲{diff}"
    if diff < 0: return f"🔴▼{abs(diff)}"
    return "⚪–"
 
def fmt_line(i, name, score, pos, change=""):
    pos_str = pos if pos else "??"
    return f"`{i:>2}.` `{name:<18}` `{score:>7.1f}` **{pos_str}** {change}".rstrip()
 
def build_discord_message(season_top10, prev_ranks, today_top10, today_bottom5, today_date):
    embeds = []
 
    # 本季 TOP10
    lines = []
    for i, p in enumerate(season_top10, 1):
        prev   = prev_ranks.get(p["name"])
        change = "🆕" if prev is None else rank_arrow(prev - i)
        lines.append(fmt_line(i, p["name"], p["score"], p["position"], change))
    embeds.append({
        "title":       f"📊 本季 TOP10 ｜ {today_date}",
        "description": "\n".join(lines),
        "color":       0x1E90FF,
        "footer":      {"text": "Yahoo Fantasy MLB • 每日自動更新"},
    })
 
    # 今日 TOP10
    if today_top10:
        lines = [fmt_line(i, p["name"], p["score"], p["position"])
                 for i, p in enumerate(today_top10, 1)]
        embeds.append({
            "title":       "🔥 今日得分 TOP10",
            "description": "\n".join(lines),
            "color":       0xFFA500,
        })
 
    # 今日 BOTTOM5
    if today_bottom5:
        lines = [fmt_line(i, p["name"], p["score"], p["position"])
                 for i, p in enumerate(today_bottom5, 1)]
        embeds.append({
            "title":       "🥶 今日得分 BOTTOM5",
            "description": "\n".join(lines),
            "color":       0xFF4444,
        })
 
    return embeds
 
def send_discord(embeds):
    resp = requests.post(DISCORD_WEBHOOK_URL, json={"embeds": embeds})
    resp.raise_for_status()
    print(f"[OK] Discord 推送成功 ({resp.status_code})")
 
# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def main():
    today_str = date.today().strftime("%Y/%m/%d")
    print(f"[{today_str}] 開始執行 Yahoo Fantasy MLB Bot...")
 
    token = refresh_access_token()
    print("取得 Token 成功")
 
    # 本季累積
    print("抓取本季累積數據...")
    season_raw  = fetch_all_players(token, "season")
    all_players = parse_players(season_raw)
    all_players.sort(key=lambda x: x["score"], reverse=True)
    season_top10 = all_players[:10]
 
    # 印出前10名（確認守位）
    for i, p in enumerate(season_top10, 1):
        print(f"  {i:>2}. {p['name']:<22} {p['score']:>7.1f}  pos='{p['position']}'")
 
    # 今日數據
    print("抓取今日數據...")
    today_raw    = fetch_all_players(token, "date", date.today().strftime("%Y-%m-%d"))
    today_players = parse_players(today_raw)
    played       = played_today_filter(today_players)
    played.sort(key=lambda x: x["score"], reverse=True)
    today_top10   = played[:10]
    today_bottom5 = sorted(played, key=lambda x: x["score"])[:5]
 
    # 排名比較
    prev_ranks = load_prev_ranks()
    new_ranks  = {p["name"]: i + 1 for i, p in enumerate(season_top10)}
 
    # Discord
    print("推送到 Discord...")
    embeds = build_discord_message(season_top10, prev_ranks, today_top10, today_bottom5, today_str)
    send_discord(embeds)
 
    save_ranks(new_ranks)
    print("完成！排名快取已更新。")
 
 
if __name__ == "__main__":
    main()
