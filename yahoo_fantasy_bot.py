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
# OAuth Token 更新
# ─────────────────────────────────────────────
def refresh_access_token():
    resp = requests.post(
        "https://api.login.yahoo.com/oauth2/get_token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": YAHOO_REFRESH_TOKEN,
        },
        auth=(YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


# ─────────────────────────────────────────────
# Yahoo Fantasy API 請求
# ─────────────────────────────────────────────
def yahoo_get(url, token):
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def get_all_players_stats(token, stats_type: str, date_str: str = None):
    """
    分頁抓取聯盟內所有球員數據（每次25筆，循環直到抓完）
    stats_type: "season" 或 "date"
    """
    base = "https://fantasysports.yahooapis.com/fantasy/v2"
    league_key = YAHOO_LEAGUE_ID
    all_players = []
    start = 0
    page_size = 25

    while True:
        if stats_type == "season":
            url = (
                f"{base}/league/{league_key}/players;status=T"
                f";start={start};count={page_size}"
                f"/stats;type=season?format=json"
            )
        else:
            url = (
                f"{base}/league/{league_key}/players;status=T"
                f";start={start};count={page_size}"
                f"/stats;type=date;date={date_str}?format=json"
            )

        data = yahoo_get(url, token)
        try:
            league = data["fantasy_content"]["league"][1]
            player_list = league["players"]
            count = player_list.get("count", 0)
        except Exception:
            break

        if count == 0:
            break

        # 合併到總列表（把這頁的 players 加進去）
        for i in range(count):
            all_players_entry = player_list.get(str(i))
            if all_players_entry:
                # 建立單頁格式的假 data 結構方便 parse_players 重用
                all_players.append(all_players_entry)

        print(f"  已抓取 {start + count} 位球員...")

        if count < page_size:
            break
        start += page_size
        time.sleep(0.5)  # 避免 API rate limit

    # 包裝成 parse_players 可以讀的格式
    players_dict = {str(i): all_players[i] for i in range(len(all_players))}
    players_dict["count"] = len(all_players)
    fake_data = {
        "fantasy_content": {
            "league": [
                {},
                {"players": players_dict}
            ]
        }
    }
    return fake_data


def get_league_players_season_stats(token):
    print("  分頁抓取本季累積數據...")
    return get_all_players_stats(token, "season")


def get_league_players_today_stats(token):
    today = date.today().strftime("%Y-%m-%d")
    print(f"  分頁抓取今日({today})數據...")
    return get_all_players_stats(token, "date", today)


# ─────────────────────────────────────────────
# 計分計算
# ─────────────────────────────────────────────
def calc_score(stats: dict, is_pitcher: bool) -> float:
    """根據聯盟規則計算 fantasy 積分"""
    scoring = PITCHER_SCORING if is_pitcher else BATTER_SCORING
    stat_ids = PITCHER_STAT_IDS if is_pitcher else BATTER_STAT_IDS

    total = 0.0
    for stat_name, points in scoring.items():
        sid = stat_ids.get(stat_name)
        if sid and sid in stats:
            try:
                val = float(stats[sid])
                total += val * points
            except (ValueError, TypeError):
                pass
    return round(total, 2)


def parse_players(data: dict):
    """解析 Yahoo API 回傳，產生 [{name, team, position, is_pitcher, stats, score}]"""
    players = []
    try:
        league = data["fantasy_content"]["league"][1]
        player_list = league["players"]
        count = player_list["count"]

        for i in range(count):
            p = player_list[str(i)]["player"]
            info = p[0]
            stats_raw = p[1]["player_stats"]["stats"]

            # 基本資訊
            name = info[2]["name"]["full"]

            # 抓隊伍
            team = "N/A"
            for item in info:
                if isinstance(item, dict) and "editorial_team_abbr" in item:
                    team = item["editorial_team_abbr"]
                    break

            # 抓守位 display_position（例如 "SP", "2B", "OF"）
            position = ""
            for item in info:
                if isinstance(item, dict):
                    if "display_position" in item:
                        position = item["display_position"]
                        break
                    # 有些版本放在 eligible_positions 裡
                    if "eligible_positions" in item:
                        ep = item["eligible_positions"]
                        if isinstance(ep, dict):
                            pos_list = [v for v in ep.values() if isinstance(v, dict)]
                            positions = [p.get("position", "") for p in pos_list]
                            position = ",".join(p for p in positions if p and p != "BN" and p != "DL" and p != "NA")
                        break

            # 判斷投手：SP, RP, P 都算投手
            pitcher_positions = {"SP", "RP", "P"}
            pos_set = set(position.replace(",", " ").split())
            is_pitcher = bool(pos_set & pitcher_positions)

            # 整理 stats dict {stat_id: value}
            stats = {}
            for s in stats_raw:
                sid = s["stat"]["stat_id"]
                sval = s["stat"]["value"]
                stats[sid] = sval

            score = calc_score(stats, is_pitcher)
            # DEBUG position (移除後請刪此行)
            if name in ("Sandy Alcantara", "Drake Baldwin"):
                print(f"[POS DEBUG] {name} | position='{position}' | info_keys={[list(x.keys()) if isinstance(x,dict) else x for x in info[:8]]}")
            players.append({
                "name": name,
                "team": team,
                "position": position,   # 例如 "SP", "2B,OF", "C"
                "is_pitcher": is_pitcher,
                "score": score,
                "stats": stats,
            })
    except Exception as e:
        print(f"[WARN] parse error: {e}")

    return players


# ─────────────────────────────────────────────
# 排名快取
# ─────────────────────────────────────────────
def load_prev_ranks() -> dict:
    if Path(RANK_CACHE_FILE).exists():
        with open(RANK_CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_ranks(ranks: dict):
    with open(RANK_CACHE_FILE, "w") as f:
        json.dump(ranks, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
# Discord 訊息格式化（手機優化版）
# 每行格式：名字縮短到名+姓第一字，控制在25字內
# ─────────────────────────────────────────────
def rank_arrow(change: int) -> str:
    if change > 0:
        return f"▲{change}"
    elif change < 0:
        return f"▼{abs(change)}"
    else:
        return "–"

def short_name(full_name: str) -> str:
    """縮短名字：Shohei Ohtani → S.Ohtani"""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0][0]}.{parts[-1]}"
    return full_name[:10]

def build_discord_message(
    season_top10: list,
    prev_ranks: dict,
    today_top10: list,
    today_bottom5: list,
    today_date: str,
) -> list:
    """回傳多個 Discord embed dict（手機友善格式）"""
    embeds = []

    # ── Embed 1: 本季累積得分前10名 ──
    # 格式：1. 🏏 S.Ohtani  129.2 🟢▲2
    season_lines = []
    for i, p in enumerate(season_top10, 1):
        score = p["score"]
        prev = prev_ranks.get(p["name"])
        if prev is None:
            change_str = "🆕"
        else:
            diff = prev - i
            change_str = rank_arrow(diff)
            if diff > 0:
                change_str = f"🟢{change_str}"
            elif diff < 0:
                change_str = f"🔴{change_str}"
            else:
                change_str = "⚪–"
        pos = p.get("position", "??") or "??"
        season_lines.append(f"`{i:>2}.` `{p['name']:<20}` `{score:>6.1f}` **{pos}** {change_str}")

    embeds.append({
        "title": f"📊 本季 TOP10 | {today_date}",
        "description": "
".join(season_lines),
        "color": 0x1E90FF,
        "footer": {"text": "Yahoo Fantasy MLB • 每日自動更新"},
    })

    # ── Embed 2: 今日得分前10名 ──
    if today_top10:
        today_lines = []
        for i, p in enumerate(today_top10, 1):
            pos = p.get("position", "??") or "??"
            today_lines.append(f"`{i:>2}.` `{p['name']:<20}` `{p['score']:>+6.1f}` **{pos}**")
        embeds.append({
            "title": "🔥 今日得分 TOP10",
            "description": "
".join(today_lines),
            "color": 0xFFA500,
        })

    # ── Embed 3: 今日得分最低5名 ──
    if today_bottom5:
        bottom_lines = []
        for i, p in enumerate(today_bottom5, 1):
            pos = p.get("position", "??") or "??"
            bottom_lines.append(f"`{i:>2}.` `{p['name']:<20}` `{p['score']:>+6.1f}` **{pos}**")
        embeds.append({
            "title": "🥶 今日得分 BOTTOM5",
            "description": "
".join(bottom_lines),
            "color": 0xFF4444,
        })

    return embeds


def send_discord(embeds: list):
    payload = {"embeds": embeds}
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    resp.raise_for_status()
    print(f"[OK] Discord 推送成功 ({resp.status_code})")


# ─────────────────────────────────────────────
# DEBUG：印出原始 stat ID（確認對應正確後可刪除）
# ─────────────────────────────────────────────
def debug_print_raw_stats(data: dict, target_name: str = "Chris Sale"):
    """印出指定球員的原始 stat ID 和數值，用來校正 stat ID 對應表"""
    try:
        league = data["fantasy_content"]["league"][1]
        player_list = league["players"]
        count = player_list["count"]
        for i in range(count):
            p = player_list[str(i)]["player"]
            info = p[0]
            name = info[2]["name"]["full"]
            if target_name.lower() in name.lower():
                stats_raw = p[1]["player_stats"]["stats"]
                print(f"\n{'='*50}")
                print(f"DEBUG 原始數據 - {name}")
                print(f"{'='*50}")
                for s in stats_raw:
                    sid = s["stat"]["stat_id"]
                    sval = s["stat"]["value"]
                    if sval not in ("", "-", None, "0", 0):
                        print(f"  stat_id={sid:>5}  value={sval}")
                print(f"{'='*50}\n")
                return
        print(f"[DEBUG] 找不到球員: {target_name}")
    except Exception as e:
        print(f"[DEBUG ERROR] {e}")


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def main():
    today_str = date.today().strftime("%Y/%m/%d")
    print(f"[{today_str}] 開始執行 Yahoo Fantasy MLB Bot...")

    # 1. 取得 token
    print("取得 Yahoo OAuth Token...")
    token = refresh_access_token()

    # 2. 本季累積數據
    print("抓取本季累積數據...")
    season_data = get_league_players_season_stats(token)



    all_players = parse_players(season_data)
    all_players.sort(key=lambda x: x["score"], reverse=True)
    season_top10 = all_players[:10]

    # 3. 今日數據
    print("抓取今日數據...")
    today_data = get_league_players_today_stats(token)
    today_players = parse_players(today_data)
    # 過濾今日有上場的球員（score != 0 或有任何非零 stat）
    INVALID_VALUES = {"", "-", None, "-/-", "—", "N/A"}
    def is_nonzero(v):
        if v in INVALID_VALUES:
            return False
        try:
            return float(v) != 0
        except (ValueError, TypeError):
            return False

    played_today = [p for p in today_players if p["score"] != 0 or any(
        is_nonzero(v) for v in p["stats"].values()
    )]
    played_today.sort(key=lambda x: x["score"], reverse=True)
    today_top10 = played_today[:10]
    today_bottom5 = sorted(played_today, key=lambda x: x["score"])[:5]

    # 4. 排名比較
    prev_ranks = load_prev_ranks()
    new_ranks = {p["name"]: i + 1 for i, p in enumerate(season_top10)}

    # 5. Discord 推送
    print("推送到 Discord...")
    embeds = build_discord_message(season_top10, prev_ranks, today_top10, today_bottom5, today_str)
    send_discord(embeds)

    # 6. 儲存今日排名
    # 合併：只保留前10名
    save_ranks(new_ranks)
    print("完成！排名快取已更新。")


if __name__ == "__main__":
    main()
