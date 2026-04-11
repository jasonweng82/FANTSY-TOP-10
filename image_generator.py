"""
image_generator.py - ESPN 深色風格圖卡
每行顯示：排名 | 球員名 + 隊伍·守位 + Owner | POS徽章 | 分數 | 趨勢
"""

from PIL import Image, ImageDraw, ImageFont
import io

FONT_REG  = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
EN_REG    = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
EN_BOLD   = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

BG_DARK   = "#0f1923"
BG_ROW1   = "#1a2535"
BG_ROW2   = "#131f2e"
BG_BADGE  = "#1d3a5f"
BG_OWNER  = "#1a2d1a"
BLUE_BAR  = "#2563eb"
BLUE_LT   = "#60a5fa"
PURPLE    = "#c084fc"
GOLD      = "#f59e0b"
GREEN     = "#22c55e"
GREEN_LT  = "#4ade80"
RED       = "#ef4444"
NEW_BLUE  = "#3b82f6"
WHITE     = "#ffffff"
GRAY      = "#94a3b8"
DK_GRAY   = "#64748b"
DIVIDER   = "#1e2d3d"
FOOTER_C  = "#374151"

W        = 880
ROW_H    = 96
PAD_X    = 28
Y_HEADER = 152

def _fonts():
    defs = [
        ("title",  FONT_BOLD, 34), ("sub",     FONT_REG,  22),
        ("rank",   EN_BOLD,   30), ("name",    EN_BOLD,   25),
        ("detail", FONT_REG,  19), ("owner",   FONT_REG,  18),
        ("pos",    EN_BOLD,   19), ("score",   EN_BOLD,   27),
        ("footer", FONT_REG,  18),
    ]
    out = {}
    for name, path, size in defs:
        try:    out[name] = ImageFont.truetype(path, size)
        except: out[name] = ImageFont.load_default()
    return out

def _canvas(n_rows):
    H   = Y_HEADER + n_rows * ROW_H + 72
    img = Image.new("RGB", (W, H), BG_DARK)
    return img, ImageDraw.Draw(img)

def _header(d, fonts, title, subtitle):
    d.rectangle([0, 0, W, 8], fill=BLUE_BAR)
    d.text((PAD_X, 24), title,    font=fonts["title"], fill=WHITE)
    d.text((PAD_X, 68), subtitle, font=fonts["sub"],   fill=DK_GRAY)
    d.line([(PAD_X, 106), (W-PAD_X, 106)], fill=DIVIDER, width=2)
    for x, label in [(PAD_X, "#"), (78, "PLAYER / OWNER"), (560, "POS"), (660, "PTS"), (790, "TREND")]:
        d.text((x, 118), label, font=fonts["detail"], fill=DK_GRAY)

def _row(d, fonts, rank, name, team, pos, owner, score, trend, tcol, bar_col):
    y  = Y_HEADER + (rank - 1) * ROW_H
    bg = BG_ROW1 if rank == 1 else BG_ROW2
    d.rounded_rectangle([18, y, W-18, y+ROW_H-6], radius=8, fill=bg)
    d.rounded_rectangle([18, y, 25,   y+ROW_H-6], radius=4, fill=bar_col)

    # 排名
    d.text((34, y+24), str(rank), font=fonts["rank"],
           fill=GOLD if rank == 1 else GRAY)

    # 球員名字
    d.text((78, y+8), (name or "")[:24], font=fonts["name"], fill=WHITE)

    # 隊伍 · 守位
    d.text((78, y+42), f"{team}  ·  {pos}", font=fonts["detail"], fill=DK_GRAY)

    # Owner 標籤
    owner_str = (owner or "Free Agent")[:22]
    # 畫 owner 小徽章
    bbox = d.textbbox((0, 0), owner_str, font=fonts["owner"])
    ow   = bbox[2] - bbox[0] + 14
    ox   = 78
    oy   = y + 66
    owner_bg = BG_OWNER if owner_str != "Free Agent" else "#1d2d3d"
    owner_col = GREEN_LT if owner_str != "Free Agent" else NEW_BLUE
    d.rounded_rectangle([ox, oy, ox+ow, oy+22], radius=4, fill=owner_bg)
    d.text((ox+7, oy+3), owner_str, font=fonts["owner"], fill=owner_col)

    # POS 徽章
    ps   = (pos or "??")[:4]
    d.rounded_rectangle([550, y+22, 644, y+56], radius=4, fill=BG_BADGE)
    bbox = d.textbbox((0, 0), ps, font=fonts["pos"])
    pw   = bbox[2] - bbox[0]
    pcol = PURPLE if pos in ("SP","RP","P","SP,RP") else BLUE_LT
    d.text((597 - pw//2, y+30), ps, font=fonts["pos"], fill=pcol)

    # 分數
    d.text((652, y+22), f"{score:.1f}", font=fonts["score"], fill=WHITE)

    # 趨勢
    d.text((790, y+22), trend, font=fonts["score"], fill=tcol)

def _footer(d, fonts, n_rows, label="Yahoo Fantasy MLB Bot"):
    y = Y_HEADER + n_rows * ROW_H + 10
    d.line([(PAD_X, y), (W-PAD_X, y)], fill=DIVIDER, width=1)
    d.text((PAD_X,   y+14), label,        font=fonts["footer"], fill=FOOTER_C)
    d.text((W-PAD_X, y+14), "每日自動更新", font=fonts["footer"], fill=FOOTER_C, anchor="ra")

def _to_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()

def _bar(pos):
    return PURPLE if pos in ("SP","RP","P","SP,RP") else BLUE_LT

def _trend(prev_ranks, name, i):
    prev = prev_ranks.get(name)
    if prev is None:  return "NEW", NEW_BLUE
    diff = prev - i
    if diff > 0:      return f"▲{diff}", GREEN
    if diff < 0:      return f"▼{abs(diff)}", RED
    return "–", GRAY


def generate_season_top10(players, prev_ranks, today_str) -> bytes:
    fonts = _fonts()
    img, d = _canvas(len(players))
    _header(d, fonts, "本季累積得分 TOP 10", f"{today_str}  ·  Yahoo Fantasy MLB")
    for i, p in enumerate(players, 1):
        tr, tc = _trend(prev_ranks, p["name"], i)
        _row(d, fonts, i, p["name"], p["team"], p["position"],
             p.get("owner", ""), p["score"], tr, tc, _bar(p["position"]))
    _footer(d, fonts, len(players))
    return _to_bytes(img)


def generate_today_top10(players, today_str) -> bytes:
    fonts = _fonts()
    img, d = _canvas(len(players))
    _header(d, fonts, "今日得分 TOP 10", f"{today_str}  ·  Yahoo Fantasy MLB")
    for i, p in enumerate(players, 1):
        sc = p["score"]
        tr = f"+{sc:.1f}" if sc >= 0 else f"{sc:.1f}"
        tc = GREEN if sc > 0 else (RED if sc < 0 else GRAY)
        _row(d, fonts, i, p["name"], p["team"], p["position"],
             p.get("owner", ""), sc, tr, tc, _bar(p["position"]))
    _footer(d, fonts, len(players), "今日得分排行")
    return _to_bytes(img)


def generate_today_bottom5(players, today_str) -> bytes:
    fonts = _fonts()
    img, d = _canvas(len(players))
    _header(d, fonts, "今日得分 BOTTOM 5", f"{today_str}  ·  Yahoo Fantasy MLB")
    for i, p in enumerate(players, 1):
        sc = p["score"]
        _row(d, fonts, i, p["name"], p["team"], p["position"],
             p.get("owner", ""), sc, f"{sc:.1f}", RED, _bar(p["position"]))
    _footer(d, fonts, len(players), "今日得分墊底")
    return _to_bytes(img)


def generate_free_agent_top5(players, today_str) -> bytes:
    fonts = _fonts()
    img, d = _canvas(len(players))
    _header(d, fonts, "本季 Free Agent TOP 5", f"{today_str}  ·  強烈推薦撿人")
    for i, p in enumerate(players, 1):
        _row(d, fonts, i, p["name"], p["team"], p["position"],
             "Free Agent", p["score"], "FA", NEW_BLUE, _bar(p["position"]))
    _footer(d, fonts, len(players), "Free Agent 推薦")
    return _to_bytes(img)


def generate_weekly_report(players, week_label) -> bytes:
    fonts = _fonts()
    img, d = _canvas(len(players))
    _header(d, fonts, "本週得分 TOP 10", f"{week_label}  ·  Yahoo Fantasy MLB 週報")
    for i, p in enumerate(players, 1):
        _row(d, fonts, i, p["name"], p["team"], p["position"],
             p.get("owner", ""), p["score"], f"{p['score']:.1f}", BLUE_LT, _bar(p["position"]))
    _footer(d, fonts, len(players), "每週一自動發送")
    return _to_bytes(img)
