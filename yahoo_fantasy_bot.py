"""
Yahoo Fantasy MLB Bot
- 每天抓取本季累積得分前10名球員 + 近兩天得分 + Free Agent
- 每週一推送週報（台灣時間上週二到本週一，共七天累積 TOP10）
- 產生圖卡發送到 Discord

[優化說明]
1. fetch_player_owner_map：單次請求 ;out=roster，原本 12+ 次 → 1 次
2. 近兩天 FA 合併：date 抓全員時同步判斷 FA，省去重複抓取
3. sleep 調降：0.5s/1.0s → 0.2s
4. 週報：抓上週二到本週一共七天逐日成績加總（含今天，用 status=T type=date）
"""

import os
import json
import time
import requests
from datetime import date, timedelta
from pathlib import Path

# ─────────────────────────────────────────────
# 計分規則
# ─────────────────────────────────────────────
BATTER_SCORING = {
    "R":    1.0,  "1B":   2.6,  "2B":   5.2,
    "3B":   7.8,  "HR":  10.4,  "RBI":  1.0,
    "SB":   3.5,  "CS":  -0.5,  "BB":   2.6,
    "HBP":  2.6,  "K":   -0.5,  "GIDP":-1.0,
}
PITCHER_SCORING = {
    "W":    3.0,  "SV":   6.0,  "OUT":  1.0,
    "H":   -1.3,  "ER":  -2.5,  "BB":  -1.3,
    "HBP": -1.3,  "K":    2.0,  "GIDP": 1.0,
    "HLD":  5.0,  "QS":   6.0,
}
BATTER_STAT_IDS = {
    "R":"7","1B":"9","2B":"10","3B":"11","HR":"12",
    "RBI":"13","SB":"16","CS":"17","BB":"18",
    "HBP":"20","K":"21","GIDP":"22",
}
PITCHER_STAT_IDS = {
    "W":"28","SV":"32","OUT":"33","H":"34","ER":"37",
    "BB":"39","HBP":"41","K":"42","HLD":"82","QS":"83","GIDP":"46",
}

# ─────────────────────────────────────────────
# 環境變數
# ─────────────────────────────────────────────
YAHOO_CLIENT_ID     = os.environ["YAHOO_CLIENT_ID"]
YAHOO_CLIENT_SECRET = os.environ["YAHOO_CLIENT_SECRET"]
YAHOO_REFRESH_TOKEN = os.environ["YAHOO_REFRESH_TOKEN"]
YAHOO_LEAGUE_ID     = os.environ["YAHOO_LEAGUE_ID"]
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
RANK_CACHE_FILE     = "rank_cache.json"
PITCHER_POS         = {"SP", "RP", "P"}
INVALID_STAT        = {"", "-", None, "-/-", "—", "N/A", "0"}

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
# API 抓取
# ─────────────────────────────────────────────
def yahoo_get(url, token):
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    return resp.json()

def fetch_all_players(token, stats_type, date_str=None):
    """抓取聯盟內所有 rostered 球員，支援 season / date 兩種模式"""
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
        time.sleep(0.2)
    return all_raw


def fetch_all_players_date(token, date_str):
    """
    抓取指定日期所有 active（rostered + FA）球員的當日成績。
    用 status=A 一次抓完，近兩天統計使用。
    """
    base = "https://fantasysports.yahooapis.com/fantasy/v2"
    all_raw = []
    start = 0
    page_size = 25
    while True:
        url = (f"{base}/league/{YAHOO_LEAGUE_ID}/players;status=A"
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
        if count < page_size:
            break
        start += page_size
        time.sleep(0.2)
    print(f"  {date_str} 抓取完畢，共 {len(all_raw)} 位")
    return all_raw


def fetch_rostered_players_date(token, date_str):
    """
    抓取指定日期所有 rostered（status=T）球員的當日成績。
    週報專用：status=T + type=date 才能抓到歷史日期的成績。
    """
    base = "https://fantasysports.yahooapis.com/fantasy/v2"
    all_raw = []
    start = 0
    page_size = 25
    while True:
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
        if count < page_size:
            break
        start += page_size
        time.sleep(0.2)
    print(f"  [週報] {date_str} 抓取完畢，共 {len(all_raw)} 位")
    return all_raw


def fetch_schedule(date_str) -> dict:
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        matchups = {}
        for game in data.get("dates", [{}])[0].get("games", []):
            away = game["teams"]["away"]["team"].get("abbreviation", "")
            home = game["teams"]["home"]["team"].get("abbreviation", "")
            if away and home:
                matchups[away] = f"vs {home}"
                matchups[home] = f"vs {away}"
        return matchups
    except Exception as e:
        print(f"[WARN] 賽程抓取失敗 {date_str}: {e}")
        return {}


def fetch_player_owner_map(token) -> dict:
    """單次請求取得全聯盟所有隊伍 + roster（原本 12+ 次 → 1 次）"""
    base = "https://fantasysports.yahooapis.com/fantasy/v2"
    owner_map = {}
    url = f"{base}/league/{YAHOO_LEAGUE_ID}/teams;out=roster?format=json"
    try:
        data = yahoo_get(url, token)
        teams_raw = data["fantasy_content"]["league"][1]["teams"]
        team_count = teams_raw["count"]
    except Exception as e:
        print(f"[WARN] 無法取得 roster: {e}")
        return owner_map

    print(f"  共 {team_count} 支隊伍，單次請求解析 roster...")
    for i in range(team_count):
        try:
            team_data = teams_raw[str(i)]["team"]
            team_info = team_data[0]
            team_name = next(
                (item["name"] for item in team_info
                 if isinstance(item, dict) and "name" in item), ""
            )
            roster_players = team_data[1]["roster"]["0"]["players"]
            p_count = roster_players["count"]
            for j in range(p_count):
                try:
                    pinfo = roster_players[str(j)]["player"][0]
                    name_obj = next(
                        (item["name"] for item in pinfo
                         if isinstance(item, dict) and "name" in item), None
                    )
                    if name_obj:
                        full_name = name_obj["full"]
                        mlb_team = next(
                            (item["editorial_team_abbr"] for item in pinfo
                             if isinstance(item, dict) and "editorial_team_abbr" in item), ""
                        )
                        owner_map[full_name] = team_name
                        owner_map[f"{full_name}|{mlb_team}"] = team_name
                except Exception:
                    pass
            print(f"    {team_name}: {p_count} 位球員")
        except Exception as e:
            print(f"[WARN] 隊伍 {i} 解析失敗: {e}")

    print(f"  owner_map 建立完成，共 {len(owner_map)} 位球員")
    return owner_map

# ─────────────────────────────────────────────
# 計分 / 解析
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

def get_field(info_list, key):
    for item in info_list:
        if isinstance(item, dict) and key in item:
            return item[key]
    return None

def parse_players(raw_list):
    players = []
    for entry in raw_list:
        try:
            player    = entry["player"]
            info      = player[0]
            stats_raw = player[1]["player_stats"]["stats"]
            name_obj  = get_field(info, "name")
            name      = name_obj["full"] if name_obj else "Unknown"
            team      = get_field(info, "editorial_team_abbr") or "N/A"
            position  = get_field(info, "display_position") or ""
            if not position:
                ep = get_field(info, "eligible_positions")
                if isinstance(ep, dict):
                    pos_vals = []
                    for v in ep.values():
                        if isinstance(v, dict):
                            p = v.get("position", "")
                            if p and p not in ("BN","DL","NA","IL"):
                                pos_vals.append(p)
                    position = ",".join(pos_vals)
            pos_set    = set(position.replace(",", " ").split())
            is_pitcher = bool(pos_set & PITCHER_POS)
            stats      = {s["stat"]["stat_id"]: s["stat"]["value"] for s in stats_raw}
            players.append({
                "name": name, "team": team, "position": position,
                "is_pitcher": is_pitcher,
                "score": calc_score(stats, is_pitcher),
                "stats": stats,
            })
        except Exception as e:
            print(f"[WARN] parse error: {e}")
    return players

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
# Discord 發送
# ─────────────────────────────────────────────
def send_discord_image(image_bytes, filename="card.png", content=""):
    resp = requests.post(
        DISCORD_WEBHOOK_URL,
        data={"content": content} if content else {},
        files={"file": (filename, image_bytes, "image/png")},
    )
    resp.raise_for_status()
    print(f"[OK] Discord 圖片推送成功 ({resp.status_code}) - {filename}")
    time.sleep(1)

# ─────────────────────────────────────────────
# 週報：上週二到本週一（含今天）七天逐日加總
# ─────────────────────────────────────────────
def fetch_weekly_top10(token, today, owner_map) -> list:
    """
    抓取上週二到本週一（含今天，共七天）每天的 rostered 球員成績加總。
    使用 status=T + type=date，這是 Yahoo API 歷史日期唯一穩定有資料的組合。
    回傳 TOP10 list。
    """
    weekly_scores = {}

    # delta=0 是今天（週一），delta=6 是上週二，共七天
    for delta in range(0, 7):
        day     = today - timedelta(days=delta)
        day_str = day.strftime("%Y-%m-%d")
        print(f"  [週報] 抓取 {day_str}...")

        raw         = fetch_rostered_players_date(token, day_str)
        players_day = parse_players(raw)

        day_count = 0
        for p in players_day:
            # 有任何非零 stat 就算有上場
            has_played = False
            if p["score"] != 0:
                has_played = True
            else:
                for v in p["stats"].values():
                    if v not in INVALID_STAT:
                        try:
                            if float(v) != 0:
                                has_played = True
                                break
                        except (ValueError, TypeError):
                            pass
            if not has_played:
                continue

            name = p["name"]
            if name not in weekly_scores:
                weekly_scores[name] = {
                    "name":        name,
                    "team":        p["team"],
                    "position":    p["position"],
                    "is_pitcher":  p["is_pitcher"],
                    "owner":       (owner_map.get(f"{name}|{p['team']}")
                                    or owner_map.get(name, "Free Agent")),
                    "score":       0.0,
                    "days_played": 0,
                }
            weekly_scores[name]["score"]       += p["score"]
            weekly_scores[name]["days_played"] += 1
            day_count += 1

        print(f"  [週報] {day_str} 有得分球員 {day_count} 位")

    result = sorted(weekly_scores.values(), key=lambda x: x["score"], reverse=True)
    print(f"  [週報] 七天加總，共 {len(result)} 位有得分球員")
    for i, p in enumerate(result[:10], 1):
        print(f"    {i:>2}. {p['name']:<22} {p['score']:>7.1f}  ({p['days_played']} 天)")
    return result[:10]

# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def main():
    from image_generator import (
        generate_season_top10, generate_today_top10,
        generate_today_bottom5, generate_free_agent_top5,
        generate_weekly_report,
    )

    today     = date.today()
    today_str = today.strftime("%Y/%m/%d")
    is_monday = today.weekday() == 0
    print(f"[{today_str}] 開始執行 Yahoo Fantasy MLB Bot... (週一={is_monday})")

    token = refresh_access_token()
    print("取得 Token 成功")

    # ── 本季累積 ──
    print("抓取本季累積數據...")
    season_raw  = fetch_all_players(token, "season")
    all_players = parse_players(season_raw)
    all_players.sort(key=lambda x: x["score"], reverse=True)
    season_top10 = all_players[:10]

    for i, p in enumerate(season_top10, 1):
        print(f"  {i:>2}. {p['name']:<22} {p['score']:>7.1f}  pos='{p['position']}'")

    season_rank_map = {p["name"]: i + 1 for i, p in enumerate(all_players)}
    prev_ranks      = load_prev_ranks()

    # ── 單次請求取得 Owner Map ──
    print("抓取各隊 roster 對應表（單次請求）...")
    owner_map = fetch_player_owner_map(token)

    for p in all_players:
        key = f"{p['name']}|{p['team']}"
        p["owner"] = owner_map.get(key) or owner_map.get(p["name"], "Free Agent")

    # ── 近兩天數據（rostered + FA 合併，只抓兩輪）──
    print("抓取近兩天數據...")
    two_day_scores = {}
    two_day_opps   = {}
    fa_scores      = {}

    for delta in [1, 2]:
        day      = today - timedelta(days=delta)
        day_str  = day.strftime("%Y-%m-%d")
        schedule = fetch_schedule(day_str)
        raw      = fetch_all_players_date(token, day_str)
        players_day = parse_players(raw)

        for p in players_day:
            if p["score"] == 0:
                continue
            name  = p["name"]
            key   = f"{name}|{p['team']}"
            owner = owner_map.get(key) or owner_map.get(name, "Free Agent")

            if name not in two_day_scores:
                two_day_scores[name] = {
                    "name":        name,
                    "team":        p["team"],
                    "position":    p["position"],
                    "is_pitcher":  p["is_pitcher"],
                    "owner":       owner,
                    "score":       0.0,
                    "season_rank": season_rank_map.get(name, 0),
                    "rank_change": (prev_ranks.get(name, 0) - season_rank_map.get(name, 0))
                                   if prev_ranks.get(name, 0) > 0 else 0,
                }
                two_day_opps[name] = []
            two_day_scores[name]["score"] += p["score"]

            opp = schedule.get(p["team"], "")
            if opp and opp not in two_day_opps[name]:
                two_day_opps[name].append(opp)

            if owner == "Free Agent":
                if name not in fa_scores:
                    fa_scores[name] = {
                        "name":       name,
                        "team":       p["team"],
                        "position":   p["position"],
                        "is_pitcher": p["is_pitcher"],
                        "owner":      "Free Agent",
                        "score":      0.0,
                    }
                fa_scores[name]["score"] += p["score"]

        print(f"  {day_str} 抓取完畢")

    for name, p in two_day_scores.items():
        opps = two_day_opps.get(name, [])
        p["opponent"] = "  ·  ".join(opps) if opps else ""

    played        = sorted(two_day_scores.values(), key=lambda x: x["score"], reverse=True)
    today_top10   = played[:10]
    today_bottom5 = sorted(two_day_scores.values(), key=lambda x: x["score"])[:5]
    fa_list       = sorted(fa_scores.values(), key=lambda x: x["score"], reverse=True)
    fa_top5       = fa_list[:5]

    print(f"  近兩天有得分球員共 {len(played)} 位")
    print(f"  近兩天有得分 FA={len(fa_list)}")

    # ── 產生圖卡並發送 ──
    print("產生圖卡並推送到 Discord...")

    img = generate_season_top10(season_top10, prev_ranks, today_str)
    send_discord_image(img, "season_top10.png")

    if today_top10:
        img = generate_today_top10(today_top10, today_str)
        send_discord_image(img, "today_top10.png")

    if today_bottom5:
        img = generate_today_bottom5(today_bottom5, today_str)
        send_discord_image(img, "today_bottom5.png")

    if fa_top5:
        img = generate_free_agent_top5(fa_top5, today_str)
        send_discord_image(img, "free_agent_top5.png")

    # ── 週報（週一才發）──
    # 範圍：上週二到本週一（含今天），共七天
    if is_monday:
        print("今天是週一，抓取過去七天成績產生週報...")
        weekly_top10 = fetch_weekly_top10(token, today, owner_map)

        last_tue   = today - timedelta(days=6)   # 上週二
        week_label = f"{last_tue.strftime('%m/%d')} – {today.strftime('%m/%d')}"

        if weekly_top10:
            img = generate_weekly_report(weekly_top10, week_label)
            send_discord_image(img, "weekly_report.png")
        else:
            print("[WARN] 週報資料為空，跳過發送")

    # ── 儲存排名快取 ──
    new_ranks = {p["name"]: i + 1 for i, p in enumerate(all_players)}
    save_ranks(new_ranks)
    print("完成！")


if __name__ == "__main__":
    main()
