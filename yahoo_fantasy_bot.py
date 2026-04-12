"""
Yahoo Fantasy MLB Bot
- 每天抓取本季累積得分前10名球員 + 今日得分 + Free Agent
- 每週一推送週報
- 產生圖卡發送到 Discord
"""

import os
import json
import time
import requests
from datetime import date
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
DISCORD_WEBHOOK_URL  = os.environ["DISCORD_WEBHOOK_URL"]
GEMINI_API_KEY       = os.environ.get("GEMINI_API_KEY", "")
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

def fetch_fa_players(token):
    """
    抓取聯盟內的 Free Agent 球員（status=FA）
    只會回傳本聯盟 waivers/FA 的球員，不會抓全MLB
    """
    base = "https://fantasysports.yahooapis.com/fantasy/v2"
    all_raw = []
    start = 0
    page_size = 25
    while True:
        url = (f"{base}/league/{YAHOO_LEAGUE_ID}/players;status=FA"
               f";start={start};count={page_size}"
               f"/stats;type=season?format=json")
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
        print(f"  FA 已抓取 {start + count} 位...")
        if count < page_size:
            break
        start += page_size
        time.sleep(0.3)
    return all_raw


def fetch_schedule(date_str) -> dict:
    """
    抓取指定日期 MLB 賽程
    回傳 {隊伍縮寫: 對手縮寫}，例如 {"HOU": "LAD", "LAD": "HOU"}
    """
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


def fetch_fa_players_date(token, date_str):
    """
    抓取指定日期所有 FA 球員的當日成績
    分頁抓取，不限筆數
    """
    base = "https://fantasysports.yahooapis.com/fantasy/v2"
    all_raw = []
    start = 0
    page_size = 25
    while True:
        url = (f"{base}/league/{YAHOO_LEAGUE_ID}/players;status=FA"
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
        time.sleep(0.3)
    print(f"    {date_str} FA 抓取完畢，共 {len(all_raw)} 位")
    return all_raw


def fetch_all_players_with_ownership(token):
    """抓取球員含 ownership 資訊（判斷 FA）"""
    base = "https://fantasysports.yahooapis.com/fantasy/v2"
    all_raw = []
    start = 0
    page_size = 25
    while True:
        url = (f"{base}/league/{YAHOO_LEAGUE_ID}/players;status=A"
               f";start={start};count={page_size}"
               f"/stats;type=season?format=json")
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
        print(f"  FA 已抓取 {start + count} 位...")
        if count < page_size:
            break
        start += page_size
        time.sleep(0.5)
    return all_raw


def fetch_player_owner_map(token) -> dict:
    """
    回傳 {球員名字: 隊伍名稱} 的對應表
    透過抓每支隊伍的 roster 來建立
    """
    base = "https://fantasysports.yahooapis.com/fantasy/v2"
    owner_map = {}

    # 先取得所有隊伍
    teams_url = f"{base}/league/{YAHOO_LEAGUE_ID}/teams?format=json"
    data = yahoo_get(teams_url, token)
    try:
        teams_raw = data["fantasy_content"]["league"][1]["teams"]
        team_count = teams_raw["count"]
    except Exception as e:
        print(f"[WARN] 無法取得隊伍列表: {e}")
        return owner_map

    print(f"  共 {team_count} 支隊伍，抓取各隊 roster...")

    for i in range(team_count):
        try:
            team_data  = teams_raw[str(i)]["team"]
            team_info  = team_data[0]
            # 取隊伍名稱
            team_name  = ""
            for item in team_info:
                if isinstance(item, dict) and "name" in item:
                    team_name = item["name"]
                    break

            # 取 team_key
            team_key = ""
            for item in team_info:
                if isinstance(item, dict) and "team_key" in item:
                    team_key = item["team_key"]
                    break

            if not team_key:
                continue

            # 抓該隊 roster
            roster_url = f"{base}/team/{team_key}/roster?format=json"
            rdata = yahoo_get(roster_url, token)
            players_raw = rdata["fantasy_content"]["team"][1]["roster"]["0"]["players"]
            p_count = players_raw["count"]

            for j in range(p_count):
                try:
                    pinfo = players_raw[str(j)]["player"][0]
                    name_obj = None
                    for item in pinfo:
                        if isinstance(item, dict) and "name" in item:
                            name_obj = item["name"]
                            break
                    if name_obj:
                        full_name = name_obj["full"]
                        # 取該球員的 MLB 隊伍縮寫
                        mlb_team = ""
                        for itm in pinfo:
                            if isinstance(itm, dict) and "editorial_team_abbr" in itm:
                                mlb_team = itm["editorial_team_abbr"]
                                break
                        # 用 name+team 當 key 避免同名問題
                        owner_map[full_name] = team_name
                        owner_map[f"{full_name}|{mlb_team}"] = team_name
                except Exception:
                    pass

            print(f"    {team_name}: {p_count} 位球員")
            time.sleep(0.3)

        except Exception as e:
            print(f"[WARN] 隊伍 {i} roster 抓取失敗: {e}")

    print(f"  owner_map 建立完成，共 {len(owner_map)} 位球員")
    return owner_map

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
# 今日上場過濾
# ─────────────────────────────────────────────
def played_today_filter(players):
    result = []
    for p in players:
        if p["score"] != 0:
            result.append(p); continue
        for v in p["stats"].values():
            if v not in INVALID_STAT:
                try:
                    if float(v) != 0:
                        result.append(p); break
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
# MVP 點評（Claude API）
# ─────────────────────────────────────────────
def generate_mvp_comment(mvp: dict, bottom: dict) -> str:
    """
    呼叫 Gemini API 產生近兩天 MVP 趣味點評
    """
    if not GEMINI_API_KEY:
        return ""

    mvp_name  = mvp["name"]
    mvp_score = mvp["score"]
    mvp_pos   = mvp["position"]
    mvp_team  = mvp["team"]
    mvp_owner = mvp.get("owner", "某位玩家")
    bot_name  = bottom["name"]
    bot_score = bottom["score"]
    bot_owner = bottom.get("owner", "某位玩家")

    prompt = (
        f"你是一個 Yahoo Fantasy MLB 聯盟的趣味播報員，用繁體中文寫一段簡短點評（60字以內）。\n\n"
        f"近兩天表現最佳球員：{mvp_name}（{mvp_pos}，{mvp_team}），得{mvp_score:.1f}分，屬於玩家「{mvp_owner}」\n"
        f"近兩天表現最差球員：{bot_name}，得{bot_score:.1f}分，屬於玩家「{bot_owner}」\n\n"
        f"請寫一段幽默、帶點嘲諷但不失禮的點評，可以稱讚MVP也可以酸一下墊底球員的主人。"
        f"語氣輕鬆像朋友聊天。直接給點評內容，不要加任何前綴。"
    )

    try:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        )
        resp = requests.post(
            url,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        resp.raise_for_status()
        comment = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"  MVP 點評: {comment}")
        return comment
    except Exception as e:
        print(f"[WARN] MVP 點評失敗: {e}")
        return ""


def send_discord_text(text: str):
    """發送純文字訊息到 Discord"""
    resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": text})
    resp.raise_for_status()
    print(f"[OK] Discord 文字推送成功 ({resp.status_code})")
    time.sleep(1)


# ─────────────────────────────────────────────
# Discord 發送（只發圖片）
# ─────────────────────────────────────────────
def send_discord_image(image_bytes, filename="card.png", content=""):
    resp = requests.post(
        DISCORD_WEBHOOK_URL,
        data={"content": content} if content else {},
        files={"file": (filename, image_bytes, "image/png")},
    )
    resp.raise_for_status()
    print(f"[OK] Discord 圖片推送成功 ({resp.status_code}) - {filename}")
    time.sleep(1)  # 避免 rate limit

# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def main():
    from image_generator import (
        generate_season_top10, generate_today_top10,
        generate_today_bottom5, generate_free_agent_top5,
        generate_weekly_report,
    )

    today       = date.today()
    today_str   = today.strftime("%Y/%m/%d")
    is_monday   = today.weekday() == 0  # 週一
    print(f"[{today_str}] 開始執行 Yahoo Fantasy MLB Bot... (週一={is_monday})")

    token = refresh_access_token()
    print("取得 Token 成功")

    # ── 本季累積 ──
    print("抓取本季累積數據...")
    season_raw   = fetch_all_players(token, "season")
    all_players  = parse_players(season_raw)
    all_players.sort(key=lambda x: x["score"], reverse=True)
    season_top10 = all_players[:10]

    for i, p in enumerate(season_top10, 1):
        print(f"  {i:>2}. {p['name']:<22} {p['score']:>7.1f}  pos='{p['position']}'")

    # ── 抓各隊 Roster Owner Map ──
    print("抓取各隊 roster 對應表...")
    owner_map = fetch_player_owner_map(token)

    # 把 owner 資訊加到每個球員
    for p in all_players:
        key = f"{p['name']}|{p['team']}"
        p["owner"] = owner_map.get(key) or owner_map.get(p["name"], "Free Agent")

    # ── Free Agent：all_players 裡不在 owner_map 的就是 FA ──
    # ── Free Agent TOP5（近兩天成績）──
    print("抓取 FA 近兩天成績...")
    from datetime import timedelta
    yesterday   = today - timedelta(days=1)
    day_before  = today - timedelta(days=2)

    # 抓兩天的 FA 數據並合計分數
    fa_scores = {}   # {name: {info + score}}

    for day in [yesterday, day_before]:
        day_str = day.strftime("%Y-%m-%d")
        raw = fetch_fa_players_date(token, day_str)
        players_day = parse_players(raw)
        for p in players_day:
            if p["score"] == 0:
                continue
            if p["name"] not in fa_scores:
                fa_scores[p["name"]] = {
                    "name": p["name"], "team": p["team"],
                    "position": p["position"], "is_pitcher": p["is_pitcher"],
                    "owner": "Free Agent", "score": 0.0,
                }
            fa_scores[p["name"]]["score"] += p["score"]

    fa_list = sorted(fa_scores.values(), key=lambda x: x["score"], reverse=True)
    fa_top5 = fa_list[:5]
    print(f"  近兩天有得分的 FA={len(fa_list)}")
    for p in fa_top5:
        print(f"    FA: {p['name']:<22} {p['score']:.1f}")

    # ── 近兩天累積數據 ──
    print("抓取近兩天數據...")
    from datetime import timedelta
    two_day_scores = {}   # {name: {info + score}}
    two_day_opps   = {}   # {name: [對手1, 對手2]}

    for day in [today - timedelta(days=1), today - timedelta(days=2)]:
        day_str  = day.strftime("%Y-%m-%d")
        schedule = fetch_schedule(day_str)   # {team: "vs OPP"}
        raw = fetch_all_players(token, "date", day_str)
        players_day = parse_players(raw)
        for p in players_day:
            if p["score"] == 0:
                continue
            name = p["name"]
            if name not in two_day_scores:
                two_day_scores[name] = {
                    "name":       name,
                    "team":       p["team"],
                    "position":   p["position"],
                    "is_pitcher": p["is_pitcher"],
                    "owner":      owner_map.get(f"{name}|{p['team']}") or owner_map.get(name, "Free Agent"),
                    "score":      0.0,
                }
                two_day_opps[name] = []
            two_day_scores[name]["score"] += p["score"]
            opp = schedule.get(p["team"], "")
            if opp and opp not in two_day_opps[name]:
                two_day_opps[name].append(opp)
        print(f"  {day_str} 抓取完畢")

    # 把對手資訊合併進去，格式：vs LAD · vs NYY
    for name, p in two_day_scores.items():
        opps = two_day_opps.get(name, [])
        p["opponent"] = "  ·  ".join(opps) if opps else ""

    played = sorted(two_day_scores.values(), key=lambda x: x["score"], reverse=True)
    today_top10   = played[:10]
    today_bottom5 = sorted(two_day_scores.values(), key=lambda x: x["score"])[:5]
    print(f"  近兩天有得分球員共 {len(played)} 位")

    # ── 排名快取 ──
    prev_ranks = load_prev_ranks()
    new_ranks  = {p["name"]: i + 1 for i, p in enumerate(season_top10)}

    # ── 產生圖卡並發送 ──
    print("產生圖卡並推送到 Discord...")

    # 1. 本季 TOP10
    img = generate_season_top10(season_top10, prev_ranks, today_str)
    send_discord_image(img, "season_top10.png")

    # 2. 今日 TOP10（有上場才發）
    if today_top10:
        img = generate_today_top10(today_top10, today_str)
        send_discord_image(img, "today_top10.png")

    # 3. 今日 BOTTOM5（有上場才發）
    if today_bottom5:
        img = generate_today_bottom5(today_bottom5, today_str)
        send_discord_image(img, "today_bottom5.png")

    # MVP 點評（今日有比賽才發）
    if today_top10 and today_bottom5:
        print("產生 MVP 點評...")
        comment = generate_mvp_comment(today_top10[0], today_bottom5[0])
        if comment:
            mvp = today_top10[0]
            loser = today_bottom5[0]
            mvp_name  = mvp["name"]
            mvp_owner = mvp["owner"]
            mvp_score = mvp["score"]
            bot_name  = loser["name"]
            bot_owner = loser["owner"]
            bot_score = loser["score"]
            line1 = f"🏆 **近兩天 MVP：{mvp_name}**（{mvp_owner}）`{mvp_score:+.1f}pts`"
            line2 = f"💀 **近兩天墊底：{bot_name}**（{bot_owner}）`{bot_score:+.1f}pts`"
            line3 = f"🤖 {comment}"
            msg = line1 + "\n" + line2 + "\n\n" + line3
            send_discord_text(msg)

    # 4. Free Agent TOP5（有資料才發）
    if fa_top5:
        img = generate_free_agent_top5(fa_top5, today_str)
        send_discord_image(img, "free_agent_top5.png")

    # 5. 週報（只有週一發）
    if is_monday:
        print("今天是週一，產生週報...")
        from datetime import timedelta
        last_mon = today - timedelta(days=7)
        last_sun = today - timedelta(days=1)
        week_label = f"{last_mon.strftime('%m/%d')} – {last_sun.strftime('%m/%d')}"
        img = generate_weekly_report(season_top10, week_label)
        send_discord_image(img, "weekly_report.png")

    save_ranks(new_ranks)
    print("完成！")


if __name__ == "__main__":
    main()
